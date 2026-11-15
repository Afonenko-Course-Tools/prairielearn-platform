"""Настоящие shell-блоки publisher на вымышленных commands/артефактах."""

from collections.abc import Mapping
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/publish-runtime.yml"


class _ReadbackOverrides(TypedDict, total=False):
    digest: str
    label_revision: str
    label_source: str


def community() -> str:
    text = WORKFLOW.read_text()
    assert "\n  community:\n" in text, "Отсутствует изолированный Community publisher"
    return text.split("\n  community:\n", 1)[1]


def block(name: str) -> str:
    source = (
        WORKFLOW.read_text().split("\n  community:\n", 1)[0]
        if name == "Resolve immutable version"
        else community()
    )
    text = source.split("      - name: " + name + "\n", 1)[1]
    run = text.split("        run: |\n", 1)[1].split("\n      - ", 1)[0]
    return "\n".join(line[10:] for line in run.splitlines()) + "\n"


class CommunityPublication(unittest.TestCase):
    def test_exclusive_component_jobs_and_no_other_runtime_rebuild(self) -> None:
        text = WORKFLOW.read_text()
        self.assertIn("if: ${{ inputs.components == 'all' }}", text)
        c = community()
        self.assertIn("if: ${{ inputs.components == 'community' }}", c)
        for forbidden in [
            "images/java25-grader",
            "images/fish-git-grader",
            "images/sp-git-workspace",
            "tools/publish-metadata.py",
            "tools/prepare_native_toolchain.py",
            "quarto",
            "exporter_commit",
            "workspace-smoke.json",
            "delivery4-fixtures",
        ]:
            self.assertNotIn(forbidden, c)
        self.assertIn("node --test tests/bridge/*.test.mjs", c)
        self.assertIn("tests/recognized-*.test.mjs", c)
        self.assertIn("--aggregate=", c)

    def run_block(
        self,
        name: str,
        changes: Mapping[str, str] | None = None,
        git_head: str = "a" * 40,
        digest: str | None = None,
        label_revision: str | None = None,
        label_source: str | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
        with tempfile.TemporaryDirectory(prefix="community-publisher-") as tmp:
            root = Path(tmp)
            bin = root / "bin"
            bin.mkdir()
            (root / "VERSION").write_text("2.5.3\n")
            git = bin / "git"
            git.write_text('#!/bin/sh\nprintf "%s\\n" "$FIXTURE_HEAD"\n')
            git.chmod(0o700)
            docker = bin / "docker"
            docker.write_text("""#!/bin/sh
printf '%s\\n' "$*" >> "$FIXTURE_CALLS"
case "$*" in
  *RepoDigests*) printf '%s\\n' "$FIXTURE_DIGEST";;
  *org.opencontainers.image.revision*) printf '%s\\n' "$FIXTURE_REVISION";;
  *org.opencontainers.image.source*) printf '%s\\n' "$FIXTURE_SOURCE";;
  'image inspect '*) printf '%s\\n' '[{"Id":"fictional-owned-image"}]';;
  'pull '*) exit 0;;
  *) exit 90;;
esac
""")
            docker.chmod(0o700)
            env = {
                **os.environ,
                "PATH": str(bin) + ":/usr/bin:/bin",
                "VERSION": "2.5.3",
                "REVIEWED_COMMIT": "a" * 40,
                "GITHUB_SHA": "a" * 40,
                "GITHUB_REF": "refs/heads/main",
                "GITHUB_REPOSITORY": "Example/Platform",
                "GITHUB_REPOSITORY_OWNER": "Example",
                "GITHUB_ENV": str(root / "env"),
                "GITHUB_STEP_SUMMARY": str(root / "summary"),
                "COMMUNITY_IMAGE": "ghcr.io/example/prairielearn-community-gateway:2.5.3",
                "FIXTURE_HEAD": git_head,
                "FIXTURE_CALLS": str(root / "calls"),
                "FIXTURE_DIGEST": digest
                if digest is not None
                else "ghcr.io/example/prairielearn-community-gateway@sha256:"
                + "b" * 64,
                "FIXTURE_REVISION": label_revision
                if label_revision is not None
                else "a" * 40,
                "FIXTURE_SOURCE": label_source
                if label_source is not None
                else "https://github.com/Example/Platform",
            }
            env.update(changes or {})
            cp = subprocess.run(
                ["/bin/bash", "-euo", "pipefail", "-c", block(name)],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return cp, {p.name: p.read_text() for p in root.iterdir() if p.is_file()}

    def test_actual_source_guard(self) -> None:
        cp, files = self.run_block("Зафиксировать reviewed Community source")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertEqual(
            files["env"],
            "COMMUNITY_IMAGE=ghcr.io/example/prairielearn-community-gateway:2.5.3\n",
        )
        for change in [
            {"VERSION": "2.5.2"},
            {"VERSION": "latest"},
            {"GITHUB_REF": "refs/heads/other"},
            {"REVIEWED_COMMIT": "c" * 40},
            {"GITHUB_SHA": "c" * 40},
        ]:
            cp, _ = self.run_block("Зафиксировать reviewed Community source", change)
            self.assertNotEqual(cp.returncode, 0)
        cp, _ = self.run_block(
            "Зафиксировать reviewed Community source", git_head="c" * 40
        )
        self.assertNotEqual(cp.returncode, 0)

    def test_actual_digest_and_label_readback(self) -> None:
        cp, files = self.run_block("Проверить Community digest и source readback")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertEqual(
            files["community-image.txt"].strip(),
            "ghcr.io/example/prairielearn-community-gateway@sha256:" + "b" * 64,
        )
        self.assertIn(
            "pull ghcr.io/example/prairielearn-community-gateway@sha256:",
            files["calls"],
        )
        variants: list[_ReadbackOverrides] = [
            {"digest": "ghcr.io/example/prairielearn-community-gateway:latest"},
            {
                "digest": "ghcr.io/foreign/prairielearn-community-gateway@sha256:"
                + "b" * 64
            },
            {"label_revision": "c" * 40},
            {"label_source": "https://github.com/foreign/Platform"},
        ]
        for kwargs in variants:
            cp, files = self.run_block(
                "Проверить Community digest и source readback", **kwargs
            )
            self.assertNotEqual(cp.returncode, 0)
            self.assertNotIn("community-image.txt", files)

    def test_all_mode_requires_reviewed_source_without_exporter_input(self) -> None:
        name = "Resolve immutable version"
        cp, files = self.run_block(name, {"COMPONENTS": "all"})
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("RUNTIME_IMAGE=", files["env"])
        self.assertIn("WORKSPACE_IMAGE=", files["env"])
        for change in [
            {"COMPONENTS": "other"},
            {"COMPONENTS": "all", "REVIEWED_COMMIT": "c" * 40},
            {"COMPONENTS": "all", "VERSION": "0.0.0"},
        ]:
            cp, _ = self.run_block(name, change)
            self.assertNotEqual(cp.returncode, 0)


if __name__ == "__main__":
    unittest.main()
