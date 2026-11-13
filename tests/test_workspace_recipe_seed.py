"""Реальный Git seed: настройки recipe, учебный текст commit и произвольные файлы."""

import io
from collections.abc import Callable, Mapping
from typing import Protocol
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from delivery4 import seed_proof  # noqa: E402 — import after the local test/tool path bootstrap
from grading_job import JobError  # noqa: E402 — import after the local test/tool path bootstrap
from delivery_types import SeedProof  # noqa: E402 — import after the local test/tool path bootstrap


class GitCommand(Protocol):
    def __call__(self, *args: str) -> subprocess.CompletedProcess[bytes]: ...


class RecipeSeed(unittest.TestCase):
    def fixture(
        self,
        files: Mapping[str, bytes],
        *,
        second_commit: bool = False,
        index_version: int | None = None,
        packed: bool = False,
        change: Callable[[GitCommand, Path], None] | None = None,
    ) -> tuple[Path, dict[str, bytes]]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        work = root / "work"
        work.mkdir()
        template = root / "empty-template"
        template.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")

        def git(*args: str) -> subprocess.CompletedProcess[bytes]:
            return subprocess.run(
                [
                    "git",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "core.fsmonitor=false",
                    "-c",
                    "maintenance.auto=false",
                    "-c",
                    "gc.auto=0",
                    "-c",
                    "user.name=Fixture",
                    "-c",
                    "user.email=fixture@example.invalid",
                    *args,
                ],
                cwd=work,
                env=env,
                capture_output=True,
                check=True,
                timeout=20,
            )

        git(
            "init",
            "-q",
            "--initial-branch=main",
            "--object-format=sha1",
            "--template=" + str(template),
        )
        git("config", "core.autocrlf", "false")
        for name, data in files.items():
            (work / name).write_bytes(data)
        git("add", ".")
        git("commit", "-qm", "Начальное состояние учебного проекта")
        if second_commit:
            name = next(iter(files))
            (work / name).write_bytes(files[name] + b"next\n")
            git("commit", "-qam", "Второе состояние")
        if index_version is not None:
            git("update-index", "--index-version=" + str(index_version))
        if packed:
            git("repack", "-ad")
        if change is not None:
            change(git, work)
        entries: dict[str, bytes] = {}
        for path in work.rglob("*"):
            if not path.is_file():
                continue
            name = path.relative_to(work).as_posix()
            if name.startswith(".git/") and not (
                name
                in (".git/HEAD", ".git/config", ".git/index", ".git/refs/heads/main")
                or name.startswith(".git/objects/")
            ):
                continue
            entries["work/" + name] = path.read_bytes()
        return root, entries

    def proof(
        self,
        root: Path,
        entries: Mapping[str, bytes],
        *,
        zip_modes: Mapping[str, int] | None = None,
    ) -> SeedProof:
        native = root / "native"
        prefix = "questions/fixture/exr-seed/"
        question = native / prefix
        question.mkdir(parents=True)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for name, data in sorted(entries.items()):
                member = zipfile.ZipInfo(name)
                member.external_attr = ((zip_modes or {}).get(name, 0o100644)) << 16
                archive.writestr(member, data)
                if "/.git/" not in "/" + name:
                    path = question / "clientFilesQuestion/starter" / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
        raw = stream.getvalue()
        manifest = json.dumps(
            {
                "schema": "pl-git-workspace-seed-v1",
                "files": sorted(entries),
            }
        ).encode()
        for name, data in [
            ("workspace/.pl-seed/starter.zip", raw),
            ("workspace/.pl-seed/manifest.json", manifest),
            ("clientFilesQuestion/starter.zip", raw),
        ]:
            path = question / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        payload = {
            "seed": {
                "schema": "pl-git-workspace-seed-v1",
                "archive": "workspace/.pl-seed/starter.zip",
                "manifest": "workspace/.pl-seed/manifest.json",
            }
        }
        return seed_proof(native, prefix, payload)

    def test_recipe_autocrlf_false_and_authored_commit_message(self) -> None:
        root, entries = self.fixture(
            {"README.md": "Учебный проект\n".encode(), "notes.txt": b"notes\n"}
        )
        self.proof(root, entries)

    def test_initial_tree_does_not_require_specific_filenames(self) -> None:
        root, entries = self.fixture({"catalog.tsv": b"name\tvalue\nA\t1\n"})
        self.proof(root, entries)

    def test_git_native_packed_objects_and_index_v4(self) -> None:
        root, entries = self.fixture(
            {"notes.txt": b"notes\n", "notes-other.txt": b"other\n"},
            index_version=4,
            packed=True,
        )
        self.proof(root, entries)

    def test_git_environment_does_not_select_another_repository(self) -> None:
        root, entries = self.fixture({"notes.txt": b"notes\n"})
        with patch.dict(
            os.environ,
            {
                "GIT_DIR": "/missing",
                "GIT_WORK_TREE": "/missing",
                "GIT_INDEX_FILE": "/missing",
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "core.fsmonitor",
                "GIT_CONFIG_VALUE_0": "/missing",
            },
        ):
            self.proof(root, entries)

    def test_changed_and_untracked_worktree_files_are_rejected(self) -> None:
        for tracked in (True, False):
            with self.subTest(tracked=tracked):
                root, entries = self.fixture({"notes.txt": b"notes\n"})
                entries["work/" + ("notes.txt" if tracked else "solution.txt")] = (
                    b"changed\n"
                )
                with self.assertRaises(JobError):
                    self.proof(root, entries)

    def test_object_at_size_limit_remains_usable(self) -> None:
        root, entries = self.fixture({"notes.txt": b"A" * (8 * 1024**2)}, packed=True)
        self.proof(root, entries)

    def test_large_compressed_objects_are_rejected_before_content_checks(self) -> None:
        for packed in (False, True):
            for unreachable in (False, True):
                with self.subTest(packed=packed, unreachable=unreachable):

                    def change(git: GitCommand, work: Path) -> None:
                        if unreachable:  # noqa: B023 — mock is consumed synchronously inside this loop iteration
                            (work / "notes.txt").write_bytes(b"public\n")
                            git("add", "notes.txt")
                            git("commit", "--amend", "--no-edit", "-q")
                        if packed:  # noqa: B023 — mock is consumed synchronously inside this loop iteration
                            git("repack", "-ad")

                    root, entries = self.fixture(
                        {"notes.txt": b"A" * (9 * 1024**2)}, change=change
                    )
                    entries["work/notes.txt"] = b"public\n"
                    with self.assertRaisesRegex(
                        JobError, "Git object size bound exceeded"
                    ):
                        self.proof(root, entries)

    def test_missing_git_object_is_rejected(self) -> None:
        root, entries = self.fixture({"notes.txt": b"notes\n"})
        del entries[next(n for n in entries if n.startswith("work/.git/objects/"))]
        with self.assertRaises(JobError):
            self.proof(root, entries)

    def test_corrupt_git_object_is_rejected(self) -> None:
        root, entries = self.fixture({"notes.txt": b"notes\n"})
        name = next(n for n in entries if n.startswith("work/.git/objects/"))
        entries[name] = b"corrupt object"
        with self.assertRaises(JobError):
            self.proof(root, entries)

    def test_external_git_state_is_rejected(self) -> None:
        for name in ("commondir", "objects/info/alternates", "info/grafts", "shallow"):
            with self.subTest(name=name):
                root, entries = self.fixture({"notes.txt": b"notes\n"})
                entries["work/.git/" + name] = b"/missing\n"
                with self.assertRaises(JobError):
                    self.proof(root, entries)

    def test_object_outside_initial_tree_is_rejected(self) -> None:
        def extra_object(git: GitCommand, work: Path) -> None:
            path = work.parent / "private-solution"
            path.write_bytes(b"private solution\n")
            git("hash-object", "-w", str(path))

        root, entries = self.fixture({"notes.txt": b"notes\n"}, change=extra_object)
        with self.assertRaises(JobError):
            self.proof(root, entries)

    def test_git_symlink_tree_is_rejected(self) -> None:
        def symlink(git: GitCommand, work: Path) -> None:
            (work / "link").symlink_to("notes.txt")
            git("add", "link")
            git("commit", "--amend", "--no-edit", "-q")

        root, entries = self.fixture({"notes.txt": b"notes\n"}, change=symlink)
        with self.assertRaises(JobError):
            self.proof(root, entries)

    def test_zip_symlink_and_traversal_are_rejected(self) -> None:
        for name, mode in [("work/link", 0o120777), ("../outside", 0o100644)]:
            with self.subTest(name=name):
                root, entries = self.fixture({"notes.txt": b"notes\n"})
                entries[name] = b"notes.txt"
                with self.assertRaises(JobError):
                    self.proof(root, entries, zip_modes={name: mode})

    def test_unsafe_config_remains_rejected(self) -> None:
        for change in ("true", "input", "fsmonitor"):
            with self.subTest(change=change):
                root, entries = self.fixture(
                    {"README.md": b"fixture\n", "notes.txt": b"notes\n"}
                )
                config = entries["work/.git/config"]
                entries["work/.git/config"] = (
                    config + b"\tfsmonitor = true\n"
                    if change == "fsmonitor"
                    else config.replace(
                        b"autocrlf = false", b"autocrlf = " + change.encode()
                    )
                )
                with self.assertRaises(JobError):
                    self.proof(root, entries)

    def test_workspace_history_still_requires_one_initial_commit(self) -> None:
        root, entries = self.fixture(
            {"README.md": b"fixture\n", "notes.txt": b"notes\n"}, second_commit=True
        )
        with self.assertRaises(JobError):
            self.proof(root, entries)


if __name__ == "__main__":
    unittest.main()
