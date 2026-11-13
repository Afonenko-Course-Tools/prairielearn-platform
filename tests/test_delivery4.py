"""Типизированные Native-ответы сохраняют controls и приватный ключ в delivery v5."""

import json
import sys
import unittest
from pathlib import Path
import test_delivery5 as fixtures

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import delivery_verification as v
import grading_job as g
from delivery4 import code_ids


class NativeAnswers(fixtures.DeliveryFixture):
    def native(self, kind: str) -> None:
        binding: dict[str, object] = {
            "kind": "native-answer",
            "uuid": fixtures.payload(self.d, self.q)["uuid"],
            "grading": {"method": "manual" if kind == "manual" else "external"},
            "answerType": kind,
            "responseSlots": [{"name": "answer", "type": kind, "anchor": "answer"}],
            "upstreamGradingMethod": "Manual" if kind == "manual" else "Internal",
        }
        fixtures.record(self.d["gradingPayloads"])[self.q] = binding
        info = self.read_json("questions/" + self.q + "/info.json")
        info.update(
            gradingMethod=binding["upstreamGradingMethod"],
            partialCredit=kind != "manual",
        )
        self.put("questions/" + self.q + "/info.json", info)
        self.put(
            "questions/" + self.q + "/question.html",
            '<pl-rich-text-editor file-name="answer.html" placeholder="Ответ"></pl-rich-text-editor>'
            if kind == "manual"
            else '<pl-string-input answers-name="answer" allow-blank="true"></pl-string-input>',
        )
        self.put("questions/" + self.q + "/server.py", "PRIVATE_NATIVE_ANSWER_KEY")
        a = self.read_json(
            "courseInstances/fixture/assessments/lab/infoAssessment.json"
        )
        fixtures.records(fixtures.records(a["zones"])[0]["questions"])[0] = {
            "id": self.q,
            **(
                {"manualPoints": 2, "autoPoints": 0}
                if kind == "manual"
                else {"points": 2}
            ),
        }
        self.put("courseInstances/fixture/assessments/lab/infoAssessment.json", a)
        self.d["files"] = sorted(
            p.relative_to(self.root).as_posix()
            for p in self.root.rglob("*")
            if p.is_file()
        )

    def test_native_internal_answer_is_not_a_code_grading_job_or_public_key(
        self,
    ) -> None:
        self.native("numeric")
        self.assertEqual(code_ids(self.d), set())
        report = v.package_integrity(self.d, self.root)
        self.assertEqual(report["status"], "success")
        self.assertNotIn("PRIVATE_NATIVE_ANSWER_KEY", json.dumps(self.d))
        self.assertNotIn("Hash", json.dumps(report))

    def test_manual_native_response_is_explicit_manual(self) -> None:
        self.native("manual")
        self.assertEqual(v.classification(self.d), {self.q: "manual"})
        v.package_integrity(self.d, self.root)

    def test_unbound_controls_and_key_visibility_refuse(self) -> None:
        self.native("numeric")
        self.put(
            "questions/" + self.q + "/question.html",
            '<pl-string-input answers-name="answer" allow-blank="true" correct-answer="PRIVATE"></pl-string-input>',
        )
        with self.assertRaises(g.JobError):
            v.package_integrity(self.d, self.root)
        self.put(
            "questions/" + self.q + "/question.html",
            '<pl-string-input answers-name="answer" allow-blank="true"></pl-string-input>',
        )
        info = self.read_json("questions/" + self.q + "/info.json")
        info["showCorrectAnswer"] = True
        self.put("questions/" + self.q + "/info.json", info)
        with self.assertRaises(g.JobError):
            v.package_integrity(self.d, self.root)

    def test_native_kind_cannot_accept_project_runtime(self) -> None:
        self.native("numeric")
        fixtures.payload(self.d, self.q)["runtime"] = "java25-junit-v1"
        with self.assertRaises(g.JobError):
            v.classification(self.d)


if __name__ == "__main__":
    unittest.main()
