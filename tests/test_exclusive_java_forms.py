"""Взаимоисключающие редактор и upload без изменения grader assembly."""

import shutil
import html
import unittest
from collections.abc import Mapping

import test_delivery5 as fixtures
from grading_types import NativeChecks
from gradle_unit_fixtures import registry
import grading_job as g
import delivery_verification as v


class ExclusiveJavaForms(fixtures.DeliveryFixture):
    def automatic_with_policy(self, primary: bool) -> NativeChecks:
        manifest = self.automatic_package()
        manifest["projects"][0]["check"]["additional-java-sources"] = {
            "archive": "solution.zip",
            "primary-required": primary,
            "max-files": 128,
            "max-file-bytes": 1048576,
            "max-total-bytes": 4194304,
            "max-archive-bytes": 2097152,
        }
        job = g.prepare_job(manifest, self.root, self.q, "starter", registry=registry())
        self.addCleanup(shutil.rmtree, job.root)
        self.put(
            "questions/" + self.q + "/tests/grading-job.json",
            job.checked_payload()["grading"],
        )
        return manifest

    def test_optional_primary_accepts_editor_without_any_upload_control(self) -> None:
        manifest = self.automatic_with_policy(False)
        self.put(
            "questions/" + self.q + "/question.html",
            '<pl-file-editor file-name="Answer.java" normalize-to-ascii="false"></pl-file-editor><pl-external-grader-results></pl-external-grader-results>',
        )
        self.assertEqual(
            v.package_integrity(self.d, self.root, manifest)["status"], "success"
        )

    def test_editor_cannot_include_optional_archive_upload(self) -> None:
        manifest = self.automatic_with_policy(True)
        self.put(
            "questions/" + self.q + "/question.html",
            '<pl-file-editor file-name="Answer.java"></pl-file-editor><pl-file-upload optional-file-names="solution.zip"></pl-file-upload><pl-external-grader-results></pl-external-grader-results>',
        )
        with self.assertRaises(g.JobError):
            v.package_integrity(self.d, self.root, manifest)

    def manual_starters(self, sources: Mapping[str, bytes]) -> None:
        for name, data in sources.items():
            target = self.root / (
                "questions/" + self.q + "/serverFilesQuestion/starter/" + name
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        self.d["files"] = sorted(
            p.relative_to(self.root).as_posix()
            for p in self.root.rglob("*")
            if p.is_file()
        )

    def editor(self, name: str, data: bytes) -> str:
        source = (
            html.escape(data.decode("utf-8"))
            .replace("{{", "&#123;&#123;")
            .replace("}}", "&#125;&#125;")
        )
        return (
            '<pl-file-editor file-name="'
            + name
            + '" normalize-to-ascii="false">'
            + source
            + "</pl-file-editor>"
        )

    def test_manual_editor_uses_exact_real_starter_bytes_for_one_or_two_sources(
        self,
    ) -> None:
        sources = {
            "pkg/Launcher.java": "// Ёж {{значение}} <>&\r\npackage pkg;class Launcher {}\r\n".encode(
                "utf-8"
            )
        }
        fixtures.payload(self.d, self.q)["submission"] = {"mode": "editor"}
        for count in [1, 2]:
            with self.subTest(count=count):
                if count == 2:
                    sources["pkg/Helper.java"] = b"package pkg;class Helper {}\n"
                self.manual_starters(sources)
                self.put(
                    "questions/" + self.q + "/question.html",
                    "".join(self.editor(n, data) for n, data in sources.items()),
                )
                report = v.package_integrity(self.d, self.root)
                self.assertEqual(report["status"], "success")
                self.assertEqual(report["questionBindings"][0]["method"], "manual")

    def test_manual_editor_rejects_missing_mirror_or_substituted_source(self) -> None:
        fixtures.payload(self.d, self.q)["submission"] = {"mode": "editor"}
        self.put(
            "questions/" + self.q + "/question.html",
            self.editor("Real.java", b"class Fake {}"),
        )
        with self.assertRaises(g.JobError):
            v.package_integrity(self.d, self.root)
        self.manual_starters({"Real.java": b"class Real {}"})
        with self.assertRaises(g.JobError):
            v.package_integrity(self.d, self.root)

    def test_manual_editor_keeps_unicode_transport(self) -> None:
        data = "// Ёж\nclass Real {}".encode("utf-8")
        self.manual_starters({"Real.java": data})
        fixtures.payload(self.d, self.q)["submission"] = {"mode": "editor"}
        self.put(
            "questions/" + self.q + "/question.html",
            self.editor("Real.java", data).replace(' normalize-to-ascii="false"', ""),
        )
        with self.assertRaises(g.JobError):
            v.package_integrity(self.d, self.root)

    def test_manual_editor_rejects_nul_oversize_and_private_grader(self) -> None:
        fixtures.payload(self.d, self.q)["submission"] = {"mode": "editor"}
        for data in [b"class Real {}\0", b" " * (1048576 + 1)]:
            with self.subTest(size=len(data)):
                self.manual_starters({"Real.java": data})
                self.put(
                    "questions/" + self.q + "/question.html",
                    self.editor("Real.java", data),
                )
                with self.assertRaises(g.JobError):
                    v.package_integrity(self.d, self.root)
        data = b"class Real {}"
        self.manual_starters({"Real.java": data})
        self.put(
            "questions/" + self.q + "/question.html", self.editor("Real.java", data)
        )
        self.put("questions/" + self.q + "/tests/grading-job.json", {})
        with self.assertRaises(g.JobError):
            v.package_integrity(self.d, self.root)

    def test_manual_java_uses_exclusive_flat_files_or_tree_zip(self) -> None:
        sources = {
            name: ("class " + name[:-5] + " {}").encode()
            for name in ["A.java", "B.java", "C.java"]
        }
        self.manual_starters(sources)
        fixtures.payload(self.d, self.q)["submission"] = {
            "mode": "upload",
            "layout": "files",
        }
        self.put(
            "questions/" + self.q + "/question.html",
            '<pl-file-upload file-names="A.java,B.java,C.java"></pl-file-upload>',
        )
        self.assertEqual(v.package_integrity(self.d, self.root)["status"], "success")
        self.put(
            "questions/" + self.q + "/question.html",
            '<pl-file-upload file-names="A.java,B.java,C.java" optional-file-names="solution.zip"></pl-file-upload>',
        )
        with self.assertRaises(g.JobError):
            v.package_integrity(self.d, self.root)
        for path in (
            self.root / ("questions/" + self.q + "/serverFilesQuestion/starter")
        ).iterdir():
            path.unlink()
        self.manual_starters({"pkg/" + name: data for name, data in sources.items()})
        fixtures.payload(self.d, self.q)["submission"] = {
            "mode": "upload",
            "layout": "zip",
        }
        self.put(
            "questions/" + self.q + "/question.html",
            '<pl-file-upload file-names="solution.zip"></pl-file-upload>',
        )
        self.assertEqual(v.package_integrity(self.d, self.root)["status"], "success")
        self.put(
            "questions/" + self.q + "/question.html",
            '<pl-file-upload file-names="other.zip"></pl-file-upload>',
        )
        with self.assertRaises(g.JobError):
            v.package_integrity(self.d, self.root)


if __name__ == "__main__":
    unittest.main()
