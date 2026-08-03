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


def normalize_image_contain(image_bytes: bytes, dst_path: Path, width: int, height: int, background: str) -> dict:
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
        return {
            'fit_w': fit_w,
            'fit_h': fit_h,
            'off_x_px': off_x,
            'off_y_px': off_y,
            'tiling_x': float(fit_w) / float(width),
            'tiling_y': float(fit_h) / float(height),
            'offset_x': float(off_x) / float(width),
            'offset_y': float(height - fit_h - off_y) / float(height),
        }


def page_input_framerate(seconds_per_page: float) -> str:
    if seconds_per_page <= 0.001:
        seconds_per_page = 1.0
    rounded = round(seconds_per_page)
    if abs(seconds_per_page - float(rounded)) < 0.000001 and rounded >= 1:
        return f'1/{rounded}'
    return f'{1.0 / seconds_per_page:.8f}'


def ffmpeg_build_video(frames_dir: Path, output_path: Path, fps: int, crf: int, gop: int, codec: str, seconds_per_page: float) -> None:
    if seconds_per_page <= 0.001:
        seconds_per_page = 1.0
    if fps < 1:
        fps = 30
    if gop < 1:
        gop = max(1, int(round(float(fps) * seconds_per_page)))

    cmd = [
        'ffmpeg',
        '-y',
        '-framerate',
        page_input_framerate(seconds_per_page),
        '-start_number',
        '1',
        '-i',
        str(frames_dir / 'frame_%06d.png'),
        '-r',
        str(fps),
        '-c:v',
        codec,
        '-pix_fmt',
        'yuv420p',
        '-crf',
        str(crf),
        '-g',
        str(gop),
        '-force_key_frames',
        f'expr:gte(t,n_forced*{seconds_per_page:.6f})',
        '-tune',
        'stillimage',
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
        'notices': ['notice', 'notices'],
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
        'conditionalcast': ['conditionalcast', 'condisionalcast', 'conditional_cast', 'condisional_cast'],
        'guest': ['guest'],
    }
    return aliases.get(key, [key])


def candidate_image_urls(raw_base: str, kind: str, item: dict) -> list[str]:
    out: list[str] = []
    slot = item.get('slot')
    category = str(item.get('category', '')).strip()
    if slot is None or category == '':
        return out
    slot_name = f'slot{slot}'
    exts = ['png', 'jpg', 'jpeg', 'webp']
    if kind == 'poster':
        for folder in poster_dir_candidates(category):
            for ext in exts:
                out.append(f'{raw_base}images/posters/{folder}/{slot_name}.{ext}')
                out.append(f'{raw_base}images/poster/{folder}/{slot_name}.{ext}')
    else:
        for folder in portrait_dir_candidates(category):
            for ext in exts:
                out.append(f'{raw_base}images/portraits/{folder}/{slot_name}.{ext}')
                out.append(f'{raw_base}images/portrait/{folder}/{slot_name}.{ext}')
                out.append(f'{raw_base}images/members/{folder}/{slot_name}.{ext}')
                out.append(f'{raw_base}images/member/{folder}/{slot_name}.{ext}')
                out.append(f'{raw_base}images/roster/{folder}/{slot_name}.{ext}')
    return unique_preserve(out)


def manifest_entries(manifest: dict, include_portraits: bool, include_posters: bool, include_hidden_portraits: bool) -> list[dict]:
    entries: list[dict] = []
    if include_portraits:
        members = manifest.get('members', [])
        if isinstance(members, list):
            for item in members:
                if not isinstance(item, dict):
                    continue
                if not item.get('enabled', False):
                    continue
                show_portrait = bool(item.get('showPortrait', True))
                if (not include_hidden_portraits) and (not show_portrait):
                    continue
                entry = dict(item)
                entry['_kind'] = 'member'
                entry['_showPortrait'] = show_portrait
                entries.append(entry)
    if include_posters:
        posters = manifest.get('posters', [])
        if isinstance(posters, list):
            for item in posters:
                if not isinstance(item, dict):
                    continue
                if not item.get('enabled', False):
                    continue
                entry = dict(item)
                entry['_kind'] = 'poster'
                entries.append(entry)
    return entries


def resolve_frame_entries_from_manifest(raw_base: str, manifest: dict, include_portraits: bool, include_posters: bool, include_hidden_portraits: bool) -> tuple[list[dict], list[str]]:
    entries = manifest_entries(manifest, include_portraits, include_posters, include_hidden_portraits)
    resolved: list[dict] = []
    missing: list[str] = []
    for item in entries:
        kind = str(item.get('_kind', 'member'))
        candidates = candidate_image_urls(raw_base, kind, item)
        found = None
        for candidate in candidates:
            if url_exists(candidate):
                found = candidate
                break
        label = f"{kind}|{item.get('category', '?')}|{item.get('slot', '?')}"
        if found is None:
            missing.append(label)
        else:
            resolved.append({
                'kind': kind,
                'category': str(item.get('category', '')),
                'slot': int(item.get('slot', 0)),
                'url': found,
            })
    return resolved, missing


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build a one-second-per-page roster video from GitHub images and emit a matching frame map.')
    parser.add_argument('--repo-url', required=True)
    parser.add_argument('--manifest-url', default='')
    parser.add_argument('--output', required=True)
    parser.add_argument('--branch', default='main')
    parser.add_argument('--include-posters', action='store_true')
    parser.add_argument('--include-portraits', action='store_true')
    parser.add_argument('--fps', type=int, default=30)
    parser.add_argument('--seconds-per-page', type=float, default=1.0)
    parser.add_argument('--crf', type=int, default=16)
    parser.add_argument('--gop', type=int, default=0)
    parser.add_argument('--codec', default='libx264')
    parser.add_argument('--width', type=int, default=1920)
    parser.add_argument('--height', type=int, default=1080)
    parser.add_argument('--background', default='black')
    parser.add_argument('--save-url-list', default='')
    parser.add_argument('--frame-map-output', default='')
    parser.add_argument('--include-hidden-portraits', action='store_true', default=True)
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
    print(f'Mode: one-second-page / contain + pad / fps={args.fps} / seconds_per_page={args.seconds_per_page}')

    try:
        manifest = json.loads(download_bytes(raw_manifest_url).decode('utf-8'))
    except Exception as exc:
        print(f'Failed to read manifest: {exc}', file=sys.stderr)
        return 1

    resolved_entries, missing = resolve_frame_entries_from_manifest(raw_base, manifest, args.include_portraits, args.include_posters, args.include_hidden_portraits)
    if not resolved_entries:
        print('No image URLs resolved from manifest.', file=sys.stderr)
        if missing:
            print('Missing entries:', file=sys.stderr)
            for item in missing:
                print(f'  - {item}', file=sys.stderr)
        return 2

    print(f'Resolved pages: {len(resolved_entries)}')
    print(f'Expected duration: {len(resolved_entries) * args.seconds_per_page:.3f}s')
    if missing:
        print(f'Unresolved entries: {len(missing)}')
        for item in missing[:20]:
            print(f'MISS: {item}')

    urls = [entry['url'] for entry in resolved_entries]

    if args.save_url_list:
        Path(args.save_url_list).parent.mkdir(parents=True, exist_ok=True)
        Path(args.save_url_list).write_text('\n'.join(urls) + '\n', encoding='utf-8')

    workdir_obj = tempfile.TemporaryDirectory(prefix='github_manifest_to_video_page_')
    workdir = Path(workdir_obj.name)
    frames_dir = workdir / 'frames'
    frames_dir.mkdir(parents=True, exist_ok=True)
    print(f'Workdir: {workdir}')

    idx = 0
    while idx < len(urls):
        url = urls[idx]
        frame_path = frames_dir / f'frame_{idx + 1:06d}.png'
        try:
            image_bytes = download_bytes(url)
            uv_info = normalize_image_contain(image_bytes, frame_path, args.width, args.height, args.background)
            resolved_entries[idx].update(uv_info)
            resolved_entries[idx]['page'] = idx
            resolved_entries[idx]['sample_time'] = float(idx) * args.seconds_per_page + (args.seconds_per_page * 0.5)
        except Exception as exc:
            print(f'Failed on {url}\n{exc}', file=sys.stderr)
            return 3
        idx += 1

    if args.frame_map_output:
        lines: list[str] = []
        for entry in resolved_entries:
            lines.append(
                f"{entry['kind']}|{entry['category']}|{entry['slot']}|{entry['url']}|{entry.get('tiling_x', 1.0):.8f}|{entry.get('tiling_y', 1.0):.8f}|{entry.get('offset_x', 0.0):.8f}|{entry.get('offset_y', 0.0):.8f}|page={entry.get('page', 0)}|sample={entry.get('sample_time', 0.5):.3f}"
            )
        Path(args.frame_map_output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.frame_map_output).write_text('\n'.join(lines) + '\n', encoding='utf-8')

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        ffmpeg_build_video(frames_dir, output_path, args.fps, args.crf, args.gop, args.codec, args.seconds_per_page)
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
