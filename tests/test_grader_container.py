"""Actual offline container execution at the declared PL CPU/memory limits."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import FunctionType
from typing import Protocol, runtime_checkable
from selected_job_fixture import fixture_set_up, fixture_record

import base64
import json
import os
from pathlib import Path
import subprocess
import unittest
import test_grading_job as fixtures
from gradle_unit_fixtures import registry as unit_registry, platform_tree


@runtime_checkable
class _ProtectIdentity(Protocol):
    def __call__(self, job: Path) -> None: ...


class _MutationOwner(Protocol):
    @property
    def job(self) -> Path: ...
    @property
    def cfg(self) -> dict[str, object]: ...


@runtime_checkable
class _MutationSetup(Protocol):
    def __call__(self, owner: _MutationOwner, /) -> None: ...
    def __get__(
        self, instance: _MutationOwner, owner: type[object] | None = None, /
    ) -> Callable[[], None]: ...


grader = fixtures.grader
mutation_setup: object = getattr(fixtures.MutationJob, "setup_mutation")
if not isinstance(mutation_setup, _MutationSetup) or not isinstance(
    mutation_setup, FunctionType
):
    raise AssertionError("Fixture mutation setup должен быть прежней unbound функцией")


class SandboxIdentityPreflight(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "Official container identity is Unix-only")
    def test_uid_remap_refuses_non_container_context(self) -> None:
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for folder in ("student", "tests"):
                (root / folder).mkdir()
            ids = [
                uid
                for uid in range(60000, 60100)
                if uid not in {os.geteuid(), os.getegid()}
            ][:2]
            accounts = {
                name: SimpleNamespace(
                    pw_uid=uid, pw_gid=uid, pw_shell="/usr/sbin/nologin"
                )
                for name, uid in zip(("sbuser", "nativebuild"), ids)
            }

            def groups(name: str, gid: int) -> list[int]:
                return [gid]

            protect: object = getattr(grader, "_protect_input_identity")
            if not isinstance(protect, _ProtectIdentity):
                raise AssertionError("Identity preflight hook grader недоступен")
            with (
                patch("pwd.getpwnam", side_effect=accounts.__getitem__),
                patch(
                    "grp.getgrnam",
                    return_value=SimpleNamespace(gr_gid=ids[1], gr_mem=[]),
                ),
                patch("os.getgrouplist", side_effect=groups),
                patch.object(
                    Path,
                    "stat",
                    return_value=SimpleNamespace(st_uid=ids[0], st_gid=ids[0]),
                ),
                patch.object(Path, "is_file", return_value=False),
                patch.object(
                    grader,
                    "_run",
                    side_effect=AssertionError("host account remap attempted"),
                ),
            ):
                with self.assertRaisesRegex(grader.GraderError, "supported container"):
                    protect(root)


@unittest.skipUnless(
    os.environ.get("PL_TEST_IMAGE"), "Set PL_TEST_IMAGE to an actual built image ID"
)
class ContainerParity(unittest.TestCase):
    job: Path
    cfg: dict[str, object]
    runtime_registry: dict[str, object]

    def setUp(self) -> None:
        from unittest.mock import patch
        import grading_job

        fixture_set_up(fixtures.JUnitJob.setUp)(self)
        root = self.enterContext(platform_tree(java_image=os.environ["PL_TEST_IMAGE"]))
        self.runtime_registry = fixture_record(
            json.loads((root / "runtime-profiles.json").read_text())
        )
        self.enterContext(patch.object(grading_job, "ROOT", root))

    def test_same_payload_two_cold_jobs_match_host(self) -> None:
        (self.job / "tests/grading-job.json").write_text(json.dumps(self.cfg))
        host = fixture_record(grader.grade(self.job, registry=unit_registry()))
        values: list[dict[str, object]] = []
        for _ in range(2):
            p = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--cpus",
                    "0.9",
                    "--memory",
                    "512m",
                    "--pids-limit",
                    "128",
                    "--mount",
                    f"type=bind,src={self.job},dst=/grade",
                    os.environ["PL_TEST_IMAGE"],
                    "--verification",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(p.returncode, 0, p.stderr)
            r = fixture_record(
                json.loads((self.job / "results/results.json").read_text())
            )
            values.append(r)
            self.assertEqual(r["score"], host["score"])
            self.assertEqual(r["counts"], host["counts"])
            self.assertEqual(r["rawResult"], host["rawResult"])
        for value in values:
            value.pop("durations")
            value.pop("toolchain")
        self.assertEqual(values[0], values[1])

    def test_outer_docker_failure_is_infrastructure(self) -> None:
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
        from grading_job import GradingJob, run_job

        job = GradingJob(
            schemaVersion=3,
            scope="declared",
            qualifiedId="synthetic/exr-test",
            scenario="starter",
            runtime="java25-junit-v1",
            imageDigest="sha256:" + "0" * 64,
            sources=[
                {
                    "name": "Student.java",
                    "target": "student/Student.java",
                    "data": base64.b64encode(
                        (self.job / "student/Student.java").read_bytes()
                    ).decode(),
                }
            ],
            trustedTests=[
                {
                    "name": "AnswerTest.java",
                    "target": "tests/AnswerTest.java",
                    "data": base64.b64encode(
                        (self.job / "tests/AnswerTest.java").read_bytes()
                    ).decode(),
                }
            ],
            grading=self.cfg,
        )
        job.root = self.job
        r = run_job(job, "container", registry=self.runtime_registry)
        self.assertEqual(r["classification"], "infrastructure-failure")
        self.assertNotIn("score", r)

    def test_official_sandbox_denies_proc_trusted_write_and_root_exec(self) -> None:
        self._assert_official_sandbox()

    def test_official_sandbox_denies_trusted_write_when_host_uid_matches_sbuser(
        self,
    ) -> None:
        self._assert_official_sandbox(input_uid=1001)

    def _assert_official_sandbox(self, input_uid: int | None = None) -> None:
        fixture_record(self.cfg["limits"])["run-seconds"] = 10
        (
            self.job / "student/Student.java"
        ).write_text("""public class Student {public static int answer() throws Exception {
   if(System.getProperty("sun.java.command","").contains("signature")) throw new AssertionError("containment: signature in command");
   try { java.nio.file.Files.readString(java.nio.file.Path.of("/proc/self/maps"));throw new AssertionError("containment: proc maps readable");} catch(java.nio.file.AccessDeniedException expected){}
   try { java.nio.file.Files.writeString(java.nio.file.Path.of("/grade/tests/injected"),"tampered");throw new AssertionError("containment: trusted input writable");} catch(java.nio.file.AccessDeniedException expected){}
   try { java.nio.file.Files.writeString(java.nio.file.Path.of("/platform/runtime-profiles.json"),"tampered");throw new AssertionError("containment: platform runtime writable");} catch(java.nio.file.AccessDeniedException expected){}
   Process proc=new ProcessBuilder("/usr/bin/id","-u").start();String uid=new String(proc.getInputStream().readAllBytes()).trim();if(proc.waitFor()!=0 || uid.equals("0"))throw new AssertionError("containment: child uid "+uid);
   Process child=new ProcessBuilder("/bin/sh","-c","cat /proc/self/maps >/tmp/student-proc-copy").start();if(child.waitFor()==0)throw new AssertionError("containment: child proc maps readable");
   return 42;
  }}""")
        if input_uid is not None:
            source = self.job / "student/Student.java"
            source.write_text(
                source.read_text().replace(
                    'uid.equals("0")', f'(uid.equals("0") || uid.equals("{input_uid}"))'
                )
            )
        (self.job / "tests/grading-job.json").write_text(json.dumps(self.cfg))
        mount = f"type=bind,src={self.job},dst=/grade"
        owners = {
            folder: (self.job / folder).stat().st_uid
            for folder in (".", "student", "tests")
        }

        def input_owner(uid: Mapping[str, int]) -> None:
            script = "import os;" + "".join(
                f'os.chown("/grade/{folder}",{value},-1);'
                for folder, value in uid.items()
            )
            setup = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--mount",
                    mount,
                    "--entrypoint",
                    "python3",
                    os.environ["PL_TEST_IMAGE"],
                    "-c",
                    script,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(setup.returncode, 0, setup.stderr)

        try:
            if input_uid is not None:
                input_owner({folder: input_uid for folder in owners})
            p = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--cpus",
                    "0.9",
                    "--memory",
                    "512m",
                    "--mount",
                    mount,
                    os.environ["PL_TEST_IMAGE"],
                    "--verification",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            expected_owner = (
                owners
                if input_uid is None
                else {folder: input_uid for folder in owners}
            )
            self.assertEqual(
                {folder: (self.job / folder).stat().st_uid for folder in owners},
                expected_owner,
                "grader changed host input ownership",
            )
        finally:
            if input_uid is not None:
                input_owner(owners)
        self.assertEqual(p.returncode, 0, p.stderr)
        r = fixture_record(json.loads((self.job / "results/results.json").read_text()))
        self.assertEqual(r["score"], 1, r)
        self.assertEqual(r["containment"], "official-landlock-sbuser")
        self.assertFalse((self.job / "tests/injected").exists())

    def test_outer_timeout_removes_actual_job_container(self) -> None:
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
        from grading_job import GradingJob, run_job

        cfg = fixture_record(json.loads(json.dumps(self.cfg)))
        fixture_record(cfg["limits"])["outer-seconds"] = 1.0
        (self.job / "tests/grading-job.json").write_text(json.dumps(self.cfg))
        job = GradingJob(
            schemaVersion=3,
            scope="declared",
            qualifiedId="synthetic/exr-timeout",
            scenario="starter",
            runtime="java25-junit-v1",
            imageDigest=os.environ["PL_TEST_IMAGE"],
            sources=[
                {
                    "name": "Student.java",
                    "target": "student/Student.java",
                    "data": base64.b64encode(
                        (self.job / "student/Student.java").read_bytes()
                    ).decode(),
                }
            ],
            trustedTests=[
                {
                    "name": "AnswerTest.java",
                    "target": "tests/AnswerTest.java",
                    "data": base64.b64encode(
                        (self.job / "tests/AnswerTest.java").read_bytes()
                    ).decode(),
                }
            ],
            grading=cfg,
        )
        job.root = self.job
        result = run_job(job, "container", registry=self.runtime_registry)
        self.assertEqual(result["classification"], "infrastructure-failure")
        self.assertNotIn("score", result)
        inspection = subprocess.run(
            ["docker", "inspect", job.containerName], capture_output=True
        )
        subprocess.run(
            ["docker", "rm", "--force", job.containerName], capture_output=True
        )
        self.assertNotEqual(inspection.returncode, 0)


@unittest.skipUnless(
    os.environ.get("PL_TEST_IMAGE"), "Set PL_TEST_IMAGE to an actual built image ID"
)
class MutationRuntimeContainment(unittest.TestCase):
    job: Path
    cfg: dict[str, object]
    setUp = fixture_set_up(fixtures.MutationJob.setUp)
    setup_mutation = mutation_setup

    def test_shared_adapter_and_libraries_cannot_be_modified_between_variants(
        self,
    ) -> None:
        self.setup_mutation()
        (
            self.job / "student/AnswerTest.java"
        ).write_text("""import org.junit.jupiter.api.Test;import static org.junit.jupiter.api.Assertions.*;
  public class AnswerTest {@Test void checked() throws Exception {
   for(String entry:System.getProperty("java.class.path").split(java.io.File.pathSeparator)) {
    java.nio.file.Path p=java.nio.file.Path.of(entry);
    if(p.getFileName().toString().equals("adapter")) {
      try{java.nio.file.Files.writeString(p.getParent().resolve("compiler.jsa"),"tampered");fail("compiler archive writable");}catch(java.nio.file.AccessDeniedException expected){}
    }
    if(java.nio.file.Files.isDirectory(p))p=p.resolve("PlatformJUnitAdapter.class");
    try{java.nio.file.Files.writeString(p,"tampered");fail("classpath writable: "+entry);}catch(java.nio.file.AccessDeniedException expected){}
   }
   assertEquals(42,Student.answer());
  }}""")
        (self.job / "tests/grading-job.json").write_text(json.dumps(self.cfg))
        p = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--cpus",
                "0.9",
                "--memory",
                "512m",
                "--pids-limit",
                "128",
                "--mount",
                f"type=bind,src={self.job},dst=/grade",
                os.environ["PL_TEST_IMAGE"],
                "--verification",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        r = fixture_record(json.loads((self.job / "results/results.json").read_text()))
        self.assertEqual(r["score"], 1, r)
        self.assertEqual(
            fixture_record(fixture_record(r["variants"])["correct"])["containment"],
            "official-landlock-sbuser",
        )
        self.assertEqual(
            fixture_record(
                fixture_record(fixture_record(r["variants"])["wrong"])["durations"]
            )["runnerCompilation"],
            0,
        )
