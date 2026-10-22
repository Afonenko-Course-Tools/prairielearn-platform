#!/usr/bin/env python3
"""Воспроизводимо копирует pinned native schemas из canonical exporter."""
import argparse,hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--exporter',required=True,type=Path);parser.add_argument('--check',action='store_true');args=parser.parse_args()
source=args.exporter.resolve();base='_extensions/course-prairielearn/spec/upstream';target=ROOT/'schemas/native-upstream';names=['infoCourse.json','infoCourseInstance.json','infoAssessment.json','infoQuestion.json','PRAIRIELEARN-LICENSE','provenance.json']
commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip();repository=subprocess.check_output(['git','remote','get-url','origin'],cwd=source,text=True).strip();files={}
for name in names:
 path=source/base/name
 if path.is_symlink() or path.resolve()!=path:raise SystemExit('Unsafe schema source')
 data=path.read_bytes();pinned=subprocess.check_output(['git','show',commit+':'+base+'/'+name],cwd=source)
 if data!=pinned:raise SystemExit('Native schema differs from committed provider dependency')
 files[name]=hashlib.sha256(data).hexdigest()
 if args.check:
  if (target/name).read_bytes()!=data:raise SystemExit('Stale generated native schema')
 else:target.mkdir(parents=True,exist_ok=True);(target/name).write_bytes(data)
manifest={'repository':repository,'commit':commit,'path':base,'files':files}
value=(json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode()
if args.check:
 if (target/'manifest.json').read_bytes()!=value:raise SystemExit('Stale generated provider manifest')
else:(target/'manifest.json').write_bytes(value)
print('PASS pinned native schema dependency')
