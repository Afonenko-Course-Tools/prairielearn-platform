"""Доверенная подготовка внутри образа; Java/Gradle/Landlock не запускаются."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import stat
import sys
import zipfile

ROOT=Path('/platform')
OPERATOR=Path('/operator')
def require(condition,message):
    if not condition:raise RuntimeError(message)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def inventory(home):
    require(home.is_dir() and not home.is_symlink(),'Invalid installation root')
    result={}
    for path in [home,*sorted(home.rglob('*'))]:
        info=path.lstat()
        require(info.st_uid==0 and not info.st_mode&0o7022,'Unsafe installation owner/mode')
        if stat.S_ISDIR(info.st_mode):continue
        require(stat.S_ISREG(info.st_mode) and info.st_nlink==1,'Nonregular/single-link installation member')
        result[path.relative_to(home).as_posix()]={'sha256':sha(path),'bytes':info.st_size,'mode':oct(stat.S_IMODE(info.st_mode))}
    return result

require(os.geteuid()==0,'Supervisor must be UID0')
os.umask(0o022)
expected_bytes=(OPERATOR/'hardened-toolchain-lock.json').read_bytes()
lock=json.loads(expected_bytes)
require(lock['status']=='image-admitted','Expected future lock shape changed')
spec=importlib.util.spec_from_file_location('prepare_native_jdk',ROOT/'tools/prepare_native_jdk.py')
normalizer=importlib.util.module_from_spec(spec);sys.modules[spec.name]=normalizer;spec.loader.exec_module(normalizer)
admitted=normalizer._validate_production_admission((OPERATOR/'source-inventory.json').read_bytes())
require(lock['baseImage']==normalizer.BASE_IMAGE and lock['jdk']==admitted['expectedNormalizedJdk'],'Expected source/lock cross-binding mismatch')
# Normalizer executes no JDK/Gradle bytecode. A new receipt is generated only by actual copy.
require(normalizer.main(['--admission',str(OPERATOR/'source-inventory.json'),'--receipt',str(OPERATOR/'normalization-receipt.json')])==0,'Normalization failed')
receipt=json.loads((OPERATOR/'normalization-receipt.json').read_text())
require(receipt['actualCopyCreated'] and not receipt['normalizedInstallationAdmission'] and receipt['normalizedFiles']==lock['jdk']['files'],'Missing actual copy relation')
require(inventory(Path(lock['jdk']['home']))==lock['jdk']['files'],'Independent JDK inventory mismatch')
archive=Path('/toolchain/gradle-9.8.0-bin.zip')
require(archive.stat().st_size==lock['gradle']['archiveBytes'] and sha(archive)==lock['gradle']['archiveSha256'],'Official ZIP pin mismatch')
target=Path('/opt/gradle/gradle-9.8.0')
require(lock['gradle']['home']==str(target) and not os.path.lexists(target),'Fresh exact Gradle destination required')
with zipfile.ZipFile(archive) as distribution:
    files={};directories=set();names=set()
    for entry in distribution.infolist():
        raw=entry.filename;name=raw.rstrip('/');parts=name.split('/');mode=entry.external_attr>>16
        require(name not in names and parts[0]=='gradle-9.8.0' and all(p not in ('','.','..') for p in parts) and '\\' not in name and not any(ord(ch)<32 or ord(ch)==127 for ch in name),'Unsafe/duplicate archive path')
        names.add(name)
        if entry.is_dir():
            require(stat.S_ISDIR(mode) and not mode&0o7022,'Unsafe archive directory');directories.add('/'.join(parts[1:]));continue
        require(stat.S_ISREG(mode) and not mode&0o7022,'Unsafe archive file')
        relative='/'.join(parts[1:]);require(relative in lock['gradle']['files'],'Unexpected archive member')
        expected=lock['gradle']['files'][relative];require(entry.file_size==expected['bytes'],'Archive size mismatch')
        data=distribution.read(entry);files[relative]={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'mode':oct(mode&0o777)}
    require(files==lock['gradle']['files'],'Full official archive inventory mismatch')
    target.mkdir(parents=True,exist_ok=False)
    for directory in sorted(directories,key=lambda value:(len(value.split('/')),value)):
        (target/directory).mkdir(parents=True,exist_ok=True)
    for relative,record in sorted(files.items()):
        output=target/relative;output.parent.mkdir(parents=True,exist_ok=True)
        with output.open('xb') as stream:stream.write(distribution.read('gradle-9.8.0/'+relative))
        output.chmod(int(record['mode'],8))
require(inventory(target)==lock['gradle']['files'],'Independent Gradle installation inventory mismatch')
require(inventory(Path(lock['jdk']['home']))==lock['jdk']['files'],'JDK drift after Gradle preparation')
# Candidate-only runtime lock is installed AFTER actual byte-level preparation;
# its required existing status is not ROOT image/functional/OCI admission evidence.
(ROOT/'runtime/gradle-jar-v1/toolchain-lock.json').write_bytes(expected_bytes)
(ROOT/'runtime/gradle-jar-v1/toolchain-lock.json').chmod(0o644)
(OPERATOR/'normalization-receipt.json').chmod(0o600)
OPERATOR.chmod(0o700);ROOT.chmod(0o700);Path('/javagrader').chmod(0o700)
archive.unlink()

# Последний шаг сохраняет hardened316 и добавляет JNI только в private build319.
import runpy
runpy.run_path('/operator/complete-native.py',run_name='__main__')
