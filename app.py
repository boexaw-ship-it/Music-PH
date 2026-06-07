import os, re, shutil, socket, threading, webbrowser, mimetypes
from pathlib import Path
from flask import Flask, jsonify, request, render_template, send_file, Response, abort

try:
    from mutagen.easyid3 import EasyID3
    from mutagen.id3 import ID3
    from mutagen.mp3 import MP3
    from mutagen.flac import FLAC
    from mutagen.mp4 import MP4
    MUTAGEN_OK = True
except ImportError:
    MUTAGEN_OK = False

try:
    import requests as req_lib
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

app = Flask(__name__)

AUDIO_EXTS = {'.mp3', '.flac', '.wav', '.m4a', '.ogg', '.aac'}

# ── helpers ──────────────────────────────────────────────────────────────────

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def sanitize(name):
    return re.sub(r'[\\/*?:"<>|]', '_', str(name)).strip() or "Unknown"

def read_tags(path):
    info = {"artist": "", "album": "", "title": "", "duration": 0}
    if not MUTAGEN_OK:
        return info
    ext = Path(path).suffix.lower()
    try:
        if ext == '.mp3':
            tags = EasyID3(path)
            info["artist"] = tags.get("artist", [""])[0]
            info["album"]  = tags.get("album",  [""])[0]
            info["title"]  = tags.get("title",  [""])[0]
            audio = MP3(path)
            info["duration"] = int(audio.info.length)
        elif ext == '.flac':
            audio = FLAC(path)
            info["artist"] = (audio.get("artist") or [""])[0]
            info["album"]  = (audio.get("album")  or [""])[0]
            info["title"]  = (audio.get("title")  or [""])[0]
            info["duration"] = int(audio.info.length)
        elif ext == '.m4a':
            audio = MP4(path)
            info["artist"] = str((audio.get("\xa9ART") or [""])[0])
            info["album"]  = str((audio.get("\xa9alb") or [""])[0])
            info["title"]  = str((audio.get("\xa9nam") or [""])[0])
            info["duration"] = int(audio.info.length)
    except Exception:
        pass
    return info

def scan_folder(folder):
    results = []
    for root, _, files in os.walk(folder):
        for fname in sorted(files):
            if Path(fname).suffix.lower() in AUDIO_EXTS:
                full = os.path.join(root, fname)
                tags = read_tags(full)
                results.append({
                    "path":     full,
                    "filename": fname,
                    "artist":   tags["artist"] or "Unknown Artist",
                    "album":    tags["album"]  or "Unknown Album",
                    "title":    tags["title"]  or Path(fname).stem,
                    "duration": tags["duration"],
                    "ext":      Path(fname).suffix.lower(),
                })
    return results

def fmt_duration(secs):
    m, s = divmod(secs, 60)
    return f"{m}:{s:02d}"

# ── routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", local_ip=get_local_ip())

@app.route("/api/scan", methods=["POST"])
def api_scan():
    folder = (request.json or {}).get("folder", "").strip()
    if not folder or not os.path.isdir(folder):
        return jsonify({"error": "Invalid folder"}), 400
    files = scan_folder(folder)
    return jsonify({"files": files, "count": len(files)})

@app.route("/api/stream")
def api_stream():
    path = request.args.get("path", "")
    if not path or not os.path.isfile(path):
        abort(404)
    ext  = Path(path).suffix.lower()
    mime = {
        ".mp3": "audio/mpeg", ".flac": "audio/flac",
        ".wav": "audio/wav",  ".m4a": "audio/mp4",
        ".ogg": "audio/ogg",  ".aac": "audio/aac",
    }.get(ext, "application/octet-stream")

    # range request support (needed for seek on mobile)
    size = os.path.getsize(path)
    range_header = request.headers.get("Range")
    if range_header:
        byte1, byte2 = 0, None
        m = re.search(r'(\d+)-(\d*)', range_header)
        if m:
            byte1 = int(m.group(1))
            byte2 = int(m.group(2)) if m.group(2) else size - 1
        length = byte2 - byte1 + 1
        def generate():
            with open(path, 'rb') as f:
                f.seek(byte1)
                remaining = length
                while remaining:
                    chunk = f.read(min(65536, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk
        rv = Response(generate(), 206, mimetype=mime, direct_passthrough=True)
        rv.headers.add('Content-Range', f'bytes {byte1}-{byte2}/{size}')
        rv.headers.add('Accept-Ranges', 'bytes')
        rv.headers.add('Content-Length', str(length))
        return rv

    return send_file(path, mimetype=mime, conditional=True)

@app.route("/api/cover")
def api_cover():
    """Serve embedded cover art from MP3."""
    path = request.args.get("path", "")
    if not path or not os.path.isfile(path):
        abort(404)
    try:
        raw = ID3(path)
        for key in raw.keys():
            if key.startswith("APIC"):
                apic = raw[key]
                return Response(apic.data, mimetype=apic.mime)
    except Exception:
        pass
    abort(404)

@app.route("/api/enrich", methods=["POST"])
def api_enrich():
    if not REQUESTS_OK:
        return jsonify({"artist":"","album":"","title":""})
    data   = request.json or {}
    artist = data.get("artist","")
    title  = data.get("title","")
    result = {"artist": artist, "album": "", "title": title}
    q_parts = []
    if artist and artist != "Unknown Artist": q_parts.append(f'artist:"{artist}"')
    if title  and title  != "Unknown":        q_parts.append(f'recording:"{title}"')
    if not q_parts:
        return jsonify(result)
    try:
        r = req_lib.get(
            "https://musicbrainz.org/ws/2/recording/",
            params={"query": " AND ".join(q_parts), "fmt":"json","limit":1},
            headers={"User-Agent":"MusicStream/1.0 (local)"},
            timeout=6,
        )
        recs = r.json().get("recordings",[])
        if recs:
            rec = recs[0]
            result["title"] = rec.get("title", title)
            ac = rec.get("artist-credit",[])
            if ac: result["artist"] = ac[0].get("artist",{}).get("name", artist)
            rels = rec.get("releases",[])
            if rels: result["album"] = rels[0].get("title","")
    except Exception:
        pass
    return jsonify(result)

@app.route("/api/preview", methods=["POST"])
def api_preview():
    data = request.json or {}
    files = data.get("files",[])
    out   = data.get("output_root","").strip()
    if not out: return jsonify({"error":"No output folder"}),400
    previews = []
    for f in files:
        ext  = Path(f.get("filename","x.mp3")).suffix
        dest = os.path.join(out, sanitize(f.get("artist","Unknown Artist")),
                            sanitize(f.get("album","Unknown Album")),
                            sanitize(f.get("title","track")) + ext)
        previews.append({"src": f["path"], "dest": dest})
    return jsonify({"previews": previews})

@app.route("/api/organize", methods=["POST"])
def api_organize():
    data  = request.json or {}
    files = data.get("files",[])
    out   = data.get("output_root","").strip()
    if not out: return jsonify({"error":"No output folder"}),400
    moved, errors = [], []
    for f in files:
        src = f["path"]
        ext = Path(f.get("filename","x.mp3")).suffix
        dest = os.path.join(out, sanitize(f.get("artist","Unknown Artist")),
                            sanitize(f.get("album","Unknown Album")),
                            sanitize(f.get("title","track")) + ext)
        try:
            Path(os.path.dirname(dest)).mkdir(parents=True, exist_ok=True)
            if os.path.exists(dest):
                base, e = os.path.splitext(dest)
                dest = f"{base}_1{e}"
            shutil.move(src, dest)
            moved.append({"src":src,"dest":dest})
        except Exception as e:
            errors.append({"file":src,"error":str(e)})
    return jsonify({"moved":len(moved),"errors":errors,"details":moved})

# ── run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = 5050
    ip   = get_local_ip()
    print(f"\n  ╔══════════════════════════════════════╗")
    print(f"  ║  Music Stream  →  http://{ip}:{port}  ║")
    print(f"  ║  PC browser   →  http://127.0.0.1:{port} ║")
    print(f"  ╚══════════════════════════════════════╝\n")
    threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    app.run(host="0.0.0.0", port=port, debug=False)
