"""Java publisher исполняет настоящие shell guards на вымышленных registry readbacks."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from json_boundary import JSONObject, json_object

ROOT = Path(__file__).resolve().parents[1]


def steps() -> list[JSONObject]:
    workflow = json_object(yaml.load((ROOT/'.github/workflows/publish-runtime.yml').read_text(), Loader=yaml.BaseLoader))
    jobs = json_object(workflow['jobs'])
    java = json_object(jobs['java'])
    raw = java['steps']
    assert isinstance(raw, list)
    return [json_object(step) for step in raw]


class JavaPublication(unittest.TestCase):
    def run_java(self, name: str, changes: dict[str, str] | None = None) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
        with tempfile.TemporaryDirectory(prefix='java-publisher-') as temporary:
            root = Path(temporary)
            commands = root/'bin'; commands.mkdir()
            (root/'VERSION').write_text('2.6.0\n')
            import os
            git = commands/'git'; git.write_text('#!/bin/sh\nprintf "%s\\n" "$FIXTURE_HEAD"\n'); git.chmod(0o700)
            docker = commands/'docker'; docker.write_text('''#!/bin/sh
printf '%s\\n' "$*" >> "$FIXTURE_CALLS"
case "$*" in
  *RepoDigests*) printf '%s\\n' "$FIXTURE_DIGEST";;
  *org.opencontainers.image.revision*) printf '%s\\n' "$FIXTURE_REVISION";;
  *org.opencontainers.image.source*) printf '%s\\n' "$FIXTURE_SOURCE";;
  *'{{.Id}}'*) printf '%s\\n' "$FIXTURE_IMAGE_ID";;
  'image inspect '*) printf '%s\\n' '[{"Id":"fictional-owned-image"}]';;
  'pull '*) test "$FIXTURE_PULL" = success;;
  *) exit 90;;
esac
'''); docker.chmod(0o700)
            env = {**os.environ, 'PATH': str(commands)+':/usr/bin:/bin', 'VERSION':'2.6.0',
                   'REVIEWED_COMMIT':'a'*40, 'GITHUB_SHA':'a'*40, 'GITHUB_REF':'refs/heads/main',
                   'GITHUB_REPOSITORY':'Example/Platform', 'GITHUB_REPOSITORY_OWNER':'Example',
                   'GITHUB_ENV':str(root/'env'), 'GITHUB_STEP_SUMMARY':str(root/'summary'),
                   'RUNTIME_IMAGE':'ghcr.io/example/java25-grader:2.6.0',
                   'TESTED_JAVA_IMAGE_ID':'sha256:'+'c'*64, 'FIXTURE_HEAD':'a'*40,
                   'FIXTURE_CALLS':str(root/'calls'), 'FIXTURE_DIGEST':'ghcr.io/example/java25-grader@sha256:'+'b'*64,
                   'FIXTURE_IMAGE_ID':'sha256:'+'c'*64, 'FIXTURE_REVISION':'a'*40,
                   'FIXTURE_SOURCE':'https://github.com/Example/Platform', 'FIXTURE_PULL':'success'}
            env.update(changes or {})
            source = next(step['run'] for step in steps() if step.get('name') == name)
            assert isinstance(source, str)
            cp = subprocess.run(['bash','-euo','pipefail','-c',source],cwd=root,env=env,capture_output=True,text=True,timeout=10)
            return cp,{p.name:p.read_text() for p in root.iterdir() if p.is_file()}

    def test_java_source_guard(self) -> None:
        name='Зафиксировать reviewed Java source'
        cp, files=self.run_java(name)
        self.assertEqual(cp.returncode,0,cp.stderr)
        self.assertEqual(files['env'],'RUNTIME_IMAGE=ghcr.io/example/java25-grader:2.6.0\n')
        for change in [{'VERSION':'latest'},{'VERSION':'2.5.9'},{'REVIEWED_COMMIT':'d'*40},
                       {'GITHUB_SHA':'d'*40},{'FIXTURE_HEAD':'d'*40},{'GITHUB_REF':'refs/heads/candidate'}]:
            cp,files=self.run_java(name,change)
            self.assertNotEqual(cp.returncode,0,change);self.assertNotIn('env',files)

    def test_java_readback_and_assets(self) -> None:
        cp,files=self.run_java('Сохранить Java digest и image config ID')
        self.assertEqual(cp.returncode,0,cp.stderr)
        receipt=json_object(json.loads(files['java-image.json']))
        self.assertEqual(receipt['source_commit'],'a'*40)
        self.assertEqual(receipt['image_config_id'],'sha256:'+'c'*64)
        self.assertEqual(files['java-image.txt'].strip(),receipt['repo_digest'])
        self.assertIn('pull '+str(receipt['repo_digest']),files['calls'])
        self.assertIn('java-image-inspect.json',files)
        for change in [{'FIXTURE_DIGEST':'ghcr.io/foreign/java25-grader@sha256:'+'b'*64},
                       {'FIXTURE_DIGEST':'ghcr.io/example/fish-git-grader@sha256:'+'b'*64},
                       {'FIXTURE_DIGEST':'ghcr.io/example/java25-grader:latest'},
                       {'FIXTURE_REVISION':'d'*40},{'FIXTURE_SOURCE':'https://github.com/foreign/Platform'},
                       {'FIXTURE_IMAGE_ID':'sha256:'+'d'*64},{'FIXTURE_PULL':'failed'}]:
            cp,files=self.run_java('Сохранить Java digest и image config ID',change)
            self.assertNotEqual(cp.returncode,0,change)
            self.assertNotIn('java-image.json',files);self.assertNotIn('java-image.txt',files)

    def test_java_job_has_only_java_outputs(self) -> None:
        commands='\n'.join(str(step.get('run','')) for step in steps())
        for forbidden in ['fish-git-grader','prairielearn-community-gateway','sp-git-workspace','tools/publish-metadata.py']:
            self.assertNotIn(forbidden,commands)
        for needed in ['test_grader*.py','test_binding_compilation_stages.py','test_plain_image.py']:
            self.assertIn(needed,commands)
        outputs='\n'.join(str(step.get('with',{})) for step in steps())
        for asset in ['java-image.json','java-image.txt','java-image-inspect.json']:self.assertIn(asset,outputs)

if __name__=='__main__':unittest.main()
