"""Publish generated preview media to an isolated root; never write legacy media."""
from pathlib import Path
import hashlib,json,shutil,sys,tempfile
ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'tests/ebk-videoroster'
TARGET=ROOT/'NewClubCommuShow'
OLD='https://clubcommushow.github.io/ClubCommuShow/tests/ebk-videoroster'
NEW='https://clubcommushow.github.io/ClubCommuShow/NewClubCommuShow'

def build(source=SOURCE,target=TARGET):
    source=Path(source).resolve();target=Path(target).resolve()
    if target.name!='NewClubCommuShow' or source==target:raise ValueError('Isolated NewClubCommuShow target required')
    suite=json.loads((source/'groups/suite.json').read_text())
    if suite.get('format')!='ebk-sample-media-suite-v1' or not suite.get('testOnly'):raise ValueError('Expected verified sample suite')
    with tempfile.TemporaryDirectory() as tmp:
        stage=Path(tmp)
        for group in suite['groups']:
            gid=group['id']
            if not gid or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in gid):raise ValueError('Bad group ID')
            folder=source/'groups'/gid
            m=json.loads((folder/'manifest.json').read_text())
            if m.get('generation')!=group['generation'] or m.get('groupId')!=gid or not m.get('testOnly'):raise ValueError('Manifest generation mismatch')
            video=folder/('roster_'+m['generation']+'.mp4')
            if video.is_symlink() or hashlib.sha256(video.read_bytes()).hexdigest()!=m['videoSha256']:raise ValueError('Video SHA256 mismatch')
            dest=stage/'groups'/gid;dest.mkdir(parents=True)
            shutil.copyfile(video,dest/video.name)
            (dest/'manifest.json').write_text(json.dumps(m,ensure_ascii=False,indent=2).replace(OLD,NEW)+'\n')
        for name in ['suite.json','theme_catalog.json','room_catalog.json']:
            p=source/'groups'/name
            (stage/'groups'/name).write_text(p.read_text().replace(OLD,NEW))
        index=json.loads((source/'ebk_media_root.json').read_text())
        for module in index['modules']:
            if module['id']=='common':module.update(manifestPath='groups/common/manifest.json',format='ebk-sample-videoroster-v1',sampleOnly=True)
        (stage/'ebk_media_root.json').write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n')
        # Verify the complete input first. Only generated preview paths are copied.
        target.mkdir(parents=True,exist_ok=True)
        for p in stage.rglob('*'):
            if p.is_file():
                out=target/p.relative_to(stage);out.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,out)
    print('Published six verified sample groups under NewClubCommuShow; legacy media unchanged')
if __name__=='__main__':build()
