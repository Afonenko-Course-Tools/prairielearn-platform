"""Current workflows run consumer contracts without an unused exporter pipeline."""

from pathlib import Path
import subprocess
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]


class PublicationWorkflows(unittest.TestCase):
    def workflow(self, name: str):
        return yaml.load(
            (ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader
        )

    def test_dispatch_modes_have_separate_jobs_and_metadata_keeps_public_assets(self):
        workflow = self.workflow("publish-runtime.yml")
        inputs = workflow["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(set(inputs), {"version", "reviewed_commit", "components"})
        self.assertEqual(inputs["components"]["options"], ["all", "community", "java"])
        jobs = workflow["jobs"]
        for job, mode in [
            ("publish", "all"),
            ("community", "community"),
            ("java", "java"),
        ]:
            self.assertEqual(
                jobs[job]["if"], "${{ inputs.components == '" + mode + "' }}"
            )
        steps = jobs["publish"]["steps"]
        commands = "\n".join(step.get("run", "") for step in steps)
        self.assertIn("python3 tools/publish-metadata.py", commands)
        self.assertTrue((ROOT / "tools/publish-metadata.py").is_file())
        outputs = "\n".join(step.get("with", {}).get("path", "") for step in steps)
        self.assertIn("runtime-image.json", outputs)
        self.assertIn("published-runtime-profiles.json", outputs)
        self.assertIn("${{ runner.temp }}/workspace-smoke.json", outputs)

    def test_contract_and_release_workflows_execute_current_consumers_without_fixture_export(
        self,
    ):
        for name in ["check.yml", "publish-runtime.yml"]:
            with self.subTest(workflow=name):
                workflow = self.workflow(name)
                steps = [
                    step for job in workflow["jobs"].values() for step in job["steps"]
                ]
                commands = "\n".join(step.get("run", "") for step in steps)
                self.assertIn("python3 -m unittest discover -s tests -v", commands)
                self.assertIn("node --test tests/bridge/*.test.mjs", commands)
                for step in steps:
                    self.assertNotIn(
                        "repository",
                        step.get("with", {}),
                        "Consumer checks must not generate unused course fixtures",
                    )
                    self.assertNotIn("PL_DELIVERY4_FIXTURES", step.get("run", ""))

    def test_every_workflow_shell_block_has_valid_bash_syntax(self):
        for name in ["check.yml", "publish-runtime.yml"]:
            workflow = self.workflow(name)
            for job_name, job in workflow["jobs"].items():
                for step in job["steps"]:
                    if "run" not in step:
                        continue
                    with self.subTest(
                        workflow=name, job=job_name, step=step.get("name")
                    ):
                        result = subprocess.run(
                            ["bash", "-n"],
                            input=step["run"],
                            text=True,
                            capture_output=True,
                            timeout=5,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
