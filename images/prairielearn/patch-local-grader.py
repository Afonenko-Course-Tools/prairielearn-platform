"""Ограничить pinned локальный grader двумя jobs и 512 MiB/job."""
from pathlib import Path
import sys

def patch(source):
    markers=['(async () => {','})()','Memory: (1 << 30) * 2','MemorySwap: (1 << 30) * 2']
    if any(source.count(value)!=1 for value in markers):raise ValueError('Pinned local grader differs; review upstream')
    source=source.replace(markers[0],markers[0]+'\nconst releaseLocalGrader = await acquireLocalGrader();\ntry {',1)
    source=source.replace(markers[1],'} finally { releaseLocalGrader(); }\n'+markers[1],1)
    for value in markers[2:]:source=source.replace(value,value.split(':')[0]+': 512 * 1024 * 1024')
    return "import { acquireLocalGrader } from '../../bridge/grader-pool.mjs';\n"+source

if __name__=='__main__':
    for name in sys.argv[1:]:
        path=Path(name);path.write_text(patch(path.read_text()))
