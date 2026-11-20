import json
import os
import re
import subprocess
import textwrap
from datetime import datetime
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOPIK_FILE = os.path.join(BASE_DIR, "topik.txt")
OUT_DIR = os.path.join(BASE_DIR, "hasil_shorts")


def parse_topik_txt(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    title = "Tips Singkat & Bermanfaat"
    source = ""
    slides = []
    current = None

    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.lower().startswith("judul:"):
            title = s.split(":", 1)[1].strip()
        elif s.lower().startswith("sumber:"):
            source = s.split(":", 1)[1].strip()
        elif re.match(r"^poin\s*\d*\s*:", s.lower()):
            if current:
                slides.append(current)
            current = {
                "headline": s.split(":", 1)[1].strip(),
                "body": "",
                "narration": "",
            }
        elif s.lower().startswith("isi:") and current is not None:
            current["body"] = s.split(":", 1)[1].strip()
        elif s.lower().startswith("narasi:") and current is not None:
            current["narration"] = s.split(":", 1)[1].strip()

    if current:
        slides.append(current)

    if not slides:
        slides = [
            {
                "headline": title,
                "body": "Ringkasan poin utama hari ini.",
                "narration": f"Hari ini kita membahas {title}. Simak poin pentingnya berikut ini.",
            }
        ]

    for item in slides:
        if not item["narration"]:
            item["narration"] = f"{item['headline']}. {item['body']}".strip()
        if not item["body"]:
            item["body"] = item["headline"]

    return {"title": title, "source": source, "slides": slides[:5]}


def get_font(size: int, bold: bool = False):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size=size)
    return ImageFont.load_default()


def make_voice(text: str, out_mp3: str) -> None:
    subprocess.run(
        ["edge-tts", "--voice", "id-ID-GadisNeural", "--text", text, "--write-media", out_mp3],
        check=True,
    )


def get_duration(file_path: str) -> float:
    res = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return max(float(res.stdout.strip()), 1.0)


def make_slide_img(idx: int, total: int, title_video: str, headline: str, body: str, out_png: str) -> None:
    w, h = 1080, 1920
    img = Image.new("RGB", (w, h), (15, 23, 42))
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, w, 20], fill=(239, 68, 68))
    draw.rounded_rectangle([65, 300, w - 65, h - 300], radius=36, fill=(30, 41, 59), outline=(71, 85, 105), width=3)

    f_top = get_font(28, bold=True)
    f_head = get_font(54, bold=True)
    f_body = get_font(40, bold=False)
    f_foot = get_font(28, bold=False)

    draw.text((115, 355), f"BAGIAN {idx + 1}/{total} • SHORTS", fill=(248, 113, 113), font=f_top)

    y = 430
    for line in textwrap.wrap(headline, width=26):
        draw.text((115, y), line, fill=(255, 255, 255), font=f_head)
        y += 68

    y += 18
    draw.line([(115, y), (w - 115, y)], fill=(100, 116, 139), width=3)
    y += 42

    for line in textwrap.wrap(body, width=35):
        draw.text((115, y), line, fill=(226, 232, 240), font=f_body)
        y += 56

    for line in textwrap.wrap(title_video, width=42)[:2]:
        draw.text((115, h - 410), line, fill=(148, 163, 184), font=f_foot)

    img.save(out_png)


def make_clip(img_png: str, audio_mp3: str, out_mp4: str) -> None:
    dur = get_duration(audio_mp3)
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-loop", "1", "-i", img_png,
            "-i", audio_mp3,
            "-t", f"{dur:.2f}",
            "-c:v", "libx264", "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-vf", "scale=1080:1920",
            out_mp4,
        ],
        check=True,
    )


def merge_clips(clips: list[str], final_mp4: str) -> None:
    list_txt = os.path.join(os.path.dirname(final_mp4), "list.txt")
    with open(list_txt, "w", encoding="utf-8") as f:
        for c in clips:
            f.write(f"file '{c}'\n")

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", list_txt,
            "-c:v", "libx264", "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            final_mp4,
        ],
        check=True,
    )


def build_desc(data: dict) -> str:
    lines = [data["title"], "", "Ringkasan:"]
    for i, s in enumerate(data["slides"], start=1):
        lines.append(f"{i}. {s['headline']} - {s['body']}")
    if data["source"]:
        lines.extend(["", f"Sumber/Catatan: {data['source']}"])
    lines.extend(["", "#shorts #edukasi #tips #produktivitas"])
    return "\n".join(lines)[:5000]


def upload_yt(video_mp4: str, title: str, desc: str, privacy: str) -> str:
    creds = Credentials(
        token=None,
        refresh_token=os.environ["YT_REFRESH_TOKEN"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["YT_CLIENT_ID"],
        client_secret=os.environ["YT_CLIENT_SECRET"],
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    yt = build("youtube", "v3", credentials=creds)

    short_title = title if "#shorts" in title.lower() else f"{title} #Shorts"
    body = {
        "snippet": {
            "title": short_title[:100],
            "description": desc,
            "tags": ["shorts", "edukasi", "tips", "indonesia"],
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(video_mp4, chunksize=-1, resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    return resp.get("id", "")


def main():
    data = parse_topik_txt(TOPIK_FILE)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(OUT_DIR, stamp)
    os.makedirs(run_dir, exist_ok=True)

    clips = []
    total = len(data["slides"])
    for idx, s in enumerate(data["slides"]):
        mp3 = os.path.join(run_dir, f"s_{idx+1}.mp3")
        png = os.path.join(run_dir, f"s_{idx+1}.png")
        mp4 = os.path.join(run_dir, f"c_{idx+1}.mp4")
        make_voice(s["narration"], mp3)
        make_slide_img(idx, total, data["title"], s["headline"], s["body"], png)
        make_clip(png, mp3, mp4)
        clips.append(mp4)

    final_mp4 = os.path.join(run_dir, "shorts_final.mp4")
    merge_clips(clips, final_mp4)

    desc = build_desc(data)
    privacy = os.getenv("YT_PRIVACY", "private")
    vid_id = upload_yt(final_mp4, data["title"], desc, privacy)

    with open(os.path.join(run_dir, "info.json"), "w", encoding="utf-8") as f:
        json.dump({"title": data["title"], "youtube_id": vid_id, "privacy": privacy}, f, indent=2)

    print(f"SUKSES! YouTube Video ID: {vid_id} | Status: {privacy}")


if __name__ == "__main__":
    main()
