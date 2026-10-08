#!/usr/bin/env python3
"""Build ClubCard's existing 3-frame VideoRoster, with a generation marker.

Source cards are never renumbered or rewritten. Only docs/ebk-clubcards is owned.
The marker binds the video pixels to the full metadata and source image hashes.
"""
import argparse
import copy
import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw
from build_room_media_slides import encode, checked_tree, MAX_SITE_BYTES

RARITIES = ['N', 'R', 'SR', 'SSR', 'UR', 'S']
WEIGHTS = [2000, 1000, 600, 400, 40, 3]
MAGIC = 'eb4b26c1'
MARKER = '.ebk-clubcards-generated'


def validate(manifest):
    if manifest.get('schemaVersion') != 1 or type(manifest.get('revision')) is not int or manifest['revision'] < 1:
        raise ValueError('schemaVersion=1 / revision>=1 が必要です')
    rows = manifest.get('cards')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 127:
        raise ValueError('カードは1〜127枚で指定してください（世代確認1枠を別途使用）')
    seen = set()
    slots = set()
    for row in rows:
        n = row.get('cardNumber', '')
        serial = row.get('serial')
        if not isinstance(n, str) or not re.fullmatch(r'[0-9]{5}', n) or type(serial) is not int or serial != int(n) or serial in seen:
            raise ValueError('カード番号は重複のない5桁、serialと一致させてください')
        seen.add(serial)
        if not isinstance(row.get('cardName'), str) or not row['cardName'].strip() or len(row['cardName']) > 120:
            raise ValueError(n + ': カード名は1〜120文字で指定してください')
        for key in ['enabled', 'exchangeEnabled', 'manualRarityWeightOverride']:
            if type(row.get(key)) is not bool:
                raise ValueError(n + ': ' + key + ' はboolが必要です')
        price = row.get('exchangePriceOverride')
        if type(price) is not int or not 0 <= price <= 100000000:
            raise ValueError(n + ': 交換価格が不正です')
        manual = row['manualRarityWeightOverride']
        if manual:
            weight = row.get('weightOverride')
            if row.get('rarityOverride') not in RARITIES or type(weight) is not int or not 0 <= weight <= 1000000:
                raise ValueError(n + ': 個別レアリティ/ウェイトが不正です')
        elif serial % 10 > 5:
            raise ValueError(n + ': 末尾6〜9には個別設定が必要です')
        if row.get('imagePath') != 'images/clubcards/cards/' + n + '.png':
            raise ValueError(n + ': 画像は images/clubcards/cards/番号.png を指定してください')
        slot = row.get('videoSlot', serial)
        if type(slot) is not int or not 0 <= slot <= 99999 or slot in slots:
            raise ValueError(n + ': VideoRoster枠が不正または重複しています')
        slots.add(slot)
    rules = manifest.get('rarityRules', {})
    if rules.get('mode') != 'cardNumberLastDigit' or rules.get('byLastDigit') != {str(i): r for i, r in enumerate(RARITIES)} or rules.get('defaultWeights') != dict(zip(RARITIES, WEIGHTS)):
        raise ValueError('既存の末尾レアリティ/標準ウェイト規則を維持してください')
    return sorted(rows, key=lambda row: row['serial'])


def marker_image(generation, width, height):
    bits = ''.join(format(int(c, 16), '04b') for c in MAGIC + generation)
    image = Image.new('RGB', (width, height), 'black')
    draw = ImageDraw.Draw(image)
    for i, bit in enumerate(bits):
        if bit == '1':
            x, y = i % 20, i // 20
            draw.rectangle((x * width // 20, y * height // 8, (x + 1) * width // 20 - 1, (y + 1) * height // 8 - 1), fill='white')
    return image


def build(root, base_url):
    from urllib.parse import urlsplit
    base_url = base_url.rstrip('/')
    url = urlsplit(base_url)
    if url.scheme != 'https' or not url.hostname or url.query or url.fragment or url.username or any(c.isspace() for c in base_url):
        raise ValueError('公開先のHTTPS Pages URLが必要です')
    source = root / 'data/clubcard_manifest.json'
    if not source.exists():
        print('ClubCard source is not configured; skipped')
        return None
    manifest = json.loads(source.read_text(encoding='utf-8-sig'))
    if manifest.get('cards') == []:
        print('ClubCard has no cards yet; skipped')
        return None
    cards = copy.deepcopy(validate(manifest))
    checked_tree(root / 'images/clubcards')
    checked_tree(root / 'docs')
    images = []
    for row in cards:
        image = root / row['imagePath']
        if not image.is_file() or image.stat().st_size > 50 * 1024 * 1024:
            raise ValueError('カード画像がありません/50MiB超過: ' + str(image))
        with Image.open(image) as im:
            if max(im.size) > 2048 or min(im.size) < 1 or getattr(im, 'n_frames', 1) != 1:
                raise ValueError('静止画像を2048px以下にしてください: ' + row['cardNumber'])
        row['imageSha256'] = hashlib.sha256(image.read_bytes()).hexdigest()
        row['videoSlot'] = row.get('videoSlot', row['serial'])
        images.append(image)
    generation = hashlib.sha256(json.dumps({'cards': cards, 'revision': manifest['revision'], 'format': 'ebk-clubcards-v1'}, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:32]
    result = copy.deepcopy(manifest)
    result['cards'] = cards
    for i, row in enumerate(cards):
        row['captureKey'] = 'clubcard|cards|' + str(row['videoSlot'])
        row['sampleFrame'] = (i + 1) * 3 + 1
        row['sampleTimeSeconds'] = row['sampleFrame'] / 30
    result['videoRoster'] = {'status': 'ready', 'generation': generation, 'format': 'ebk-clubcards-v1',
                            'videoUrl': base_url + '/ebk-clubcards/cards.mp4',
                            'frameMapUrl': base_url + '/ebk-clubcards/frame_map.txt',
                            'fps': 30, 'framesPerEntry': 3, 'sampleFrame': 1,
                            'headerKey': 'clubcard|generation|0', 'headerTimeSeconds': 1 / 30,
                            'width': 1024, 'height': 1536, 'frameCount': (len(cards) + 1) * 3}
    target = root / 'docs/ebk-clubcards'
    if target.exists() and not (target / MARKER).is_file():
        raise ValueError('未所有のdocs/ebk-clubcardsは上書きしません')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ebk-clubcards-') as temporary:
        stage = Path(temporary) / 'output'
        stage.mkdir()
        header = Path(temporary) / 'generation.png'
        marker_image(generation, 1024, 1536).save(header)
        encode([header] + images, stage / 'cards.mp4', 1024, 1536)
        result['videoRoster']['sha256'] = hashlib.sha256((stage / 'cards.mp4').read_bytes()).hexdigest()
        (stage / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        lines = ['1|clubcard|generation|0|generation|1|1|0|0|frames=3|sampleFrame=1|sample=0.033333|bad=0']
        lines += [f"{r['sampleFrame']}|clubcard|cards|{r['videoSlot']}|{r['imageUrl']}|1|1|0|0|frames=3|sampleFrame=1|sample={r['sampleTimeSeconds']:.6f}|bad=0" for r in cards]
        (stage / 'frame_map.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
        (stage / MARKER).write_text('EBK ClubCard generated output v1\n')
        total = sum(p.stat().st_size for p in (root / 'docs').rglob('*') if p.is_file() and not p.is_relative_to(target))
        if total + sum(p.stat().st_size for p in stage.iterdir()) > MAX_SITE_BYTES:
            raise ValueError('Pages公開データが900MiBを超えます')
        # Build and verify before touching the previously published generation.
        swap = Path(tempfile.mkdtemp(prefix='.ebk-clubcards-', dir=target.parent))
        try:
            shutil.copytree(stage, swap / 'new')
            if target.exists(): target.rename(swap / 'previous')
            try: (swap / 'new').rename(target)
            except BaseException:
                if (swap / 'previous').exists(): (swap / 'previous').rename(target)
                raise
        finally: shutil.rmtree(swap)
    print(f'ClubCard: {len(cards)} cards, generation {generation}')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--pages-base-url', default='')
    args = parser.parse_args()
    base = args.pages_base_url
    if not base:
        base = json.loads((args.root / 'data/room_media_slides.json').read_text(encoding='utf-8-sig'))['pagesBaseUrl']
    build(args.root.resolve(), base)
