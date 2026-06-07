# Music Stream

PC hard disk ထဲက သီချင်းတွေကို Phone နဲ့ WiFi ကနေ stream နားထောင်လို့ ရတဲ့ local web app။

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
python app.py
```

Terminal မှာ Phone အတွက် URL ပြပေးမယ် → ဥပမာ `http://192.168.1.5:5050`

## Phone မှာ သုံးနည်း

1. PC နဲ့ Phone တစ်ခုတည်းသော WiFi ချိတ်ပါ
2. `python app.py` run ပါ
3. Terminal မှာ ပြတဲ့ IP address ကို Phone browser မှာ ဖွင့်ပါ
4. Music folder path ထည့်ပြီး Load Music နှိပ်ပါ

## Features

- MP3 / FLAC / WAV / M4A / OGG stream
- Embedded album artwork ပြ
- Prev / Play / Pause / Next controls
- Seek (progress bar)
- Organize tab — Artist/Album/Song structure
- MusicBrainz metadata auto-fill
