#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from io import BytesIO
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageOps


def run(cmd: list[str]) -> None:
    print('RUN:', ' '.join(cmd))
    subprocess.run(cmd, check=True)


def download_bytes(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': '*/*',
        },
    )
    with urllib.request.urlopen(req) as resp:
        return resp.read()


def url_exists(url: str) -> bool:
    req = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0',
            'Accept': '*/*',
        },
        method='HEAD',
    )
    try:
        with urllib.request.urlopen(req) as resp:
            code = getattr(resp, 'status', 200)
            return 200 <= code < 400
    except Exception:
        try:
            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': 'Mozilla/5.0',
                    'Accept': '*/*',
                },
            )
            with urllib.request.urlopen(req) as resp:
                code = getattr(resp, 'status', 200)
                return 200 <= code < 400
        except Exception:
            return False


def normalize_slug(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    out = []
    for ch in text:
        if ch.isalnum():
            out.append(ch.lower())
        else:
            out.append('_')
    slug = ''.join(out)
    while '__' in slug:
        slug = slug.replace('__', '_')
    return slug.strip('_')


def parse_repo(repo_or_manifest_url: str, default_branch: str) -> tuple[str, str, str]:
    parsed = urllib.parse.urlparse(repo_or_manifest_url)
    parts = [p for p in parsed.path.split('/') if p]
    if parsed.netloc not in {'github.com', 'raw.githubusercontent.com'}:
        raise ValueError(f'Unsupported host: {parsed.netloc}')
    if parsed.netloc == 'raw.githubusercontent.com':
        if len(parts) < 4:
            raise ValueError('raw.githubusercontent.com URL is too short')
        return parts[0], parts[1], parts[2]
    if len(parts) < 2:
        raise ValueError('GitHub repo URL is too short')
    owner = parts[0]
    repo = parts[1]
    branch = default_branch
    if len(parts) >= 4 and parts[2] in {'blob', 'tree'}:
        branch = parts[3]
    return owner, repo, branch


def to_raw_manifest_url(manifest_url: str, default_branch: str) -> str:
    parsed = urllib.parse.urlparse(manifest_url)
    parts = [p for p in parsed.path.split('/') if p]
    if parsed.netloc == 'raw.githubusercontent.com':
        return manifest_url
    if parsed.netloc != 'github.com':
        return manifest_url
    if len(parts) >= 5 and parts[2] == 'blob':
        owner = parts[0]
        repo = parts[1]
        branch = parts[3]
        rel = '/'.join(parts[4:])
        return f'https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{rel}'
    owner, repo, branch = parse_repo(manifest_url, default_branch)
    return f'https://raw.githubusercontent.com/{owner}/{repo}/{branch}/data/roster_manifest.json'


def parse_background(value: str) -> tuple[int, int, int, int]:
    value = value.strip().lower()
    if value == 'black':
        return (0, 0, 0, 255)
    if value == 'white':
        return (255, 255, 255, 255)
    if value in {'transparent', 'none'}:
        return (0, 0, 0, 0)
    if value.startswith('#'):
        value = value[1:]
        if len(value) == 6:
            return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255)
        if len(value) == 8:
            return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), int(value[6:8], 16))
    raise ValueError(f'Unsupported background value: {value}')


def normalize_image_contain(image_bytes: bytes, dst_path: Path, width: int, height: int, background: str) -> None:
    bg = parse_background(background)
    with Image.open(BytesIO(image_bytes)) as img:
        img = ImageOps.exif_transpose(img)
        img = img.convert('RGBA')
        src_w, src_h = img.size
        if src_w <= 0 or src_h <= 0:
            raise ValueError('Invalid source image size')

        scale = min(float(width) / float(src_w), float(height) / float(src_h))
        fit_w = max(1, int(round(src_w * scale)))
        fit_h = max(1, int(round(src_h * scale)))
        resized = img.resize((fit_w, fit_h), Image.Resampling.LANCZOS)

        canvas = Image.new('RGBA', (width, height), bg)
        off_x = (width - fit_w) // 2
        off_y = (height - fit_h) // 2
        canvas.paste(resized, (off_x, off_y), resized)
        canvas.save(dst_path, format='PNG')


def ffmpeg_build_video(frames_dir: Path, output_path: Path, fps: int, crf: int, gop: int, codec: str) -> None:
    cmd = [
        'ffmpeg',
        '-y',
        '-framerate',
        str(fps),
        '-i',
        str(frames_dir / 'frame_%06d.png'),
        '-c:v',
        codec,
        '-pix_fmt',
        'yuv420p',
        '-crf',
        str(crf),
        '-g',
        str(gop),
        '-an',
        '-movflags',
        '+faststart',
        str(output_path),
    ]
    run(cmd)


def unique_preserve(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def poster_dir_candidates(category: str) -> list[str]:
    key = normalize_slug(category)
    mapping = {
        'eventposter': ['event', 'eventposter', 'event_poster'],
        'frontposter': ['front', 'frontposter', 'front_poster'],
        'sideposter': ['side', 'sideposter', 'side_poster'],
        'backposter': ['back', 'backposter', 'back_poster'],
        'notice': ['notice'],
        'menu': ['menu', 'kanpe'],
        'kanpe': ['kanpe', 'menu'],
    }
    return mapping.get(key, [key])


def portrait_dir_candidates(category: str) -> list[str]:
    key = normalize_slug(category)
    aliases = {
        'owner': ['owner'],
        'manager': ['manager'],
        'operator': ['operator'],
        'assistant': ['assistant'],
        'staffleader': ['staffleader', 'staff_leader'],
        'staff': ['staff'],
        'castleader': ['castleader', 'cast_leader'],
        'uppercast': ['uppercast', 'upper_cast'],
        'downercast': ['downercast', 'downer_cast'],
        'condisionalcast': ['condisionalcast', 'conditionalcast', 'conditional_cast', 'condisional_cast'],
    }
    return aliases.get(key, [key])


def candidate_image_urls(raw_base: str, item: dict, include_portraits: bool, include_posters: bool) -> list[str]:
    out: list[str] = []
    slot = item.get('slot')
    category = str(item.get('category', '')).strip()
    if slot is None or category == '':
        return out
    slot_name = f'slot{slot}'
    exts = ['png', 'jpg', 'jpeg', 'webp']

    if include_posters:
        for folder in poster_dir_candidates(category):
            for ext in exts:
                out.append(f'{raw_base}images/posters/{folder}/{slot_name}.{ext}')
                out.append(f'{raw_base}images/poster/{folder}/{slot_name}.{ext}')

    if include_portraits:
        for folder in portrait_dir_candidates(category):
            for ext in exts:
                out.append(f'{raw_base}images/portraits/{folder}/{slot_name}.{ext}')
                out.append(f'{raw_base}images/portrait/{folder}/{slot_name}.{ext}')
                out.append(f'{raw_base}images/members/{folder}/{slot_name}.{ext}')
                out.append(f'{raw_base}images/member/{folder}/{slot_name}.{ext}')
                out.append(f'{raw_base}images/roster/{folder}/{slot_name}.{ext}')
    return unique_preserve(out)


def manifest_entries(manifest: dict, include_portraits: bool, include_posters: bool) -> list[dict]:
    entries: list[dict] = []
    if include_portraits:
        members = manifest.get('members', [])
        if isinstance(members, list):
            for item in members:
                if not isinstance(item, dict):
                    continue
                if not item.get('enabled', False):
                    continue
                if not item.get('showPortrait', True):
                    continue
                entries.append(item)
    if include_posters:
        posters = manifest.get('posters', [])
        if isinstance(posters, list):
            for item in posters:
                if not isinstance(item, dict):
                    continue
                if not item.get('enabled', False):
                    continue
                entries.append(item)
    return entries


def resolve_urls_from_manifest(raw_base: str, manifest: dict, include_portraits: bool, include_posters: bool) -> tuple[list[str], list[str]]:
    entries = manifest_entries(manifest, include_portraits, include_posters)
    resolved: list[str] = []
    missing: list[str] = []
    members = manifest.get('members', [])
    posters = manifest.get('posters', [])
    for item in entries:
        candidates = candidate_image_urls(
            raw_base,
            item,
            include_portraits=True if item in members else False,
            include_posters=True if item in posters else False,
        )
        found = None
        for candidate in candidates:
            if url_exists(candidate):
                found = candidate
                break
        label = f"{item.get('category', '?')} slot={item.get('slot', '?')}"
        if found is None:
            missing.append(label)
        else:
            resolved.append(found)
    return unique_preserve(resolved), missing


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build a no-crop video from a GitHub repo + roster_manifest.json.')
    parser.add_argument('--repo-url', required=True)
    parser.add_argument('--manifest-url', default='')
    parser.add_argument('--output', required=True)
    parser.add_argument('--branch', default='main')
    parser.add_argument('--include-posters', action='store_true')
    parser.add_argument('--include-portraits', action='store_true')
    parser.add_argument('--fps', type=int, default=30)
    parser.add_argument('--crf', type=int, default=10)
    parser.add_argument('--gop', type=int, default=1)
    parser.add_argument('--codec', default='libx264')
    parser.add_argument('--width', type=int, default=1920)
    parser.add_argument('--height', type=int, default=1080)
    parser.add_argument('--background', default='black')
    parser.add_argument('--save-url-list', default='')
    parser.add_argument('--keep-workdir', action='store_true')
    args = parser.parse_args()
    if not args.include_posters and not args.include_portraits:
        args.include_posters = True
        args.include_portraits = True
    return args


def main() -> int:
    args = parse_args()
    owner, repo, branch = parse_repo(args.repo_url, args.branch)
    raw_base = f'https://raw.githubusercontent.com/{owner}/{repo}/{branch}/'
    manifest_source = args.manifest_url.strip() or f'https://github.com/{owner}/{repo}/blob/{branch}/data/roster_manifest.json'
    raw_manifest_url = to_raw_manifest_url(manifest_source, args.branch)

    print(f'Repo: {owner}/{repo}')
    print(f'Branch: {branch}')
    print(f'Manifest: {raw_manifest_url}')
    print(f'Canvas: {args.width}x{args.height}')
    print('Mode: PIL contain + pad (no crop)')

    try:
        manifest = json.loads(download_bytes(raw_manifest_url).decode('utf-8'))
    except Exception as exc:
        print(f'Failed to read manifest: {exc}', file=sys.stderr)
        return 1

    urls, missing = resolve_urls_from_manifest(raw_base, manifest, args.include_portraits, args.include_posters)
    if not urls:
        print('No image URLs resolved from manifest.', file=sys.stderr)
        if missing:
            print('Missing entries:', file=sys.stderr)
            for item in missing:
                print(f'  - {item}', file=sys.stderr)
        return 2

    print(f'Resolved images: {len(urls)}')
    if missing:
        print(f'Unresolved entries: {len(missing)}')
        for item in missing[:20]:
            print(f'MISS: {item}')

    if args.save_url_list:
        Path(args.save_url_list).write_text('\n'.join(urls) + '\n', encoding='utf-8')

    workdir_obj = tempfile.TemporaryDirectory(prefix='github_manifest_to_video_nocrop_pillow_')
    workdir = Path(workdir_obj.name)
    frames_dir = workdir / 'frames'
    frames_dir.mkdir(parents=True, exist_ok=True)
    print(f'Workdir: {workdir}')

    for idx, url in enumerate(urls):
        frame_path = frames_dir / f'frame_{idx + 1:06d}.png'
        try:
            image_bytes = download_bytes(url)
            normalize_image_contain(image_bytes, frame_path, args.width, args.height, args.background)
        except Exception as exc:
            print(f'Failed on {url}\n{exc}', file=sys.stderr)
            return 3

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        ffmpeg_build_video(frames_dir, output_path, args.fps, args.crf, args.gop, args.codec)
    except Exception as exc:
        print(f'Failed to build video\n{exc}', file=sys.stderr)
        return 4

    print(f'Built: {output_path}')
    if args.keep_workdir:
        keep_file = output_path.with_suffix('.workdir.txt')
        keep_file.write_text(str(workdir), encoding='utf-8')
        workdir_obj.cleanup = lambda: None  # type: ignore[attr-defined]
        print(f'Kept workdir: {workdir}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
