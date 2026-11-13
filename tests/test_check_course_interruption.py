"""Завершённые сценарии и точный остаток переживают остановку checker."""

import copy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
from typing import Protocol, runtime_checkable

from gradle_unit_fixtures import write_registry
from test_selected_file_delivery import manifest
from json_boundary import json_object, is_object

ROOT = Path(__file__).resolve().parents[1]


@runtime_checkable
class Checker(Protocol):
    def main(self) -> int: ...


class CheckCourseInterruption(unittest.TestCase):
    def test_completed_scenario_is_saved_before_next_job_and_on_interrupt(self) -> None:
        self.verify_interruption(active_container=False)

    def test_active_container_cleanup_cannot_replace_primary_interrupt(self) -> None:
        self.verify_interruption(active_container=True)

    def test_completed_grading_ownership_interrupt_retains_cleanup_required_and_logs(
        self,
    ) -> None:
        import subprocess
        import grading_job as jobs

        cases: list[
            tuple[str, bool, subprocess.CompletedProcess[str] | BaseException]
        ] = [
            (
                "removed",
                True,
                subprocess.CompletedProcess(["docker", "rm"], 0, stdout="", stderr=""),
            ),
            (
                "absent",
                True,
                subprocess.CompletedProcess(
                    ["docker", "rm"], 1, stdout="", stderr="No such container"
                ),
            ),
            (
                "denied",
                False,
                subprocess.CompletedProcess(
                    ["docker", "rm"], 1, stdout="", stderr="daemon denied removal"
                ),
            ),
            ("timeout", False, subprocess.TimeoutExpired("docker rm", 10)),
            ("unavailable", False, OSError("daemon unavailable")),
            ("interrupted", False, KeyboardInterrupt("повторная отмена удаления")),
        ]
        real_remove = shutil.rmtree
        for label, stopped, removal in cases:
            with (
                self.subTest(removal=label),
                tempfile.TemporaryDirectory() as temporary,
            ):
                spec = importlib.util.spec_from_file_location(
                    "ownership_interrupted_check_course", ROOT / "tools/check-course.py"
                )
                assert spec is not None and spec.loader is not None
                cli = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(cli)
                if not isinstance(cli, Checker):
                    raise TypeError("Контракт checker недоступен")
                root = Path(temporary)
                source = root / "manifest.json"
                output = root / "report.json"
                value = manifest()
                check = value["projects"][0]["check"]
                check["runtime"] = "java25-gradle-junit-v1"
                check["java-build"] = {
                    "kind": "gradle-jar-v1",
                    "artifact": "answer.jar",
                }
                source.write_text(json.dumps(value))
                runtime_registry = write_registry(root)
                completed = {
                    "qualifiedId": "demo/exr-answer",
                    "scenario": "starter",
                    "infrastructure": "complete",
                    "classification": "success",
                }
                log_data = (
                    "Журнал завершённого grading сохранён до ownership cleanup.\n"
                )
                log = (
                    output.with_name(output.name + ".private-build-evidence")
                    / "demo/exr-answer/starter/compile.log"
                )
                prepared: jobs.GradingJob | None = None
                selected_name: str | None = None
                events: list[str] = []
                calls = 0
                interrupt = KeyboardInterrupt(
                    "отмена ownership после завершённого grading"
                )

                def execute(
                    job: object, backend: str, registry: object
                ) -> dict[str, str]:
                    nonlocal prepared
                    if not isinstance(job, jobs.GradingJob):
                        raise TypeError("Подготовленный job недоступен")
                    self.assertEqual(backend, "container")
                    prepared = job
                    self.addCleanup(
                        lambda: real_remove(job.root) if job.root.exists() else None
                    )
                    private = job.root / ".native-build-private"
                    private.mkdir(mode=0o700)
                    evidence = private / "compile.log"
                    evidence.write_text(log_data)
                    evidence.chmod(0o600)
                    events.append("grading-complete")
                    return completed

                def run(
                    command: list[str], **kwargs: object
                ) -> subprocess.CompletedProcess[str]:
                    nonlocal calls, selected_name
                    calls += 1
                    self.assertLessEqual(calls, 2)
                    job = prepared
                    if job is None:
                        raise AssertionError("Ownership запущен до подготовки job")
                    self.assertTrue(job.root.is_dir())
                    self.assertEqual(log.read_text(), log_data)
                    self.assertEqual(
                        kwargs, {"capture_output": True, "text": True, "timeout": 10}
                    )
                    if calls == 1:
                        saved = json_object(json.loads(output.read_text()))
                        self.assertEqual(saved["results"], [completed])
                        self.assertEqual(saved["remaining"], [])
                        self.assertEqual(
                            command[:4], ["docker", "run", "--rm", "--name"]
                        )
                        selected_name = command[4]
                        self.assertRegex(selected_name, r"^plcleanup-[0-9a-f]{24}$")
                        self.assertIn(job["imageDigest"], command)
                        self.assertIn(
                            f"type=bind,src={job.root},dst=/grade,bind-recursive=disabled",
                            command,
                        )
                        events.append("ownership-run")
                        raise interrupt
                    self.assertEqual(
                        command, ["docker", "rm", "--force", selected_name]
                    )
                    events.append("ownership-remove")
                    if isinstance(removal, BaseException):
                        raise removal
                    return removal

                args = [
                    "check-course.py",
                    "--manifest",
                    str(source),
                    "--snapshot",
                    str(root),
                    "--backend",
                    "container",
                    "--scenario",
                    "starter",
                    "--runtime-registry",
                    str(runtime_registry),
                    "--output",
                    str(output),
                ]
                with (
                    patch.object(sys, "argv", args),
                    patch.object(cli, "run_job", side_effect=execute),
                    patch.object(
                        jobs.shutil,
                        "rmtree",
                        side_effect=PermissionError("mixed owner"),
                    ) as remove,
                    patch.object(jobs.subprocess, "run", side_effect=run),
                ):
                    self.assertEqual(cli.main(), 130, output.read_text())
                    self.assertEqual(remove.call_count, 1)
                job = prepared
                if job is None:
                    raise AssertionError("Grading job не был подготовлен")
                self.assertEqual(calls, 2)
                self.assertEqual(
                    events, ["grading-complete", "ownership-run", "ownership-remove"]
                )
                self.assertIs(job._containers_stopped, stopped)
                self.assertTrue(job.root.is_dir())
                self.assertEqual(log.read_text(), log_data)
                preserved = json_object(
                    json.loads(log.with_name("files.json").read_text())
                )
                self.assertEqual(preserved["files"], ["compile.log"])
                saved = json_object(json.loads(output.read_text()))
                self.assertEqual(saved["results"], [completed])
                self.assertEqual(saved["remaining"], [])
                self.assertEqual(saved["classification"], "interrupted")
                self.assertEqual(saved["coverage"], "partial")
                self.assertNotIn("score", saved)
                self.assertNotIn("summary", saved)
                self.assertIn(
                    "cleanupRequired",
                    saved,
                    "Прерванная ownership cleanup должна сохранить точный scratch",
                )
                cleanup = json_object(saved["cleanupRequired"])
                self.assertEqual(cleanup["qualifiedId"], "demo/exr-answer")
                self.assertEqual(cleanup["scenario"], "starter")
                self.assertEqual(cleanup["scratch"], str(job.root))
                error = cleanup["error"]
                self.assertIsInstance(error, str)
                if not isinstance(error, str):
                    raise AssertionError("Отсутствует cleanup error")
                self.assertTrue(error)

    def verify_interruption(self, *, active_container: bool) -> None:
        spec = importlib.util.spec_from_file_location(
            "interrupted_check_course", ROOT / "tools/check-course.py"
        )
        assert spec is not None and spec.loader is not None
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        if not isinstance(cli, Checker):
            raise TypeError("Контракт checker недоступен")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "manifest.json"
            output = root / "report.json"
            value = manifest()
            second = copy.deepcopy(value["projects"][0])
            second.update(
                exerciseId="exr-next",
                qualifiedId="demo/exr-next",
                projectRoot="projects/next",
                source="labs/next.qmd",
            )
            value["projects"].append(second)
            source.write_text(json.dumps(value))
            registry = write_registry(root)
            first_result = {
                "qualifiedId": "demo/exr-answer",
                "scenario": "starter",
                "infrastructure": "complete",
                "classification": "success",
            }

            interrupted_root: Path | None = None

            def execute(
                job: object, backend: str, runtime_registry: object
            ) -> dict[str, str]:
                nonlocal interrupted_root
                if not is_object(job):
                    raise TypeError("Подготовленный job недоступен")
                if job["qualifiedId"] == "demo/exr-answer":
                    return first_result
                saved = json_object(json.loads(output.read_text()))
                self.assertEqual(saved["results"], [first_result])
                self.assertEqual(
                    saved["remaining"],
                    [
                        {"qualifiedId": "demo/exr-next", "scenario": "starter"},
                    ],
                )
                self.assertEqual(saved["coverage"], "partial")
                self.assertNotIn("summary", saved)
                if active_container:
                    # Настоящий cleanup должен отказать без удаления scratch.
                    # Контейнер не запускается; это состояние прерванного runner.
                    job_root: object = getattr(job, "root", None)
                    if not isinstance(job_root, Path):
                        raise TypeError("Private job root недоступен")
                    setattr(job, "_containers_stopped", False)
                    self.addCleanup(shutil.rmtree, job_root)
                    interrupted_root = job_root
                raise KeyboardInterrupt

            args = [
                "check-course.py",
                "--manifest",
                str(source),
                "--snapshot",
                str(root),
                "--backend",
                "container" if active_container else "host",
                "--scenario",
                "starter",
                "--runtime-registry",
                str(registry),
                "--output",
                str(output),
            ]
            with (
                patch.object(sys, "argv", args),
                patch.object(cli, "run_job", side_effect=execute),
            ):
                self.assertEqual(cli.main(), 130, output.read_text())
            saved = json_object(json.loads(output.read_text()))
            self.assertEqual(saved["results"], [first_result])
            self.assertEqual(
                saved["remaining"],
                [
                    {"qualifiedId": "demo/exr-next", "scenario": "starter"},
                ],
            )
            self.assertEqual(saved["classification"], "interrupted")
            self.assertEqual(saved["coverage"], "partial")
            self.assertNotIn("score", saved)
            self.assertNotIn("summary", saved)
            if active_container:
                if interrupted_root is None:
                    raise AssertionError("Прерванный private job root не сохранён")
                self.assertTrue(interrupted_root.is_dir())
                cleanup = json_object(saved["cleanupRequired"])
                self.assertEqual(cleanup["qualifiedId"], "demo/exr-next")
                self.assertEqual(cleanup["scenario"], "starter")
                self.assertEqual(cleanup["scratch"], str(interrupted_root))
                error = cleanup["error"]
                self.assertIsInstance(error, str)
                if not isinstance(error, str):
                    raise AssertionError("Отсутствует cleanup error")
                self.assertIn("stopped containers", error)


if __name__ == "__main__":
    unittest.main()
