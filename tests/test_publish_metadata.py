"""Producer checks; image digests below are explicitly fictional unit inputs."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
IMAGES = {
    'java': 'ghcr.io/example/java25-grader@sha256:' + '1' * 64,
    'fish': 'ghcr.io/example/fish-git-grader@sha256:' + '2' * 64,
    'community': 'ghcr.io/example/prairielearn-community-gateway@sha256:' + '3' * 64,
}


class PublishedMetadata(unittest.TestCase):
    def run_producer(self, changes=None):
        env = dict(os.environ, GITHUB_SHA=subprocess.check_output(
            ['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
            VERSION='2.3.0', **{k.upper() + '_DIGEST': v for k, v in IMAGES.items()})
        env.update(changes or {})
        with tempfile.TemporaryDirectory(prefix='publisher-unit-') as output:
            # The historical CLI reads this from cwd. Retain that real input
            # when demonstrating its lost native profile; the new CLI binds ROOT.
            (Path(output) / 'runtime-profiles.json').write_bytes((ROOT / 'runtime-profiles.json').read_bytes())
            process = subprocess.run([sys.executable, str(ROOT / 'tools/publish-receipt.py')],
                                     cwd=output, env=env, capture_output=True, timeout=30)
            files = {p.name: p.read_bytes() for p in Path(output).iterdir() if p.name != 'runtime-profiles.json'}
        return process, files

    def require_context(self):
        if not (ROOT / '.native-toolchain').is_dir():
            self.skipTest('Requires explicit authenticated host preparation; no implicit downloads')

    def assert_refused(self, changes=None):
        process, files = self.run_producer(changes)
        self.assertNotEqual(process.returncode, 0)
        self.assertEqual(files, {}, 'Rejected input must not emit release metadata')

    def test_real_producer_emits_four_current_profiles_and_bound_lock(self):
        self.require_context()
        process, files = self.run_producer()
        self.assertEqual(process.returncode, 0, process.stderr.decode())
        registry = json.loads(files['published-runtime-profiles.json'])
        self.assertEqual(set(registry['profiles']), {
            'java25-junit-v1', 'java25-mutation-v1', 'java25-gradle-junit-v1', 'fish-git-v1'})
        for name in ('java25-junit-v1', 'java25-mutation-v1', 'java25-gradle-junit-v1'):
            profile = registry['profiles'][name]
            self.assertEqual(profile['image'], IMAGES['java'])
            self.assertEqual(profile['runnerSha256'],
                             '05aa5dfe0889c48b57eacf665c4274ac18d9ac3b1a0f18f4a948cc09fba7a737')
            self.assertEqual(profile['sharedFiles']['runtime/gradle-jar-v1/toolchain-lock.json'],
                             'c44c6f648e0bafbd2f87871813a8c5b2095315c465ddbf14e1b6282acae574ca')
        native = registry['profiles']['java25-gradle-junit-v1']
        for name in ('build.gradle', 'settings.gradle'):
            path = 'runtime/gradle-jar-v1/' + name
            self.assertEqual(native['sharedFiles'][path], hashlib.sha256((ROOT / path).read_bytes()).hexdigest())
        fish = registry['profiles']['fish-git-v1']
        self.assertEqual(fish['image'], IMAGES['fish'])
        self.assertEqual(fish['sharedFiles']['schemas/grading-descriptor.schema.json'],
                         hashlib.sha256((ROOT / 'schemas/grading-descriptor.schema.json').read_bytes()).hexdigest())
        self.assertEqual(hashlib.sha256(files['published-toolchain-lock.json']).hexdigest(),
                         'c44c6f648e0bafbd2f87871813a8c5b2095315c465ddbf14e1b6282acae574ca')
        receipt = json.loads(files['runtime-image.json'])
        self.assertEqual(receipt['runtimeProfilesSha256'], hashlib.sha256(files['published-runtime-profiles.json']).hexdigest())
        self.assertEqual((receipt['schemaVersion'], receipt['deliverySchemaVersion'],
                          receipt['resultsSchemaVersion']), (2, 3, 2))
        # Bind the emitted protocol to the actual current delivery consumer,
        # rather than deriving the expected version from the publisher itself.
        sys.path.insert(0, str(ROOT / 'tools'))
        import delivery_verification
        delivery = {
            'schemaVersion': receipt['deliverySchemaVersion'], 'courseId': 'synthetic',
            'bookRoot': 'tasks', 'sourceSnapshotHash': 'a' * 64, 'inventoryHash': 'b' * 64,
            'verificationInventoryHash': 'c' * 64, 'deliveryHash': 'd' * 64,
            'questions': ['synthetic/exr-manual'],
            'gradingPayloads': {'synthetic/exr-manual': {
                'uuid': '37d79ee7-fd7d-44db-bd45-6587711862a5',
                'grading': {'method': 'manual'}, 'submission': {'mode': 'upload'},
                'sourceRoot': 'projects/manual'}},
            'works': [{'id': 'unit'}],
            'instances': {'fixture': {'works': ['unit'], 'selfEnrollment': False}}, 'files': {}}
        self.assertEqual(delivery_verification.classification(delivery), {'synthetic/exr-manual': 'manual'})
        delivery['schemaVersion'] = 2
        with self.assertRaises(delivery_verification.JobError):
            delivery_verification.classification(delivery)
        self.assertEqual(receipt['images'], IMAGES)
        self.assertEqual(receipt['sourceCommit'], subprocess.check_output(
            ['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip())
        # Exercise the existing closed consumer against a separate release
        # assembly, with the declared generated lock at its existing path.
        spec = importlib.util.spec_from_file_location('publish_grading_job', ROOT / 'tools/grading_job.py')
        job = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(job)
        with tempfile.TemporaryDirectory(prefix='release-assembly-unit-') as name:
            assembly = Path(name)
            for path in ('runtime', 'schemas'):
                shutil.copytree(ROOT / path, assembly / path)
            for path in ('images/java25-grader/grade.py', 'images/fish-git-grader/grade.py'):
                target = assembly / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / path).read_bytes())
            lock = assembly / 'runtime/gradle-jar-v1/toolchain-lock.json'
            lock.write_bytes(files['published-toolchain-lock.json'])
            job.ROOT = assembly
            for name in registry['profiles']:
                self.assertTrue(job.runtime_evidence(name, registry)['dependencyHashes'])
            lock.unlink()
            with self.assertRaises((OSError, job.JobError)):
                job.runtime_evidence('java25-gradle-junit-v1', registry)
            lock.write_bytes((ROOT / 'runtime/gradle-jar-v1/toolchain-lock.json').read_bytes())
            with self.assertRaises(job.JobError):
                job.runtime_evidence('java25-gradle-junit-v1', registry)

    def test_wrong_repository_digest_is_refused(self):
        self.assert_refused({'JAVA_DIGEST': IMAGES['fish']})

    def test_local_image_id_is_not_a_published_digest(self):
        self.assert_refused({'JAVA_DIGEST': 'sha256:' + '1' * 64})

    def test_source_head_mismatch_is_refused(self):
        self.assert_refused({'GITHUB_SHA': 'f' * 40})

    def test_version_mismatch_is_refused(self):
        self.assert_refused({'VERSION': '2.2.0'})

    def changed_context(self, relative, change):
        self.require_context()
        path = ROOT / '.native-toolchain' / relative
        data = path.read_bytes()
        try:
            if change is None:
                path.unlink()
            else:
                path.write_bytes(change(data))
            self.assert_refused()
        finally:
            path.write_bytes(data)

    def test_missing_baked_view_is_refused(self):
        self.changed_context('runtime-profiles.json', None)

    def test_missing_fish_view_is_refused(self):
        self.changed_context('fish-runtime-profiles.json', None)

    def test_stale_fish_shared_schema_is_refused(self):
        def stale(data):
            value = json.loads(data)
            value['profiles']['fish-git-v1']['sharedFiles']['schemas/grading-descriptor.schema.json'] = '0' * 64
            return json.dumps(value).encode()
        self.changed_context('fish-runtime-profiles.json', stale)

    def test_stale_baked_runner_is_refused(self):
        self.changed_context('runtime-profiles.json', lambda b: b.replace(b'05aa5dfe', b'00000000'))

    def test_missing_native_profile_is_refused(self):
        def remove(data):
            value = json.loads(data)
            del value['profiles']['java25-gradle-junit-v1']
            return json.dumps(value).encode()
        self.changed_context('runtime-profiles.json', remove)

    def test_stale_prepared_source_is_refused(self):
        def stale(data):
            value = json.loads(data)
            value['source']['commit'] = 'f' * 40
            return json.dumps(value).encode()
        self.changed_context('context-manifest.json', stale)

    def test_wrong_generated_lock_is_refused(self):
        self.changed_context('operator/expected-toolchain-lock.json', lambda b: b + b' ')


if __name__ == '__main__':
    unittest.main()
