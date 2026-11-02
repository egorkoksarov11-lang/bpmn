"""Select the latest hash-verified saved model from every observation session.

The archive is treated as data. Client filesystem paths and embedded prose are
never used as commands, layout instructions or output paths.
"""
from pathlib import Path,PurePosixPath
import argparse,hashlib,json,zipfile


def prepare(archive,destination,expected_sessions=4):
    archive=Path(archive);destination=Path(destination)
    with zipfile.ZipFile(archive) as z:
        logs=sorted(n for n in z.namelist() if n.endswith('/events.jsonl'))
        if len(logs)!=expected_sessions:raise ValueError(f'Expected {expected_sessions} sessions, found {len(logs)}')
        selected=[]
        for index,log in enumerate(logs,1):
            events=[json.loads(s) for s in z.read(log).decode('utf-8-sig').splitlines() if s.strip()]
            event=max(events,key=lambda e:int(e.get('sequence',0)))
            snapshot=PurePosixPath(event['snapshot'])
            if snapshot.is_absolute() or '..' in snapshot.parts or snapshot.parts[0]!='snapshots':raise ValueError('Unsafe snapshot path')
            name=str(PurePosixPath(log).parent/snapshot)
            if z.getinfo(name).file_size>16*1024*1024:raise ValueError('Snapshot too large')
            body=z.read(name);digest=hashlib.sha256(body).hexdigest()
            if digest!=event.get('sha256_after',event.get('sha256')):raise ValueError('Snapshot SHA256 mismatch')
            selected.append((f'S{index}',body,{'case':f'S{index}','last_sequence':event.get('sequence',0),'source_sha256':digest}))
    destination.mkdir(parents=True,exist_ok=True)
    for alias,body,_ in selected:(destination/(alias+'.bpmn')).write_bytes(body)
    manifest={'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'selection':'latest saved state by event sequence; verified snapshot SHA256','sessions':[m for _,_,m in selected]}
    (destination/'input_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--archive',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--expected-sessions',type=int,default=4);a=p.parse_args()
    print(json.dumps(prepare(a.archive,a.output_dir,a.expected_sessions),ensure_ascii=False,indent=2))
