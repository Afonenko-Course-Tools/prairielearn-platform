"""Изолированная локальная проверка UID1001, fish/Git и restart тома; без portal."""
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid
from test_lifecycle import Lifecycle

image = sys.argv[1]
name = 'sp-c2-' + uuid.uuid4().hex[:12]
volume = name + '-data'
fixture = Lifecycle()
fixture.setUp()
fixture.root.chmod(0o755)
fixture.home.chmod(0o755)

def docker(*args):
    result = subprocess.run(['docker', *args], capture_output=True, text=True, timeout=90)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()

def run(script, seed=False):
    mounts = ['--mount', f'type=volume,source={volume},target=/home/coder/workspace']
    if seed:
        mounts += ['--mount', f'type=bind,source={fixture.home / ".pl-seed"},target=/fixtures,readonly']
    return docker('run', '--rm', '--network', 'none', '--user', '1001:1001', *mounts,
                  '--entrypoint', '/bin/bash', image, '-ec', script)

try:
    docker('volume', 'create', volume)
    first = run('''
cp -r /fixtures .pl-seed
/usr/local/bin/sp-git-workspace true
id -u
fish --version
git --version
cd work
git config user.name Fixture
git config user.email fixture@example.invalid
printf 'Название: проект измерений.\n' > README.md
printf 'Следующая встреча: вторник.\n' > notes.txt
git add README.md notes.txt
git restore --staged notes.txt
sha256sum .git/index
''', seed=True)
    after = run('''
/usr/local/bin/sp-git-workspace true
cd work
sha256sum .git/index
git show :notes.txt
cat notes.txt
git commit -qm 'Исправить название'
git rev-parse HEAD
''')
    assert '1001' in first and 'fish, version 3.7.0' in first, first
    assert first.splitlines()[-1] in after, 'Restart потерял binary index'
    assert 'Следующая встреча: понедельник.' in after and 'Следующая встреча: вторник.' in after, after
    b = after.splitlines()[-1]
    final = run('''
/usr/local/bin/sp-git-workspace true
cd work
git rev-parse HEAD
cat notes.txt
git restore notes.txt
test -z "$(git status --porcelain)"
git rev-parse HEAD
''')
    assert final.splitlines()[0] == b == final.splitlines()[-1], 'Restart/restore изменил B'
    docker('run', '-d', '--name', name, '--network', 'none', '--user', '1001:1001',
           '--mount', f'type=volume,source={volume},target=/home/coder/workspace', image)
    ready = False
    for _ in range(30):
        result = subprocess.run(['docker','exec',name,'curl','--silent','--fail','http://127.0.0.1:8080/healthz'],capture_output=True,text=True)
        if result.returncode == 0:
            ready = True
            break
        time.sleep(0.25)
    assert ready, 'Code-server HTTP не готов: '+docker('logs',name)
    receipt = {'image':image,'uid':1001,'fish':'3.7.0','seedA':fixture.a,
               'containerRecreation':'PASS','splitIndexWorktree':'PASS','BPreserved':'PASS','httpHealth':'PASS',
               'liveWorkspaceHost':'NOT_RUN'}
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
finally:
    subprocess.run(['docker','rm','-f',name],capture_output=True)
    subprocess.run(['docker','volume','rm',volume],capture_output=True)
    fixture.tearDown()
