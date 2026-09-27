#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SUPPORTED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp'}
SLOT_PATTERN = re.compile(r'^slot([0-9]+)$', re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Create a temporary VideoRoster manifest whose Menu poster entries follow images/posters/menu/slotN.* exactly.'
    )
    parser.add_argument('--manifest', default='data/roster_manifest.json')
    parser.add_argument('--menu-dir', default='images/posters/menu')
    parser.add_argument('--output', default='data/roster_manifest.video.generated.json')
    parser.add_argument('--allow-gaps', action='store_true')
    return parser.parse_args()


def discover_menu_slots(menu_dir: Path) -> list[int]:
    if not menu_dir.exists() or not menu_dir.is_dir():
        return []

    found: dict[int, Path] = {}
    for path in menu_dir.iterdir():
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
                f'Duplicate Menu slot{slot}: {found[slot].name} and {path.name}. Keep one image per slot.'
            )
        found[slot] = path

    return sorted(found.keys())


def validate_contiguous(slots: list[int], allow_gaps: bool) -> None:
    if allow_gaps or not slots:
        return
    expected = list(range(len(slots)))
    if slots != expected:
        raise RuntimeError(
            'Menu slots must be contiguous from slot0 when dynamic LocalImageAlbumFade sizing is enabled. '
            f'Found={slots}, expected={expected}'
        )


def build_manifest(source: dict, menu_slots: list[int]) -> dict:
    result = dict(source)
    posters = source.get('posters', [])
    new_posters: list[dict] = []

    if isinstance(posters, list):
        for item in posters:
            if not isinstance(item, dict):
                continue
            category = str(item.get('category', '')).strip().lower()
            if category == 'menu':
                continue
            new_posters.append(dict(item))

    for slot in menu_slots:
        new_posters.append({
            'enabled': True,
            'category': 'Menu',
            'slot': slot,
        })

    result['posters'] = new_posters
    return result


def main() -> int:
    args = parse_args()
    manifest_path = Path(args.manifest)
    menu_dir = Path(args.menu_dir)
    output_path = Path(args.output)

    if not manifest_path.exists():
        raise FileNotFoundError(f'Manifest not found: {manifest_path}')

    source = json.loads(manifest_path.read_text(encoding='utf-8'))
    if not isinstance(source, dict):
        raise RuntimeError('roster_manifest.json root must be an object.')

    slots = discover_menu_slots(menu_dir)
    validate_contiguous(slots, args.allow_gaps)
    generated = build_manifest(source, slots)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(generated, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )

    print(f'Menu image count: {len(slots)}')
    if slots:
        print(f'Menu slots: {slots[0]}..{slots[-1]}')
    else:
        print('Menu slots: none')
    print(f'Generated manifest: {output_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
