import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import grading_job as jobs
from json_boundary import is_object
import test_selected_file_delivery as selected
import test_build_course as builds
from gradle_unit_fixtures import registry as unit_registry

ROOT = Path(__file__).resolve().parents[1]


class DiagnosticRegistry(unittest.TestCase):
    def test_explicit_registry_selects_candidate_and_host_runner_consistently(
        self,
    ) -> None:
        m = jobs
        registry = unit_registry()
        registry["profiles"]["java25-junit-v1"]["image"] = None
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            manifest = selected.manifest()
            with patch.dict("os.environ", {"PL_LOCAL_IMAGE_ID": "sha256:" + "d" * 64}):
                default = m.prepare_job(manifest, root, "demo/exr-answer", "starter")
                profiles = m.load_runtime_registry()["profiles"]
                assert is_object(profiles)
                profile = profiles["java25-junit-v1"]
                assert is_object(profile)
                self.assertEqual(default["imageDigest"], profile["image"])
                __import__("shutil").rmtree(default.root)
                job = m.prepare_job(
                    manifest, root, "demo/exr-answer", "starter", registry=registry
                )
            try:
                self.assertEqual(job["imageDigest"], "sha256:" + "d" * 64)
                with patch.object(
                    m,
                    "load_runtime_registry",
                    side_effect=AssertionError(
                        "Explicit registry must not reload defaults"
                    ),
                ):
                    with patch.object(
                        m.importlib.util,
                        "spec_from_file_location",
                        side_effect=OSError("mock host unavailable"),
                    ):
                        result = m.run_job(job, "host", registry=registry)
                        self.assertEqual(
                            result["classification"], "infrastructure-failure"
                        )
            finally:
                __import__("shutil").rmtree(job.root)

    def test_builder_forwards_explicit_candidate_flag(self) -> None:
        import inspect

        self.assertIn(
            "candidate_image", inspect.signature(builds.builder.build_course).parameters
        )
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            source = root / "source"
            entry = (
                source
                / "tasks/_extensions/course-prairielearn/entrypoints/export-course.ts"
            )
            entry.parent.mkdir(parents=True)
            entry.write_text("// owner")
            with patch.object(
                builds.builder.subprocess,
                "run",
                side_effect=OSError("stop after capture"),
            ) as run:
                with self.assertRaises(builds.builder.BuildError):
                    builds.builder.build_course(
                        source,
                        "tasks",
                        "pilot",
                        root / "out",
                        root / "registry.json",
                        "sha256:" + "d" * 64,
                    )
            run.assert_called_once()
            command = run.call_args.args[0]
            self.assertEqual(command[:3], ["quarto", "run", str(entry)])
            self.assertEqual(run.call_args.kwargs["cwd"], source / "tasks")
            self.assertEqual(
                command[command.index("--candidate-image") + 1], "sha256:" + "d" * 64
            )

    def test_check_cli_threads_one_explicit_registry_through_prepare_execute_and_receipt(
        self,
    ) -> None:
        import sys

        sys.path.insert(0, str(ROOT / "tools"))
        spec = importlib.util.spec_from_file_location(
            "diagnostic_check", ROOT / "tools/check-course.py"
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Загрузчик локального Python-модуля недоступен")
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "registry.json").write_text('{"profiles":{"diagnostic":{}}}')
            registry: dict[str, object] = {"profiles": {"diagnostic": {}}}
            project: dict[str, object] = {
                "qualifiedId": "demo/exr-a",
                "projectRoot": "p",
                "check": {"runtime": "diagnostic"},
            }
            qualified_id = project["qualifiedId"]
            assert isinstance(qualified_id, str)
            prepared_manifest = selected.manifest()
            prepared_manifest["projects"][0]["qualifiedId"] = qualified_id
            (root / "manifest.json").write_text(json.dumps(prepared_manifest))
            job = jobs.prepare_job(
                prepared_manifest,
                root,
                qualified_id,
                "starter",
                registry=unit_registry(),
            )
            self.addCleanup(__import__("shutil").rmtree, job.root)
            args = [
                "check-course.py",
                "--manifest",
                str(root / "manifest.json"),
                "--snapshot",
                str(root),
                "--runtime-registry",
                str(root / "registry.json"),
                "--output",
                str(root / "result.json"),
            ]
            with (
                patch.object(cli, "cleanup_job"),
                patch.object(sys, "argv", args),
                patch.object(cli, "inventory", return_value=[project]),
                patch.object(
                    cli,
                    "scenario_inventory",
                    return_value=[{"qualifiedId": "demo/exr-a", "scenario": "starter"}],
                ),
                patch.object(cli, "prepare_job", return_value=job) as prepare,
                patch.object(cli, "run_job", return_value={}) as execute,
                patch.object(
                    cli, "verify_results", return_value={"exitCode": 0}
                ) as receipt,
            ):
                self.assertEqual(cli.main(), 0)
            self.assertEqual(prepare.call_args.args[-1], registry)
            self.assertEqual(execute.call_args.args[-1], registry)
            self.assertEqual(receipt.call_args.args[-1], registry)
