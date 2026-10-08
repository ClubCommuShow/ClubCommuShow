"""Mirror only owned slide output into the existing root Pages source."""
from pathlib import Path
import shutil
source=Path('docs/ebk-room-media')
target=Path('ebk-room-media')
marker='.ebk-room-media-generated'
if not (source/marker).is_file():raise SystemExit('Missing generated output marker')
if target.exists():
 if not (target/marker).is_file():raise SystemExit('Refusing to replace unowned root directory')
 shutil.rmtree(target)
shutil.copytree(source,target)
Path('docs/data').mkdir(parents=True,exist_ok=True)
for name in ['clubcard_manifest.json','content_manifest.json']:
 shutil.copy2(Path('data')/name,Path('docs/data')/name)
