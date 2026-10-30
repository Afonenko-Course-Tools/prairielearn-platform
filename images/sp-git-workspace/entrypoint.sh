#!/bin/bash
set -euo pipefail
# cwd — native workspaceOptions.home; PL восстанавливает его до запуска image.
python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile
import zipfile

root = Path.cwd()
seed = root / '.pl-seed'
manifest = json.loads((seed / 'manifest.json').read_text())
if set(manifest) != {'schema', 'sha256', 'files'} or manifest['schema'] != 'pl-git-workspace-seed-v1':
    raise SystemExit('SP.SEED_INVALID: неверный manifest')
archive = seed / 'starter.zip'
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
if digest != manifest['sha256']:
    raise SystemExit('SP.SEED_INVALID: изменён архив')
work = root / 'work'
identity = seed / 'identity.json'
if work.exists() or work.is_symlink():
    if work.is_symlink() or not work.is_dir() or not identity.is_file():
        raise SystemExit('SP.RESUME_UNKNOWN: работа сохранена; автоматическая инициализация запрещена')
    chosen = json.loads(identity.read_text())
    if chosen.get('schema') != manifest['schema'] or chosen.get('sha256') != digest:
        raise SystemExit('SP.SEED_CHANGED: работа сохранена; выбранная заготовка изменилась')
    # На restart не вызываем даже Git: чтение status может освежить index.
else:
    if identity.exists():
        raise SystemExit('SP.RESUME_MISSING: выбранная работа отсутствует; автоматический сброс запрещён')
    entries = manifest['files']
    if not isinstance(entries, list) or not 1 <= len(entries) <= 4096:
        raise SystemExit('SP.SEED_INVALID: неверный inventory')
    expected = {entry['name']: entry['sha256'] for entry in entries}
    if len(expected) != len(entries):
        raise SystemExit('SP.SEED_INVALID: повтор inventory')
    stage = Path(tempfile.mkdtemp(prefix='.sp-init-', dir=root))
    try:
        with zipfile.ZipFile(archive) as z:
            members = z.infolist()
            if len(members) != len(expected) or sum(m.file_size for m in members) > 16 * 1024 * 1024:
                raise SystemExit('SP.SEED_INVALID: состав или размер ZIP')
            seen = set()
            for member in members:
                name = member.filename
                parts = PurePosixPath(name).parts
                mode = member.external_attr >> 16
                if (name not in expected or name in seen or not parts or name.startswith('/')
                    or '\\' in name or '\x00' in name or any(p in ('', '.', '..') for p in name.split('/'))
                    or parts[0] == '.pl-seed' or member.is_dir()
                    or stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
                    raise SystemExit('SP.SEED_INVALID: небезопасный member')
                seen.add(name)
                data = z.read(member)
                if hashlib.sha256(data).hexdigest() != expected[name]:
                    raise SystemExit('SP.SEED_INVALID: member не соответствует inventory')
                target = stage / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                target.chmod(0o755 if mode & 0o111 else 0o644)
        env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
        env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null', GIT_TERMINAL_PROMPT='0')
        def git(*args):
            return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false', *args],
                                           cwd=stage/'work', env=env, text=True, stderr=subprocess.PIPE).strip()
        git('fsck', '--full', '--no-reflogs')
        if (git('symbolic-ref', 'HEAD') != 'refs/heads/main'
            or git('rev-list', '--count', '--all') != '1'
            or git('status', '--porcelain') != ''):
            raise SystemExit('SP.SEED_INVALID: требуется только чистый исходный A/main')
        chosen = {'schema': manifest['schema'], 'sha256': digest, 'seedCommit': git('rev-parse', 'HEAD')}
        # Публикуем проверенный work одним rename, существующую работу не перезаписываем.
        (stage/'work').rename(work)
        for source in stage.iterdir():
            target = root/source.name
            if not target.exists():
                source.rename(target)
        pending = seed/'identity.json.pending'
        pending.write_text(json.dumps(chosen, ensure_ascii=False, indent=2)+'\n')
        pending.replace(identity)
    finally:
        shutil.rmtree(stage)
PY
if [ "$#" -eq 0 ]; then
  set -- /entrypoint.sh
fi
exec "$@"
