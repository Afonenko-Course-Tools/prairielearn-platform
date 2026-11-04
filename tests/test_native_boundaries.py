"""Адресные guards реальных ролей и завершения процессов, без inventory admission."""
import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from test_grading_job import grader

class SeparateNativeRolesTests(unittest.TestCase):
    """Synthetic role records/env; actual kernel gates remain separate."""

    def setUp(self):
        self.assertTrue(
            callable(getattr(grader, "_validate_role_records", None)),
            "Missing two-role isolation guard",
        )
        self.roles = {
            "sbuser": {"uid": 1101, "gid": 1101, "groups": [1101]},
            "nativebuild": {"uid": 1102, "gid": 1102, "groups": [1102]},
        }

    def test_distinct_private_groups_pass_and_collisions_or_extra_groups_refuse(self):
        import copy

        grader._validate_role_records(self.roles, {1000}, {1000})
        for mutation in [
            "root",
            "same-uid",
            "same-gid",
            "extra-group",
            "build-group",
            "mounted-uid",
            "mounted-gid",
        ]:
            r = copy.deepcopy(self.roles)
            if mutation == "root":
                r["nativebuild"]["uid"] = 0
            elif mutation == "same-uid":
                r["nativebuild"]["uid"] = 1101
            elif mutation == "same-gid":
                r["nativebuild"]["gid"] = 1101
                r["nativebuild"]["groups"] = [1101]
            elif mutation == "extra-group":
                r["sbuser"]["groups"].append(27)
            elif mutation == "build-group":
                r["sbuser"]["groups"].append(1102)
            elif mutation == "mounted-uid":
                r["nativebuild"]["uid"] = 1000
            else:
                r["nativebuild"]["gid"] = 1000
                r["nativebuild"]["groups"] = [1000]
            with self.subTest(mutation=mutation):
                with self.assertRaises(grader.GraderError):
                    grader._validate_role_records(r, {1000}, {1000})
        with self.assertRaises(grader.GraderError):
            grader._validate_role_records(
                {"sbuser": self.roles["sbuser"]}, set(), set()
            )

    def test_grade_environment_discards_inherited_native_and_jvm_options(self):
        with patch.dict(
            os.environ,
            {
                "PL_CONTAINMENT": "official",
                "JAVA_HOME": "/opt/native-jdk",
                "PATH": "/hostile",
                "LD_PRELOAD": "/evil",
                "JAVA_TOOL_OPTIONS": "-javaagent:/evil",
                "_JAVA_OPTIONS": "-Dsecret=x",
                "JDK_JAVA_OPTIONS": "-javaagent:/evil",
                "JDK_JAVAC_OPTIONS": "-processor Evil",
                "CLASSPATH": "/evil",
                "HOME": "/tmp/build-home",
                "GRADLE_USER_HOME": "/tmp/build-cache",
            },
        ):
            env = grader._grading_environment()
        self.assertEqual(
            env,
            {
                "PATH": "/usr/lib/jvm/java-25-openjdk-amd64/bin:/usr/bin:/bin",
                "JAVA_HOME": "/usr/lib/jvm/java-25-openjdk-amd64",
                "HOME": "/nonexistent",
                "TMPDIR": "/tmp",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
            },
        )

    def test_private_build_root_rejects_world_search_group_or_identity_drift(self):
        good = {"uid": 0, "gid": 1102, "mode": 0o750, "directory": True}
        grader._validate_build_root_record(good, 1102)
        for key, value in [
            ("mode", 0o755),
            ("mode", 0o770),
            ("gid", 1101),
            ("uid", 1102),
            ("directory", False),
        ]:
            with self.subTest(key=key, value=value):
                with self.assertRaises(grader.GraderError):
                    grader._validate_build_root_record(dict(good, **{key: value}), 1102)

    def test_process_membership_uses_actual_uid_not_process_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for pid, uid in [(71, 1102), (72, 1101)]:
                p = root / str(pid)
                p.mkdir()
                (p / "status").write_text(
                    f"Name: java\nUid: {uid} {uid} {uid} {uid}\nState: S (sleeping)\n"
                )
                (p / "stat").write_text(
                    str(pid)
                    + " (java) S "
                    + " ".join(["0"] * 18 + ["314159"] + ["0"] * 5)
                )
            self.assertEqual(
                grader._build_process_records(root, 1102),
                {71: {"uid": 1102, "starttime": "314159", "state": "S"}},
            )


class NamespaceBoundaryTests(unittest.TestCase):
    def test_host_scope_cannot_reach_role_or_process_inventory(self):
        with patch.object(Path, "is_file", return_value=False), patch.object(
            os, "geteuid", return_value=0
        ), patch.object(
            grader,
            "_role_records",
            side_effect=AssertionError("Unscoped role/process access"),
        ):
            with self.assertRaises(grader.GraderError):
                grader._grading_boundary()


class BuildTransitionCleanupTests(unittest.TestCase):
    def test_cleanup_binds_pid_identity_and_records_empty_remaining_set(self):
        first = {71: {"uid": 1102, "starttime": "15", "state": "S"}}
        changed = {71: {"uid": 1102, "starttime": "16", "state": "S"}}
        for rescan, expected in [(first, [71]), (changed, [])]:
            killed = []
            with patch.object(Path, "is_file", return_value=True), patch.object(
                os, "geteuid", return_value=0
            ), patch.object(
                grader, "_build_process_records", side_effect=[first, rescan, {}]
            ), patch.object(
                os, "kill", side_effect=lambda pid, sig: killed.append(pid)
            ), patch.object(
                os, "waitpid", side_effect=ChildProcessError
            ):
                receipt = grader._finish_build_role(1102)
            self.assertEqual(killed, expected)
            self.assertEqual(
                receipt,
                {"uid": 1102, "remaining": [], "terminated": expected, "reaped": []},
            )

