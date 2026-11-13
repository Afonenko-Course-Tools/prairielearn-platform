"""Копирование upstream schemas и проверка актуальности без SHA manifest."""

import pathlib, shutil, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
NAMES = [
    "infoCourse.json",
    "infoCourseInstance.json",
    "infoAssessment.json",
    "infoQuestion.json",
    "PRAIRIELEARN-LICENSE",
    "provenance.json",
]


class VendorSchemas(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="schema-vendor-")
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.provider = self.root / "provider"
        self.provider.mkdir()
        self.base = self.provider / "_extensions/course-prairielearn/spec/upstream"
        self.base.mkdir(parents=True)
        for name in NAMES:
            shutil.copyfile(ROOT / "schemas/native-upstream" / name, self.base / name)
        self.git("init", "-q")
        self.git("remote", "add", "origin", "https://example.invalid/fixture.git")
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "Fixture schemas",
        )
        script = self.root / "platform/tools/vendor-native-schemas.py"
        script.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / "tools/vendor-native-schemas.py", script)
        self.script = script
        self.target = script.parents[1] / "schemas/native-upstream"

    def git(self, *args: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            ["git", *args],
            cwd=self.provider,
            capture_output=True,
            check=True,
            timeout=10,
        )

    def vendor(self, *args: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [
                sys.executable,
                "-B",
                str(self.script),
                "--exporter",
                str(self.provider),
                *args,
            ],
            capture_output=True,
            timeout=10,
        )

    def test_copy_and_check_use_actual_schema_files_without_manifest(self):
        result = self.vendor()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(p.name for p in self.target.iterdir()), sorted(NAMES))
        for name in NAMES:
            self.assertEqual(
                (self.target / name).read_bytes(), (self.base / name).read_bytes()
            )
        self.assertEqual(self.vendor("--check").returncode, 0)
        (self.target / "infoCourse.json").write_text("{}")
        result = self.vendor("--check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"Stale generated native schema", result.stderr)

    def test_uncommitted_provider_schema_is_rejected(self):
        (self.base / "infoCourse.json").write_text("{}")
        result = self.vendor()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"differs from committed provider", result.stderr)


if __name__ == "__main__":
    unittest.main()
