"""Публичная CLI публикации; OCI digests здесь вымышленные."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Mapping

from selected_job_fixture import fixture_record

ROOT = Path(__file__).resolve().parents[1]
IMAGES = {
    'java': 'ghcr.io/example/java25-grader@sha256:' + '1' * 64,
    'fish': 'ghcr.io/example/fish-git-grader@sha256:' + '2' * 64,
    'community': 'ghcr.io/example/prairielearn-community-gateway@sha256:' + '3' * 64,
}

class PublishedMetadata(unittest.TestCase):
    def produce(self, changes: Mapping[str, str] | None = None) -> tuple[subprocess.CompletedProcess[bytes], dict[str, dict[str, object]]]:
        env = dict(os.environ, GITHUB_SHA=subprocess.check_output(
            ['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
            VERSION=(ROOT/'VERSION').read_text().strip(),
            **{key.upper()+'_DIGEST': value for key,value in IMAGES.items()})
        env.update(changes or {})
        with tempfile.TemporaryDirectory(prefix='publisher-public-') as output:
            result = subprocess.run([sys.executable, '-B', str(ROOT/'tools/publish-metadata.py')],
                cwd=output, env=env, capture_output=True, timeout=10)
            files = {p.name: fixture_record(json.loads(p.read_bytes())) for p in Path(output).iterdir()}
        return result, files

    def test_publishes_runtime_profiles_without_preparation_or_file_inventories(self):
        result, files = self.produce()
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(set(files), {'runtime-image.json', 'published-runtime-profiles.json'})
        profiles = fixture_record(files['published-runtime-profiles.json']['profiles'])
        self.assertEqual(set(profiles), {'java25-junit-v1','java25-mutation-v1','java25-gradle-junit-v1','fish-git-v1'})
        for name, raw_profile in profiles.items():
            profile = fixture_record(raw_profile)
            self.assertEqual(profile['image'], IMAGES['fish' if name=='fish-git-v1' else 'java'])
            self.assertTrue({'runnerSha256','files','sharedFiles','dependencies'}.isdisjoint(profile))
        receipt=files['runtime-image.json']
        self.assertEqual(receipt['images'], IMAGES)
        self.assertNotIn('runtimeProfilesSha256', receipt)
        self.assertEqual(receipt['deliverySchemaVersion'], 5)

    def test_workspace_uses_its_own_image_role(self):
        workspace='ghcr.io/example/sp-git-workspace@sha256:'+'4'*64
        result, files = self.produce({'WORKSPACE_DIGEST':workspace})
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(files['published-runtime-profiles.json']['workspaceImages'], {'sp-git-workspace-v1':{'image':workspace}})
        self.assertEqual(fixture_record(files['runtime-image.json']['images'])['workspace'], workspace)

    def test_rejects_image_from_other_role_before_writing(self):
        for changes in ({'JAVA_DIGEST':IMAGES['fish']},{'JAVA_DIGEST':'sha256:'+'1'*64},{'WORKSPACE_DIGEST':IMAGES['java']}):
            with self.subTest(changes=changes):
                result, files=self.produce(changes)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(files,{})

    def test_records_real_source_commit_and_version(self):
        result, files=self.produce()
        self.assertEqual(result.returncode,0,result.stderr.decode())
        receipt=files['runtime-image.json']
        self.assertEqual(receipt['sourceCommit'],subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip())
        self.assertEqual(receipt['version'],(ROOT/'VERSION').read_text().strip())
        for changes in ({'GITHUB_SHA':'f'*40},{'VERSION':'0.0.0'}):
            with self.subTest(changes=changes):
                result, files=self.produce(changes)
                self.assertNotEqual(result.returncode,0)
                self.assertEqual(files,{})

if __name__=='__main__': unittest.main()
