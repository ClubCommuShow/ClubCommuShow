#!/usr/bin/env python3
"""Build one exact 3-frame-per-image MP4 per immediate album directory.

Only docs/ebk-room-media is generated. Roster, source images and other docs
are never edited. Failed builds leave the previous output intact.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
import tempfile
import unicodedata
import warnings
from pathlib import Path
from urllib.parse import quote, urlsplit

from PIL import Image, ImageOps

FPS = 30
FRAMES = 3
EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
MARKER = ".ebk-room-media-generated"
MAX_IMAGE_BYTES = 50 * 1024 * 1024
MAX_ALBUM_IMAGES = 2000
MAX_VIDEO_BYTES = 95 * 1024 * 1024
MAX_SITE_BYTES = 900 * 1024 * 1024
Image.MAX_IMAGE_PIXELS = 40_000_000
warnings.simplefilter("error", Image.DecompressionBombWarning)


def natural_key(path: Path):
    name = unicodedata.normalize("NFC", path.name)
    return ([(1, int(s)) if s.isdigit() else (0, s.casefold())
             for s in re.split(r"([0-9]+)", name)], name, path.name)


def safe_name(name: str):
    # Japanese and spaces are supported; reject names that cannot be distributed
    # consistently on Windows or that are hidden/reserved filesystem entries.
    if (not name or name.startswith(".") or name.endswith((" ", "."))
            or len(name.encode("utf-8")) > 180
            or any(ord(c) < 32 or ord(c) == 127 or c in '<>:"/\\|?*' for c in name)):
        raise ValueError("使用できないアルバム名: " + repr(name))
    if name.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL",
                                             *[f"COM{i}" for i in range(1, 10)],
                                             *[f"LPT{i}" for i in range(1, 10)]}:
        raise ValueError("予約されたアルバム名: " + name)


def checked_tree(root: Path):
    if root.is_symlink():
        raise ValueError("シンボリックリンクは使用できません: " + str(root))
    if root.exists():
        for path in root.rglob("*"):
            if path.is_symlink():
                raise ValueError("シンボリックリンクは使用できません: " + str(path))


def discover(source: Path):
    checked_tree(source)
    if not source.is_dir():
        raise ValueError("画像投入フォルダがありません: " + str(source))
    albums = []
    names = set()
    for directory in sorted(source.iterdir(), key=natural_key):
        if directory.name.startswith("."):
            continue
        if not directory.is_dir():
            if directory.suffix.lower() in EXTENSIONS:
                raise ValueError("画像はアルバムのフォルダ内に入れてください: " + str(directory))
            continue
        safe_name(directory.name)
        key = unicodedata.normalize("NFC", directory.name).casefold()
        if key in names:
            raise ValueError("大文字小文字・Unicode表記で衝突するアルバム名: " + directory.name)
        names.add(key)
        images = []
        image_names = set()
        for path in sorted(directory.iterdir(), key=natural_key):
            if path.name.startswith("."):
                continue
            if path.is_dir():
                raise ValueError("アルバム内のサブフォルダには対応していません: " + str(path))
            if path.suffix.lower() not in EXTENSIONS:
                if path.name.lower().startswith("readme"):
                    continue
                raise ValueError("未対応の画像形式: " + str(path))
            if path.stat().st_size > MAX_IMAGE_BYTES:
                raise ValueError("画像が50MiBを超えています: " + str(path))
            image_key = unicodedata.normalize("NFC", path.name).casefold()
            if image_key in image_names:
                raise ValueError("大文字小文字・Unicode表記で衝突する画像名: " + str(path))
            image_names.add(image_key)
            images.append(path)
        if len(images) > MAX_ALBUM_IMAGES:
            raise ValueError("1アルバム2000枚までです: " + directory.name)
        albums.append((directory.name, images))
    return albums


def frame_bytes(path: Path, width: int, height: int):
    with Image.open(path) as source:
        if getattr(source, "n_frames", 1) != 1:
            raise ValueError("静止画像を使用してください（アニメーション/複数ページ）: " + str(path))
        image = ImageOps.exif_transpose(source).convert("RGBA")
        scale = min(width / image.width, height / image.height)
        image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                             Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (width, height), (0, 0, 0))
        canvas.paste(image, ((width - image.width) // 2, (height - image.height) // 2), image)
        return canvas.tobytes()


def encode(images: list[Path], output: Path, width: int, height: int):
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
               "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", f"{width}x{height}",
               "-framerate", str(FPS), "-i", "pipe:0", "-an", "-c:v", "libx264",
               "-pix_fmt", "yuv420p", "-r", str(FPS), "-frames:v", str(len(images) * FRAMES),
               "-crf", "18", "-preset", "medium", "-g", "1", "-bf", "0",
               "-sc_threshold", "0", "-tune", "stillimage", "-movflags", "+faststart", str(output)]
    with tempfile.TemporaryFile() as error_log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=error_log)
        try:
            for path in images:
                pixels = frame_bytes(path, width, height)
                for _ in range(FRAMES):
                    process.stdin.write(pixels)
            process.stdin.close()
            if process.wait() != 0:
                error_log.seek(0)
                raise RuntimeError(error_log.read().decode("utf-8", errors="replace"))
        except BaseException:
            process.kill()
            process.wait()
            if not process.stdin.closed:
                process.stdin.close()
            raise
    probe = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                            "-show_entries", "stream=codec_name,pix_fmt,r_frame_rate,nb_read_frames,width,height",
                            "-of", "json", str(output)], check=True, capture_output=True, text=True)
    stream = json.loads(probe.stdout)["streams"][0]
    if (stream["codec_name"] != "h264" or stream["pix_fmt"] != "yuv420p"
            or stream["r_frame_rate"] != "30/1" or int(stream["nb_read_frames"]) != len(images) * FRAMES
            or stream["width"] != width or stream["height"] != height):
        raise RuntimeError("生成動画のフレーム検査に失敗しました: " + str(output))
    if output.stat().st_size > MAX_VIDEO_BYTES:
        raise ValueError("動画が95MiBを超えました。画像を別アルバムへ分けてください: " + output.name)


def write_index(output: Path, albums: list[dict]):
    rows = []
    for album in albums:
        name = html.escape(album["name"])
        if not album["imageCount"]:
            rows.append(f"<tr><th>{name}</th><td>0</td><td>画像待ち</td></tr>")
            continue
        url = html.escape(album["slideUrl"], quote=True)
        raw = html.escape(album["videoUrl"], quote=True)
        rows.append(f'<tr><th>{name}</th><td>{album["imageCount"]}</td><td>'
                    f'<input aria-label="{name}のスライドURL" readonly value="{url}">'
                    f'<button type="button" data-url="{url}">リンクをコピー</button> '
                    f'<a href="{raw}" download>MP4</a></td></tr>')
    document = '''<!doctype html><html lang="ja"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>EBK スライドアルバム</title><style>
body{font:16px system-ui,sans-serif;max-width:1080px;margin:40px auto;padding:0 20px;background:#f6f7fa;color:#182334}
table{width:100%;border-collapse:collapse;background:white}th,td{padding:16px;text-align:left;border-bottom:1px solid #ddd}
input{box-sizing:border-box;width:100%;padding:10px;margin-bottom:8px}button{padding:8px 14px;cursor:pointer}
</style><h1>EBK スライドアルバム</h1>
<p>リンクをコピーして、部屋別メディアボードのURL欄へ貼り付けて読み込みます。<br>
対応版EBKはスライド方式（1枚3フレーム・30fps）へ自動で切り替わります。</p>
<table><thead><tr><th>アルバム</th><th>枚数</th><th>メディアボード用リンク</th></tr></thead><tbody>
''' + "\n".join(rows) + '''</tbody></table><p id="message" role="status"></p>
<p>画像の更新後は動画生成と公開の完了を待ち、同じURLを読み込み直してください。</p>
<script>
document.querySelectorAll('button[data-url]').forEach(button => {
 button.addEventListener('click', async () => {
  const message = document.getElementById('message');
  try { await navigator.clipboard.writeText(button.dataset.url); message.textContent = 'リンクをコピーしました。'; }
  catch (_) { const input=button.parentElement.querySelector('input'); input.focus(); input.select();
   message.textContent = 'URLを選択しました。コピー操作をしてください。'; }
 });
});
</script></html>'''
    (output / "index.html").write_text(document, encoding="utf-8")


def build(root: Path, config_path: Path):
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if config.get("schemaVersion") != 1:
        raise ValueError("room_media_slides.jsonのschemaVersionは1を指定してください")
    width, height = config.get("width", 1920), config.get("height", 1080)
    for value in (width, height):
        if type(value) is not int or value < 64 or value > 3840 or value % 2:
            raise ValueError("解像度は64〜3840の偶数を指定してください")
    base = str(config.get("pagesBaseUrl", "")).rstrip("/")
    parsed = urlsplit(base)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.query or parsed.fragment
            or parsed.username or parsed.password or any(c.isspace() for c in base)
            or "YOUR_" in base):
        raise ValueError("pagesBaseUrlに購入者自身の公開HTTPS URLを設定してください")
    source = root / "media/room-slides"
    docs = root / "docs"
    target = docs / "ebk-room-media"
    if (root / "media").is_symlink():
        raise ValueError("mediaはシンボリックリンクにできません")
    checked_tree(docs)
    albums = discover(source)
    if target.exists() and not (target / MARKER).is_file():
        raise ValueError("既存のdocs/ebk-room-mediaを上書きしません。別用途の内容を確認してください")
    docs.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ebk-slides-") as temporary:
        output = Path(temporary) / "output"
        videos = output / "videos"
        videos.mkdir(parents=True)
        result = []
        for name, images in albums:
            entry = {"name": name, "imageCount": len(images), "fps": FPS,
                     "framesPerImage": FRAMES, "sampleFrame": 1, "videoUrl": "", "slideUrl": "",
                     "images": []}
            if images:
                video = videos / (name + ".mp4")
                encode(images, video, width, height)
                url = base + "/ebk-room-media/videos/" + quote(name + ".mp4", safe="")
                entry.update(videoUrl=url, slideUrl=url + "?ebk-slides=3x30",
                             frameCount=len(images) * FRAMES,
                             sha256=hashlib.sha256(video.read_bytes()).hexdigest())
                entry["images"] = [{"file": p.name, "sourceBlobSha": git_blob_sha(p), "sampleFrame": i * FRAMES + 1,
                                    "sampleTimeSeconds": (i * FRAMES + 1) / FPS}
                                   for i, p in enumerate(images)]
            result.append(entry)
        (output / "manifest.json").write_text(json.dumps({"schemaVersion": 1, "albums": result},
                                                        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output / "links.tsv").write_text("album\timages\tslideUrl\n" + "".join(
            f'{a["name"]}\t{a["imageCount"]}\t{a["slideUrl"]}\n' for a in result), encoding="utf-8")
        write_index(output, result)
        (output / MARKER).write_text("EBK RoomMedia generated output v1\n", encoding="utf-8")
        site_bytes = sum(p.stat().st_size for p in docs.rglob("*")
                         if p.is_file() and not p.is_relative_to(target))
        site_bytes += sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
        if site_bytes > MAX_SITE_BYTES:
            raise ValueError("公開データが900MiBを超えます。アルバムを分割・縮小してください")
        # Encode and verify every album before replacing this owned directory.
        stage = Path(tempfile.mkdtemp(prefix=".ebk-room-media-stage-", dir=docs.parent))
        backup = stage / "previous"
        try:
            shutil.copytree(output, stage / "ready")
            if target.exists():
                target.rename(backup)
            try:
                (stage / "ready").rename(target)
            except BaseException:
                if backup.exists():
                    backup.rename(target)
                raise
        finally:
            shutil.rmtree(stage)
    print(f"Built {sum(bool(images) for _, images in albums)} albums / {sum(len(images) for _, images in albums)} images")
    print(base + "/ebk-room-media/")
    return result


def git_blob_sha(path: Path):
    data = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="data/room_media_slides.json")
    args = parser.parse_args()
    build(Path.cwd(), Path(args.config))


if __name__ == "__main__":
    main()
