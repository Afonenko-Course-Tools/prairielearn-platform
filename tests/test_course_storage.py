"""Exercise exact Git transport and checkout over a temporary verified HTTPS server."""

from gradle_unit_fixtures import registry as unit_registry
import functools
import http.server
import importlib.util
import json
import os
import shutil
from pathlib import Path
import ssl
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "tools/stage_courses.py"


class CourseStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(SCRIPT.is_file(), "Course storage is not implemented")
        spec = importlib.util.spec_from_file_location("storage", SCRIPT)
        if spec is None or spec.loader is None:
            raise RuntimeError("Загрузчик локального Python-модуля недоступен")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "native.git"
        self.repo.mkdir()

        def git(*args: str) -> str:
            return subprocess.run(
                ["git", *args],
                cwd=self.repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

        self.git = git
        git("init", "-q")
        git("config", "user.name", "Synthetic")
        git("config", "user.email", "synthetic@example.test")
        (self.repo / "infoCourse.json").write_text(
            json.dumps(
                {
                    "uuid": "4174cd08-ddff-4006-81cc-d7a6b67d3ee0",
                    "name": "SYN",
                    "title": "Synthetic",
                    "timezone": "Europe/Minsk",
                    "topics": [
                        {
                            "name": "fixture",
                            "color": "gray1",
                            "description": "Synthetic",
                        }
                    ],
                }
            )
        )
        self.registry = unit_registry()
        for profile in self.registry["profiles"].values():
            profile["image"] = "synthetic@sha256:" + "a" * 64
        self.update_provenance()
        git("add", ".")
        git("commit", "-qm", "Native v1")
        self.first = git("rev-parse", "HEAD")
        git("update-server-info")
        cert = self.root / "cert.pem"
        key = self.root / "key.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=IP:127.0.0.1",
            ],
            check=True,
            capture_output=True,
        )

        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:
                pass

        self.server = http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), functools.partial(Quiet, directory=str(self.root))
        )
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        self.server.socket = ctx.wrap_socket(self.server.socket, server_side=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.env = patch.dict(
            os.environ, {"GIT_SSL_CAINFO": str(cert), "GIT_TERMINAL_PROMPT": "0"}
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.course = {
            "id": "course-a",
            "repository": f"https://127.0.0.1:{self.server.server_port}/native.git/.git",
            "commit": self.first,
            "mount": "/course",
        }
        self.storage = self.root / "storage"
        self.storage.mkdir()

    def update_provenance(self):
        from test_delivery5 import Delivery5

        helper = Delivery5()
        helper.setUp()
        try:
            info = (self.repo / "infoCourse.json").read_bytes()
            shutil.copytree(helper.root, self.repo, dirs_exist_ok=True)
            (self.repo / "infoCourse.json").write_bytes(info)
            (self.repo / "delivery.json").write_text(json.dumps(helper.d))
        finally:
            helper.doCleanups()

    def rename_course(self, name: str) -> None:
        p = self.repo / "infoCourse.json"
        value = json.loads(p.read_text())
        value["name"] = name
        p.write_text(json.dumps(value))

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def stage(self):
        return self.module.stage_course(self.course, self.storage)

    def test_exact_commit_checkout_and_repeat_are_stable(self) -> None:
        path = self.stage()
        self.assertEqual(path, self.storage / "course-a" / self.first)
        self.assertEqual(
            json.loads((path / "infoCourse.json").read_text())["name"], "SYN"
        )
        self.assertEqual(self.stage(), path)

    def test_upgrade_retains_previous_delivery(self) -> None:
        first = self.stage()
        self.rename_course("SYN2")
        self.update_provenance()
        self.git("add", ".")
        self.git("commit", "-qm", "Native v2")
        self.course["commit"] = self.git("rev-parse", "HEAD")
        self.git("update-server-info")
        second = self.stage()
        self.assertNotEqual(first, second)
        self.assertIn("SYN2", (second / "infoCourse.json").read_text())
        self.assertEqual(
            json.loads((first / "infoCourse.json").read_text())["name"], "SYN"
        )

    def test_dirty_existing_checkout_is_refused(self) -> None:
        path = self.stage()
        (path / "infoCourse.json").write_text("changed")
        with self.assertRaises(self.module.StorageError):
            self.stage()

    def test_symlink_git_metadata_is_refused_before_git_execution(self) -> None:
        path = self.stage()
        metadata = self.root / "external-git"
        shutil.move(path / ".git", metadata)
        (path / ".git").symlink_to(metadata)
        with patch.object(self.module, "git", wraps=self.module.git) as invoked:
            with self.assertRaises(self.module.StorageError):
                self.stage()
            invoked.assert_not_called()

    def test_nonexistent_commit_leaves_no_published_directory(self) -> None:
        self.course["commit"] = "f" * 40
        with self.assertRaises(self.module.StorageError):
            self.stage()
        self.assertFalse((self.storage / "course-a" / ("f" * 40)).exists())

    def test_symlink_payload_is_refused(self) -> None:
        (self.repo / "leak").symlink_to("/etc/hosts")
        self.git("add", ".")
        self.git("commit", "-qm", "Unsafe native")
        self.course["commit"] = self.git("rev-parse", "HEAD")
        self.git("update-server-info")
        with self.assertRaises(self.module.StorageError):
            self.stage()

    def test_two_course_ids_keep_separate_storage(self) -> None:
        first = self.stage()
        self.course["id"] = "course-b"
        self.course["mount"] = "/course2"
        second = self.stage()
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_dir())
        self.assertTrue(second.is_dir())

    def test_registry_upgrade_one_course_preserves_other_pin_and_payload(self) -> None:
        a = dict(self.course)
        b = dict(self.course, id="course-b", mount="/course2")
        registry = {"schema": "pl-courses-v1", "courses": [a, b]}
        images = self.module.builder.read_json(SCRIPT.parents[1] / "images.lock.json")
        first = self.module.stage_registry(registry, images, self.storage)
        original = (
            Path(first["services"]["pl"]["volumes"][0]["source"]) / "infoCourse.json"
        ).read_bytes()
        self.rename_course("SYN2")
        self.update_provenance()
        self.git("add", ".")
        self.git("commit", "-qm", "Only B upgraded")
        self.git("update-server-info")
        b["commit"] = self.git("rev-parse", "HEAD")
        second = self.module.stage_registry(registry, images, self.storage)
        self.assertEqual(
            first["services"]["pl"]["volumes"][0],
            second["services"]["pl"]["volumes"][0],
        )
        self.assertEqual(
            (
                Path(second["services"]["pl"]["volumes"][0]["source"])
                / "infoCourse.json"
            ).read_bytes(),
            original,
        )
        self.assertNotEqual(
            first["services"]["pl"]["volumes"][1]["source"],
            second["services"]["pl"]["volumes"][1]["source"],
        )
        self.assertTrue(Path(first["services"]["pl"]["volumes"][1]["source"]).exists())

    def test_symlink_storage_parent_is_refused(self) -> None:
        (self.storage / "course-a").symlink_to(self.repo)
        with self.assertRaises(self.module.StorageError):
            self.stage()

    def test_v2_institution_reference_survives_staging_and_repeat(self) -> None:
        catalog = {
            "schema": "pl-institutions-v1",
            "institutions": {
                "synthetic": {
                    "shortName": "SYN",
                    "longName": "Synthetic University",
                    "displayTimezone": "Europe/Minsk",
                    "uidRegexp": None,
                }
            },
        }
        course = {**self.course, "institution": "synthetic"}
        registry = {"schema": "pl-courses-v2", "courses": [course]}
        images = self.module.builder.read_json(SCRIPT.parents[1] / "images.lock.json")
        first = self.module.stage_registry(registry, images, self.storage, catalog)
        self.assertEqual(
            first, self.module.stage_registry(registry, images, self.storage, catalog)
        )
        self.assertTrue(Path(first["services"]["pl"]["volumes"][0]["source"]).is_dir())

    def test_unknown_institution_rejects_before_checkout(self) -> None:
        catalog = {
            "schema": "pl-institutions-v1",
            "institutions": {
                "synthetic": {
                    "shortName": "SYN",
                    "longName": "Synthetic University",
                    "displayTimezone": "Europe/Minsk",
                    "uidRegexp": None,
                }
            },
        }
        registry = {
            "schema": "pl-courses-v2",
            "courses": [{**self.course, "institution": "unknown"}],
        }
        images = self.module.builder.read_json(SCRIPT.parents[1] / "images.lock.json")
        with patch.object(self.module, "git", wraps=self.module.git) as invoked:
            with self.assertRaises(self.module.RegistryError):
                self.module.stage_registry(registry, images, self.storage, catalog)
            invoked.assert_not_called()
