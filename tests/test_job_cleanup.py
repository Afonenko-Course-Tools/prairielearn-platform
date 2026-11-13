"""Очистка приватного scratch без настоящего запуска контейнеров."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractContextManager
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from typing import TypeGuard
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import grading_job as jobs
from json_boundary import is_object
from test_selected_file_delivery import manifest, row
from gradle_unit_fixtures import registry

IMAGE = "sha256:" + "d" * 64


def completed(
    code: int, stderr: str = "", stdout: str = ""
) -> subprocess.CompletedProcess[str]:
    # capture_output=True/text=True возвращает оба стандартных stream-поля.
    return subprocess.CompletedProcess(["docker"], code, stdout=stdout, stderr=stderr)


def _raw_result(value: object) -> TypeGuard[dict[str, object]]:
    return is_object(value) and all(isinstance(key, str) for key in value)


def raw_result(value: object) -> dict[str, object]:
    # Частичный mock не обещает валидный CheckResult; сохраняем исходный объект.
    if not _raw_result(value):
        raise AssertionError("Ожидался объект результата mock")
    return value


class JobCleanup(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.manifest = manifest()
        self.registry = registry()
        self.registry["profiles"]["java25-junit-v1"]["image"] = IMAGE

    def prepare(self, public: bool = False) -> jobs.GradingJob:
        if public:
            self.manifest["projects"][0]["verificationTests"] = [
                row("PublicTest.java", b"public")
            ]
        job = jobs.prepare_job(
            self.manifest,
            Path(self.temp),
            "demo/exr-answer",
            "starter",
            registry=self.registry,
        )
        self.addCleanup(
            lambda: (
                shutil.rmtree(job.root)
                if job.root.exists() and not job.root.is_symlink()
                else None
            )
        )
        return job

    def execute(
        self,
        job: jobs.GradingJob,
        outcomes: Sequence[subprocess.CompletedProcess[str] | Exception] | None = None,
    ) -> dict[str, object]:
        pending = iter(outcomes or [completed(0, stderr="")])

        def run(
            command: Sequence[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            outcome = next(pending)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        with (
            patch.object(jobs, "validate"),
            patch.object(
                jobs, "_junit_result_helpers", return_value={"unique_json_object": dict}
            ),
            patch.object(jobs.subprocess, "run", side_effect=run),
        ):
            for root in [job.root, job.root / "public-verification"]:
                if root.is_dir():
                    (root / "results").mkdir()
                    (root / "results/results.json").write_text(
                        json.dumps({"infrastructure": "complete", "score": 1})
                    )
            return raw_result(jobs.run_job(job, "container", self.registry))

    def test_permission_fallback_uses_only_prepared_mount_and_exact_image(self) -> None:
        job = self.prepare()
        self.execute(job)
        with (
            patch.object(jobs.secrets, "token_hex", return_value="f" * 24),
            patch.object(
                jobs.shutil,
                "rmtree",
                side_effect=[PermissionError("mixed owner"), None],
            ) as remove,
            patch.object(
                jobs.subprocess, "run", return_value=completed(0, stderr="")
            ) as run,
        ):
            jobs.cleanup_job(job, "container")
        self.assertEqual(remove.call_count, 2)
        self.assertEqual(
            run.call_args.args[0],
            [
                "docker",
                "run",
                "--rm",
                "--name",
                "plcleanup-" + "f" * 24,
                "--network",
                "none",
                "--read-only",
                "--entrypoint",
                "/bin/chown",
                "--mount",
                f"type=bind,src={job.root},dst=/grade,bind-recursive=disabled",
                IMAGE,
                "-Rh",
                f"{os.getuid()}:{os.getgid()}",
                "/grade",
            ],
        )
        self.assertEqual(
            run.call_args.kwargs, {"capture_output": True, "text": True, "timeout": 10}
        )

    def test_replaced_root_after_ownership_command_blocks_second_deletion(self) -> None:
        job = self.prepare()
        self.execute(job)
        original = job.root.with_name(job.root.name + "-original")

        def chown(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
            job.root.rename(original)
            job.root.mkdir()
            self.addCleanup(lambda: shutil.rmtree(original))
            return completed(0, stderr="")

        with (
            patch.object(
                jobs.shutil, "rmtree", side_effect=[PermissionError(), None]
            ) as remove,
            patch.object(jobs.subprocess, "run", side_effect=chown),
        ):
            with self.assertRaises(jobs.JobError):
                jobs.cleanup_job(job, "container")
            self.assertEqual(remove.call_count, 1)

    def test_ordinary_cleanup_and_host_or_nonpermission_failures_never_run_docker(
        self,
    ) -> None:
        job = self.prepare()
        for backend, error in [
            ("container", None),
            ("host", PermissionError()),
            ("container", OSError("io")),
        ]:
            with (
                self.subTest(backend=backend, error=error),
                patch.object(jobs.shutil, "rmtree", side_effect=error),
                patch.object(jobs.subprocess, "run") as run,
            ):
                if error:
                    with self.assertRaises(OSError):
                        jobs.cleanup_job(job, backend)
                else:
                    jobs.cleanup_job(job, backend)
                run.assert_not_called()

    def test_unknown_live_failed_timeout_and_public_child_block_all_deletion(
        self,
    ) -> None:
        timeout = subprocess.TimeoutExpired("docker", 1)
        for public, outcomes in [
            (False, [OSError("unknown")]),
            (False, [timeout, completed(1, stderr="denied")]),
            (False, [timeout, timeout]),
            (True, [completed(0, stderr=""), timeout, completed(1, stderr="denied")]),
        ]:
            with self.subTest(public=public, outcomes=outcomes):
                job = self.prepare(public)
                self.execute(job, outcomes)
                with patch.object(
                    jobs, "validate", side_effect=jobs.JobError("invalid retry")
                ):
                    with self.assertRaises(jobs.JobError):
                        jobs.run_job(job, "container", self.registry)
                with (
                    patch.object(jobs.shutil, "rmtree") as remove,
                    patch.object(jobs.subprocess, "run") as run,
                ):
                    with self.assertRaises(jobs.JobError):
                        jobs.cleanup_job(job, "container")
                    remove.assert_not_called()
                    run.assert_not_called()

    def test_retry_after_failed_container_removal_cannot_forget_live_container(
        self,
    ) -> None:
        job = self.prepare()
        self.execute(
            job, [subprocess.TimeoutExpired("docker", 1), completed(1, stderr="denied")]
        )
        original_name = job.containerName
        with (
            patch.object(jobs, "validate"),
            patch.object(
                jobs.subprocess, "run", return_value=completed(0, stderr="")
            ) as run,
            patch.object(jobs.secrets, "token_hex") as name,
        ):
            with self.assertRaises(jobs.JobError):
                jobs.run_job(job, "container", self.registry)
            run.assert_not_called()
            name.assert_not_called()
        self.assertEqual(job.containerName, original_name)
        stopped: object = getattr(job, "_containers_stopped")
        if type(stopped) is not bool:
            raise AssertionError("Приватное состояние остановки должно быть bool")
        self.assertFalse(stopped)
        with patch.object(jobs.shutil, "rmtree") as remove:
            with self.assertRaises(jobs.JobError):
                jobs.cleanup_job(job, "container")
            remove.assert_not_called()

    def test_safe_unlaunched_cleanup_needs_no_image_or_mount_csv(self) -> None:
        for backend in ["container", "host"]:
            with self.subTest(backend=backend):
                self.registry["profiles"]["java25-junit-v1"]["image"] = ""
                parent = Path(self.temp) / ("comma," + backend)
                parent.mkdir()
                with patch.object(tempfile, "tempdir", str(parent)):
                    job = self.prepare()
                with (
                    patch.object(jobs.shutil, "rmtree") as remove,
                    patch.object(jobs.subprocess, "run") as run,
                ):
                    jobs.cleanup_job(job, backend)
                    remove.assert_called_once_with(job.root)
                    run.assert_not_called()

    def test_host_completion_allows_ordinary_cleanup_without_docker(self) -> None:
        job = self.prepare(public=True)
        delattr(job, "_containers_stopped")

        def grade(root: Path, **kwargs: object) -> dict[str, object]:
            return {"infrastructure": "complete", "score": 1}

        def exec_module(module: object) -> None:
            return None

        grader = SimpleNamespace(grade=grade)
        spec = SimpleNamespace(loader=SimpleNamespace(exec_module=exec_module))
        with (
            patch.object(jobs, "validate"),
            patch.object(
                jobs.importlib.util, "spec_from_file_location", return_value=spec
            ),
            patch.object(jobs.importlib.util, "module_from_spec", return_value=grader),
            patch.object(jobs.subprocess, "run") as run,
        ):
            self.assertEqual(
                jobs.run_job(job, "host", self.registry)["infrastructure"], "complete"
            )
            with patch.object(jobs.shutil, "rmtree") as remove:
                jobs.cleanup_job(job, "host")
                remove.assert_called_once_with(job.root)
            run.assert_not_called()

    def test_validation_or_missing_image_before_launch_allows_cleanup(self) -> None:
        for failure in ["validation", "image"]:
            with self.subTest(failure=failure):
                job = self.prepare()
                if failure == "image":
                    job["imageDigest"] = ""
                with (
                    patch.object(
                        jobs,
                        "validate",
                        side_effect=jobs.JobError("invalid")
                        if failure == "validation"
                        else None,
                    ),
                    patch.object(jobs.subprocess, "run") as run,
                ):
                    if failure == "validation":
                        with self.assertRaises(jobs.JobError):
                            jobs.run_job(job, "container", self.registry)
                    else:
                        self.assertEqual(
                            jobs.run_job(job, "container", self.registry)[
                                "infrastructure"
                            ],
                            "failure",
                        )
                    run.assert_not_called()
                with patch.object(jobs.shutil, "rmtree") as remove:
                    jobs.cleanup_job(job, "container")
                    remove.assert_called_once_with(job.root)

    def test_successful_timeout_removal_allows_fallback(self) -> None:
        job = self.prepare()
        self.execute(
            job, [subprocess.TimeoutExpired("docker", 1), completed(0, stderr="")]
        )
        with (
            patch.object(jobs.shutil, "rmtree", side_effect=[PermissionError(), None]),
            patch.object(
                jobs.subprocess, "run", return_value=completed(0, stderr="")
            ) as run,
        ):
            jobs.cleanup_job(job, "container")
            run.assert_called_once()

    def test_public_completion_allows_fallback_only_after_child_finishes(self) -> None:
        job = self.prepare(public=True)
        observed: list[Path] = []

        def run(
            command: Sequence[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            # Любое удаление во время grading-фазы запрещено.
            with patch.object(jobs.shutil, "rmtree") as remove:
                with self.assertRaises(jobs.JobError):
                    jobs.cleanup_job(job, "container")
                remove.assert_not_called()
            root = job.root if not observed else job.root / "public-verification"
            (root / "results").mkdir()
            (root / "results/results.json").write_text(
                '{"infrastructure":"complete","score":1}'
            )
            observed.append(root)
            return completed(0, stderr="")

        with (
            patch.object(jobs, "validate"),
            patch.object(
                jobs, "_junit_result_helpers", return_value={"unique_json_object": dict}
            ),
            patch.object(jobs.subprocess, "run", side_effect=run),
        ):
            result = jobs.run_job(job, "container", self.registry)
        self.assertEqual(raw_result(raw_result(result)["publicResult"])["score"], 1)
        self.assertEqual(observed, [job.root, job.root / "public-verification"])
        with (
            patch.object(jobs.shutil, "rmtree", side_effect=[PermissionError(), None]),
            patch.object(
                jobs.subprocess, "run", return_value=completed(0, stderr="")
            ) as cleanup,
        ):
            jobs.cleanup_job(job, "container")
            cleanup.assert_called_once()

    def test_changed_root_symlink_owner_uid_image_or_unprepared_path_is_rejected(
        self,
    ) -> None:
        for change in [
            "root",
            "inode",
            "symlink",
            "owner",
            "uid",
            "image",
            "unprepared",
        ]:
            with self.subTest(change=change):
                job = self.prepare()
                self.execute(job)
                contexts: list[AbstractContextManager[object]] = []
                if change == "root":
                    original = job.root
                    job.root = Path(self.temp)
                    self.addCleanup(setattr, job, "root", original)
                elif change == "inode":
                    original = job.root.with_name(job.root.name + "-original")
                    job.root.rename(original)
                    job.root.mkdir()
                    self.addCleanup(shutil.rmtree, original)
                elif change == "symlink":
                    original = job.root
                    link = Path(self.temp) / "link"
                    link.symlink_to(original)
                    self.addCleanup(link.unlink)
                    job.root = link
                    self.addCleanup(setattr, job, "root", original)
                elif change == "owner":
                    real = Path.lstat

                    def other_owner(path: Path) -> SimpleNamespace:
                        return SimpleNamespace(
                            st_dev=real(path).st_dev,
                            st_ino=real(path).st_ino,
                            st_uid=os.getuid() + 1,
                            st_mode=real(path).st_mode,
                        )

                    contexts.append(patch.object(Path, "lstat", other_owner))
                elif change == "uid":
                    contexts.append(
                        patch.object(jobs.os, "getuid", return_value=os.getuid() + 1)
                    )
                elif change == "image":
                    job["imageDigest"] = "sha256:" + "e" * 64
                else:
                    replacement = jobs.GradingJob(job)
                    replacement.root = job.root
                    job = replacement
                from contextlib import ExitStack

                with ExitStack() as stack:
                    for context in contexts:
                        stack.enter_context(context)
                    remove = stack.enter_context(
                        patch.object(
                            jobs.shutil,
                            "rmtree",
                            side_effect=PermissionError()
                            if change == "image"
                            else None,
                        )
                    )
                    run = stack.enter_context(patch.object(jobs.subprocess, "run"))
                    with self.assertRaises((jobs.JobError, PermissionError)):
                        jobs.cleanup_job(job, "container")
                    if change != "image":
                        remove.assert_not_called()
                    run.assert_not_called()

    def test_mount_csv_separator_in_prepared_scratch_is_rejected(self) -> None:
        parent = Path(self.temp) / "comma,parent"
        parent.mkdir()
        with patch.object(tempfile, "tempdir", str(parent)):
            job = self.prepare()
        self.execute(job)
        with (
            patch.object(jobs.shutil, "rmtree", side_effect=PermissionError()),
            patch.object(jobs.subprocess, "run") as run,
        ):
            with self.assertRaises(jobs.JobError):
                jobs.cleanup_job(job, "container")
            run.assert_not_called()

    def test_chown_failure_timeout_or_retry_failure_is_not_ignored(self) -> None:
        for outcome in [
            completed(1, stderr="unsupported bind-recursive"),
            subprocess.TimeoutExpired("docker", 10),
            completed(0, stderr=""),
        ]:
            job = self.prepare()
            self.execute(job)
            with (
                patch.object(jobs.shutil, "rmtree", side_effect=PermissionError()),
                patch.object(
                    jobs.subprocess,
                    "run",
                    side_effect=outcome if isinstance(outcome, Exception) else None,
                    return_value=outcome,
                ),
            ):
                with self.assertRaises((jobs.JobError, OSError)):
                    jobs.cleanup_job(job, "container")

    def test_ownership_timeout_removes_only_its_named_container_without_retrying_rmtree(
        self,
    ) -> None:
        cases = [
            (completed(0, stderr=""), "timed out; container removed"),
            (completed(1, stderr="No such container"), "timed out; container removed"),
            (completed(1, stderr="denied"), "container cleanup failed: denied"),
            (subprocess.TimeoutExpired("docker rm", 10), "container cleanup failed"),
            (OSError("daemon unavailable"), "container cleanup failed"),
        ]
        for removal, message in cases:
            with self.subTest(removal=removal):
                job = self.prepare()
                self.execute(job)
                with (
                    patch.object(jobs.secrets, "token_hex", return_value="a" * 24),
                    patch.object(
                        jobs.shutil, "rmtree", side_effect=PermissionError()
                    ) as remove,
                    patch.object(
                        jobs.subprocess,
                        "run",
                        side_effect=[
                            subprocess.TimeoutExpired("docker run", 10),
                            removal,
                        ],
                    ) as run,
                ):
                    with self.assertRaisesRegex(jobs.JobError, message):
                        jobs.cleanup_job(job, "container")
                self.assertEqual(remove.call_count, 1)
                self.assertEqual(run.call_count, 2)
                command = run.call_args_list[0].args[0]
                self.assertEqual(
                    command[command.index("--name") + 1], "plcleanup-" + "a" * 24
                )
                self.assertEqual(
                    run.call_args_list[1].args[0],
                    ["docker", "rm", "--force", "plcleanup-" + "a" * 24],
                )
                self.assertEqual(
                    run.call_args_list[1].kwargs,
                    {"capture_output": True, "text": True, "timeout": 10},
                )

    def test_cli_retains_results_on_ownership_command_failure_or_timeout(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "cleanup_failure_cli", jobs.ROOT / "tools/check-course.py"
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Загрузчик локального Python-модуля недоступен")
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        root = Path(self.temp)
        source = root / "manifest.json"
        source.write_text(json.dumps(self.manifest))
        output = root / "report.json"
        for outcome in [
            completed(1, stderr="unsupported bind-recursive"),
            subprocess.TimeoutExpired("docker", 10),
        ]:
            with self.subTest(outcome=outcome):
                job = self.prepare()
                self.execute(job)
                result = {"score": 1, "publicResult": {"score": 1}}
                with (
                    patch.object(
                        sys,
                        "argv",
                        [
                            "check-course.py",
                            "--manifest",
                            str(source),
                            "--output",
                            str(output),
                        ],
                    ),
                    patch.object(cli, "prepare_job", return_value=job),
                    patch.object(cli, "run_job", return_value=result),
                    patch.object(cli, "preserve_build_logs"),
                    patch.object(jobs.shutil, "rmtree", side_effect=PermissionError()),
                    patch.object(
                        jobs.subprocess,
                        "run",
                        side_effect=outcome if isinstance(outcome, Exception) else None,
                        return_value=outcome,
                    ),
                ):
                    self.assertEqual(cli.main(), 2)
                report = raw_result(json.loads(output.read_text()))
                self.assertEqual(report["results"], [result])
                self.assertEqual(report["classification"], "infrastructure-failure")

    def test_cli_retains_results_and_logs_before_cleanup_failure(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "cleanup_cli", jobs.ROOT / "tools/check-course.py"
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Загрузчик локального Python-модуля недоступен")
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        root = Path(self.temp)
        source = root / "manifest.json"
        source.write_text(json.dumps(self.manifest))
        output = root / "report.json"
        job = self.prepare()
        observed: list[str] = []
        result: dict[str, object] = {"score": 1, "publicResult": {"score": 1}}

        def execute(*args: object) -> dict[str, object]:
            observed.append("run-public-complete")
            return result

        def preserve_logs(*args: object) -> None:
            observed.append("logs")

        with (
            patch.object(
                sys,
                "argv",
                ["check-course.py", "--manifest", str(source), "--output", str(output)],
            ),
            patch.object(cli, "prepare_job", return_value=job),
            patch.object(cli, "run_job", side_effect=execute),
            patch.object(cli, "preserve_build_logs", side_effect=preserve_logs),
            patch.object(
                jobs.shutil, "rmtree", side_effect=PermissionError("mixed owner")
            ),
            patch.object(
                jobs.subprocess, "run", side_effect=OSError("daemon unavailable")
            ) as ownership,
        ):
            self.assertEqual(cli.main(), 2)
        ownership.assert_called_once()
        command = ownership.call_args.args[0]
        self.assertRegex(command[4], r"^plcleanup-[0-9a-f]{24}$")
        self.assertEqual(
            command,
            [
                "docker",
                "run",
                "--rm",
                "--name",
                command[4],
                "--network",
                "none",
                "--read-only",
                "--entrypoint",
                "/bin/chown",
                "--mount",
                f"type=bind,src={job.root},dst=/grade,bind-recursive=disabled",
                IMAGE,
                "-Rh",
                f"{os.getuid()}:{os.getgid()}",
                "/grade",
            ],
        )
        self.assertEqual(
            ownership.call_args.kwargs,
            {"capture_output": True, "text": True, "timeout": 10},
        )
        report = raw_result(json.loads(output.read_text()))
        self.assertEqual(report["results"], [result])
        self.assertEqual(report["classification"], "infrastructure-failure")
        self.assertEqual(observed, ["run-public-complete", "logs"])
