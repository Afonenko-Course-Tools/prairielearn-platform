"""Builder uses installed full exporter and preserves fresh candidate semantics."""

from gradle_unit_fixtures import write_registry as unit_registry_file
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("builder", ROOT / "tools/build-course.py")
if spec is None or spec.loader is None:
    raise RuntimeError("Загрузчик локального Python-модуля недоступен")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class BuilderContract(unittest.TestCase):
    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / "source"
            source.mkdir()
            out = root / "out"
            out.mkdir()
            (out / "sentinel").write_text("keep")
            with self.assertRaises(builder.BuildError):
                builder.build_course(
                    source,
                    "tasks",
                    "pilot",
                    out,
                    runtime_registry=unit_registry_file(root),
                )
            self.assertEqual((out / "sentinel").read_text(), "keep")

    def test_old_shell_exporter_cannot_build(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / "source"
            source.mkdir()
            for cmd in [
                ["git", "init", "-q"],
                ["git", "config", "user.name", "Synthetic"],
                ["git", "config", "user.email", "synthetic@example.test"],
                ["git", "remote", "add", "origin", "https://example.test/source.git"],
            ]:
                subprocess.run(cmd, cwd=source, check=True)
            p = source / "tasks/_extensions/course-prairielearn/entrypoints/export.ts"
            p.parent.mkdir(parents=True)
            p.write_text("// old exporter")
            subprocess.run(["git", "add", "."], cwd=source, check=True)
            subprocess.run(["git", "commit", "-qm", "Fixture"], cwd=source, check=True)
            with self.assertRaises(builder.BuildError):
                builder.build_course(
                    source,
                    "tasks",
                    "pilot",
                    root / "out",
                    runtime_registry=unit_registry_file(root),
                )
            self.assertFalse((root / "out").exists())

    def test_atomic_publication_does_not_overwrite_concurrent_directory(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / "from"
            source.mkdir()
            target = root / "target"
            target.mkdir()
            (target / "keep").write_text("keep")
            with self.assertRaises(builder.BuildError):
                builder.publish_directory(source, target)
            self.assertEqual((target / "keep").read_text(), "keep")

    def test_full_exporter_copies_native_and_private_checks_without_receipts(self):
        import test_build_course_launch as launch

        helper = launch.LaunchContract()
        helper.setUp()
        try:
            helper.run_spy = helper.emit_package
            helper.call(export_stage=helper.stage)
            self.assertTrue((helper.output / "delivery.json").is_file())
            self.assertFalse((helper.output / "provenance.json").exists())
            private = helper.output.with_name(helper.output.name + "-checks.json")
            self.assertTrue(private.is_file())
            self.assertEqual(private.stat().st_mode & 0o777, 0o600)
            self.assertFalse((helper.output / "checks.json").exists())
        finally:
            helper.doCleanups()
