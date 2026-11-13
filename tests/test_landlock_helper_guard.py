"""Source guard regression; mocked container facts не доказывают изоляцию."""

import os
import shutil
from collections.abc import Iterator, Sequence
from typing import Protocol, runtime_checkable
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from test_grading_job import grader


@runtime_checkable
class _NativeContainment(Protocol):
    def __call__(
        self, job: Path, private_paths: Sequence[Path]
    ) -> tuple[int, list[str]]: ...


class InstalledHelperGuardTests(unittest.TestCase):
    def test_unmatched_installed_helper_refuses_before_first_child(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            job = Path(temporary)
            for name in ("student", "tests"):
                (job / name).mkdir()
            real_iterdir = Path.iterdir

            def directories(path: Path) -> Iterator[Path]:
                return (
                    iter([Path("/sys/class/net/lo")])
                    if path == Path("/sys/class/net")
                    else real_iterdir(path)
                )

            containment: object = getattr(grader, "_native_containment")
            if not isinstance(containment, _NativeContainment):
                raise RuntimeError("Контракт локального native containment недоступен")
            with (
                patch.dict(os.environ, PL_CONTAINMENT="official"),
                patch.object(os, "geteuid", return_value=0),
                patch.object(Path, "is_file", return_value=True),
                patch.object(Path, "iterdir", directories),
                patch.object(shutil, "which", return_value="/usr/sbin/runuser"),
                patch.object(grader, "_protect_input_identity"),
                patch("pwd.getpwnam", return_value=SimpleNamespace(pw_uid=1001)),
                patch.object(grader, "_run", return_value=(0, "1001\n", None)) as child,
            ):
                with self.assertRaisesRegex(grader.GraderError, "Landlock helper"):
                    containment(job, [])
                child.assert_not_called()
