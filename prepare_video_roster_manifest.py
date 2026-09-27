#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SUPPORTED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}
SLOT_PATTERN = re.compile(r'^slot([0-9]+)$', re.IGNORECASE)

# GitHub上のPosterフォルダをVideoRoster用カテゴリへ変換。
# すべて slot0..N の実ファイル数へ追従する。
POSTER_FOLDERS = [
    ('main', 'EventPoster'),
    ('front', 'FrontPoster'),
    ('side', 'SidePoster'),
    ('back', 'BackPoster'),
    ('notice', 'Notice'),
    ('menu', 'Menu'),
    ('kanpe', 'Kanpe'),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Create a temporary VideoRoster manifest whose poster entries follow images/posters/*/slotN.* exactly.'
    )
    parser.add_argument('--manifest', default='data/roster_manifest.json')
    parser.add_argument('--posters-root', default='images/posters')
    # RC4.2 workflow compatibility. If supplied, its parent is used as posters root.
    parser.add_argument('--menu-dir', default='')
    parser.add_argument('--output', default='data/roster_manifest.video.generated.json')
    parser.add_argument('--allow-gaps', action='store_true')
    return parser.parse_args()


def discover_slots(folder: Path, category: str) -> list[int]:
    if not folder.exists() or not folder.is_dir():
        return []

    found: dict[int, Path] = {}
    for path in folder.iterdir():
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        match = SLOT_PATTERN.match(path.stem)
        if match is None:
            continue

        slot = int(match.group(1))
        if slot in found:
            raise RuntimeError(
                f'Duplicate {category} slot{slot}: {found[slot].name} and {path.name}. Keep one image per slot.'
            )
        found[slot] = path

    return sorted(found.keys())


def validate_contiguous(category: str, slots: list[int], allow_gaps: bool) -> None:
    if allow_gaps or not slots:
        return

    expected = list(range(len(slots)))
    if slots != expected:
        raise RuntimeError(
            f'{category} slots must be contiguous from slot0. Found={slots}, expected={expected}'
        )


def build_manifest(source: dict, discovered: list[tuple[str, list[int]]]) -> dict:
    result = dict(source)

    known_categories = {category.lower() for _, category in POSTER_FOLDERS}
    existing = source.get('posters', [])
    new_posters: list[dict] = []

    # Unknown/custom poster categories are preserved.
    if isinstance(existing, list):
        for item in existing:
            if not isinstance(item, dict):
                continue
            category = str(item.get('category', '')).strip().lower()
            if category in known_categories:
                continue
            new_posters.append(dict(item))

    for category, slots in discovered:
        for slot in slots:
            new_posters.append({
                'enabled': True,
                'category': category,
                'slot': slot,
            })

    result['posters'] = new_posters
    return result


def main() -> int:
    args = parse_args()

    manifest_path = Path(args.manifest)
    if args.menu_dir:
        posters_root = Path(args.menu_dir).parent
    else:
        posters_root = Path(args.posters_root)
    output_path = Path(args.output)

    if not manifest_path.exists():
        raise FileNotFoundError(f'Manifest not found: {manifest_path}')

    source = json.loads(manifest_path.read_text(encoding='utf-8'))
    if not isinstance(source, dict):
        raise RuntimeError('roster_manifest.json root must be an object.')

    discovered: list[tuple[str, list[int]]] = []
    total = 0
    for folder_name, category in POSTER_FOLDERS:
        slots = discover_slots(posters_root / folder_name, category)
        validate_contiguous(category, slots, args.allow_gaps)
        discovered.append((category, slots))
        total += len(slots)

        if slots:
            print(f'{category}: {len(slots)} slots ({slots[0]}..{slots[-1]})')
        else:
            print(f'{category}: 0 slots')

    generated = build_manifest(source, discovered)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(generated, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )

    members = generated.get('members', [])
    member_count = len(members) if isinstance(members, list) else 0
    print(f'Member manifest entries: {member_count}')
    print(f'Auto poster entries: {total}')
    print(f'Generated manifest: {output_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
