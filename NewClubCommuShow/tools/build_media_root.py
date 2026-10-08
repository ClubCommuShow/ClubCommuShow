#!/usr/bin/env python3
"""Build an isolated EBK media root. No writes outside the selected folder.

Inputs are copied to a temporary build directory. Only validated generated
outputs are published; the caller commits them together. Legacy inputs, scripts
and videos at the repository root are not read or changed.
"""
from pathlib import Path
from urllib.parse import urlsplit, unquote, quote
import argparse
import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile

from PIL import Image, ImageOps
import build_room_media_slides as slides
import build_clubcard_video as cards
import build_theme_catalog as themes


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def source_image(root, row, kind, base):
    # Preserve explicit portrait mappings (semantic slot need not equal filename).
    address = row.get('portraitUrl' if kind == 'member' else 'imageUrl', '')
    if address:
        if not address.startswith(base + '/'):
            raise ValueError('画像URLは新しい共通ルート内で指定してください: ' + address)
        relative = unquote(urlsplit(address).path[len(urlsplit(base).path) + 1:])
        candidate = root / relative
        if not candidate.resolve().is_relative_to(root.resolve()):
            raise ValueError('Image path escapes media root')
        return candidate if candidate.is_file() else None
    from github_manifest_to_video import find_image
    return find_image(root / 'images', kind, str(row['category']), int(row['slot']))


def build_common(root, output, base):
    manifest = read_json(root / 'data/roster_manifest.json')
    from prepare_video_roster_manifest import discover, POSTER_FOLDERS
    posters = list(manifest.get('posters', []))
    known = {(r.get('category'), r.get('slot')) for r in posters if isinstance(r, dict)}
    for folder, category in POSTER_FOLDERS:
        for slot in discover(root / 'images/posters' / folder):
            if (category, slot) not in known:
                posters.append({'category': category, 'slot': slot, 'enabled': True})
    manifest['posters'] = posters
    records = []
    skipped = []
    keys = set()
    for field, kind in [('members', 'member'), ('posters', 'poster')]:
        for row in manifest.get(field, []):
            if not isinstance(row, dict) or not row.get('enabled', True):
                continue
            if kind == 'member' and not row.get('showPortrait', True):
                continue
            category, slot = row.get('category'), row.get('slot')
            if not isinstance(category, str) or not category or '|' in category or type(slot) is not int or slot < 0:
                raise ValueError('Invalid semantic image key')
            key = f'{kind}|{category}|{slot}'
            if key in keys:
                raise ValueError('Duplicate key: ' + key)
            keys.add(key)
            path = source_image(root, row, kind, base)
            if path is None:
                skipped.append(key)
                continue  # Missing keys use the Wizard's local image.
            records.append((key, path))
    if len(records) > 128:
        raise ValueError('共通画像は128枠までです')
    output.mkdir(parents=True, exist_ok=True)
    if not records:
        return None, skipped
    with tempfile.TemporaryDirectory(prefix='ebk-common-') as tmp:
        frames = []
        lines = []
        hashes = []
        for i, (key, path) in enumerate(records):
            with Image.open(path) as image:
                image = ImageOps.exif_transpose(image)
                width, height = image.size
                frame = Path(tmp) / f'{i:04}.png'
                image.convert('RGB').resize((1280, 720), Image.Resampling.LANCZOS).save(frame)
            frames.append(frame)
            address = base + '/' + quote(path.relative_to(root).as_posix(), safe='/')
            lines.append(f'{i*3+1}|{key}|{address}|aspect={width/height:.8f}|sample={(i*3+1)/30:.8f}|bad=0')
            hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
        slides.encode(frames, output / 'roster.mp4', 1280, 720)
    result = copy.deepcopy(manifest)
    result['videoRoster'] = {'enabled': True, 'fps': 30, 'framesPerEntry': 3, 'sampleFrame': 1,
                            'videoUrl': base + '/common/roster.mp4',
                            'frameMapUrl': base + '/common/frame_map.txt'}
    write_json(output / 'manifest.json', result)
    (output / 'frame_map.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    write_json(output / 'build_report.json', {'captured': len(records), 'fallbackKeys': skipped, 'sourceHashes': hashes})
    return {'id': 'common', 'manifestPath': 'common/manifest.json', 'format': 'ebk-roster-v1'}, skipped


def build(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Media root must be an existing regular directory')
    root = root.resolve()
    slides.checked_tree(root)
    config = read_json(root / 'data/room_media_slides.json')
    base = config['pagesBaseUrl'].rstrip('/')
    url = urlsplit(base)
    if url.scheme != 'https' or not url.hostname or url.username or url.query or url.fragment:
        raise ValueError('公開済みのHTTPSルートURLが必要です')
    # Stage all groups before updating even one published group.
    with tempfile.TemporaryDirectory(prefix='ebk-media-root-') as tmp:
        stage = Path(tmp)
        for directory in ['data', 'images', 'media', 'themes']:
            if (root / directory).is_dir():
                shutil.copytree(root / directory, stage / directory)
        (stage / 'themes').mkdir(exist_ok=True)
        (stage / 'media/room-slides').mkdir(parents=True, exist_ok=True)
        generated = stage / 'generated'
        generated.mkdir()
        modules = []
        if (stage / 'data/roster_manifest.json').is_file():
            common, _ = build_common(stage, generated / 'common', base)
            if common:
                modules.append(common)
        card_manifest = stage / 'data/clubcard_manifest.json'
        if card_manifest.is_file() and read_json(card_manifest).get('cards'):
            cards.build(stage, base)
            modules.append({'id': 'clubcards', 'manifestPath': 'ebk-clubcards/manifest.json',
                            'videoPath': 'ebk-clubcards/cards.mp4', 'format': 'ebk-clubcards-v1'})
        slides.build(stage, stage / 'data/room_media_slides.json')
        modules.append({'id': 'roomMedia', 'manifestPath': 'ebk-room-media/manifest.json', 'format': 'ebk-room-media-v1'})
        themes.build(stage / 'themes')
        modules.append({'id': 'themes', 'manifestPath': 'themes/theme_catalog.json', 'format': 'ebk-theme-catalog-v1'})
        if (stage / 'docs').exists():
            for group in (stage / 'docs').iterdir():
                if group.is_dir():
                    shutil.copytree(group, generated / group.name)
        write_json(generated / 'ebk_media_root.json', {'schemaVersion': 1, 'format': 'ebk-media-root-v1', 'modules': modules})
        # Atomicity at the remote end is provided by the single generated commit.
        for directory in ['common', 'ebk-clubcards', 'ebk-room-media']:
            src = generated / directory
            if not src.exists():
                continue
            target = root / directory
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(src, target)
        (root / 'themes').mkdir(exist_ok=True)
        shutil.copyfile(stage / 'themes/theme_catalog.json', root / 'themes/theme_catalog.json')
        shutil.copyfile(generated / 'ebk_media_root.json', root / 'ebk_media_root.json')
    print('Built isolated media root:', root.name)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    build(args.root)
