"""Точечные hooks в pinned Community grading; без общего interceptor/daemon."""

from pathlib import Path
import sys

IMPORT = "import { applyRecognizedCredit } from '../../bridge/recognized-credit-native.mjs';\n"


def once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError("Pinned Community boundary differs: " + old[:80])
    return source.replace(old, new, 1)


def patch(source: str, kind: str) -> str:
    if "recognized-credit-native.mjs" in source:
        raise ValueError("Already patched; no duplicate hooks")
    if kind == "manualGrading":
        if source.count("export async function updateInstanceQuestionScore(") != 1:
            raise ValueError("Pinned native manual grading entrypoint differs")
        return (
            source
            + "\nexport { recognizeCredit as recognizePreviousCredit } from '../../bridge/recognized-credit-native.mjs';\n"
        )
    if kind == "grading":
        anchor = "return { submission_id, variant };"
        hook = "if (variant.assessment_instance_id != null) { await applyRecognizedCredit({ assessment_instance_id: variant.assessment_instance_id }); }\n    "
        source = once(source, anchor, hook + anchor)
    elif kind == "assessment-grading":
        anchor = "if (credit == null) {"
        hook = "const recognizedCreditCount = await applyRecognizedCredit({ assessment_instance_id });\n    if (recognizedCreditCount > 0) precomputedPointsByZone = undefined;\n    "
        source = once(source, anchor, hook + anchor)
        # Match native manual grading credit:100, bounded by trusted AI events.
        # Keep native points/maxima and existing bonus credit; no force-max.
        anchor = "const instanceQuestionsUsedForGrade ="
        source = once(
            source,
            anchor,
            "if (recognizedCreditCount > 0) credit = Math.max(credit, 100);\n        "
            + anchor,
        )
    elif kind == "grading-job":
        anchor = "return gradingJob;"
        hook = "if (!gradable && assessment_instance_id != null && instance_question_id != null) {\n      const recognizedCreditCount = await applyRecognizedCredit({ assessment_instance_id });\n      if (recognizedCreditCount > 0) await updateAssessmentInstanceGrade({ assessment_instance_id, authn_user_id: gradingJob.auth_user_id, credit });\n    }\n    "
        source = once(source, anchor, hook + anchor)
    elif kind == "assessment":
        anchor = "const pointsByZone = await computeAssessmentInstanceScoreByZone({ assessment_instance_id });"
        hook = "await applyRecognizedCredit({ assessment_instance_id });\n    "
        source = once(source, anchor, hook + anchor)
    else:
        raise ValueError("Unknown exact native boundary")
    return IMPORT + source


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--stdin":
        sys.stdout.write(patch(sys.stdin.read(), sys.argv[2]))
    elif len(sys.argv) == 2:
        root = Path(sys.argv[1])
        outputs: dict[Path, str] = {}
        for subtree in ("src", "dist"):
            for kind, folder in [
                ("grading", "lib"),
                ("assessment-grading", "lib"),
                ("grading-job", "models"),
                ("assessment", "lib"),
                ("manualGrading", "lib"),
            ]:
                p = (
                    root
                    / subtree
                    / folder
                    / (kind + (".ts" if subtree == "src" else ".js"))
                )
                outputs[p] = patch(p.read_text(), kind)
        # All ten boundaries must match before any file is changed.
        for p, text in outputs.items():
            p.write_text(text)
    else:
        raise SystemExit("Usage: --stdin exact-kind OR exact PrairieLearn app root")
