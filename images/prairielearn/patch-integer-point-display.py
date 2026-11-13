"""Course-scoped представление баллов; исходные результаты не округляются."""

from pathlib import Path
import sys
import importlib.util

SPEC = importlib.util.spec_from_file_location(
    "manual_points_patch", Path(__file__).with_name("patch-integer-manual-points.py")
)
assert SPEC is not None and SPEC.loader is not None
MANUAL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MANUAL)
once = MANUAL.once
PANEL = MANUAL.PANEL
TABLE = MANUAL.TABLE


def add_policy_calls(source: str, name: str, value: str) -> str:
    anchor = name + "({\n"
    if anchor not in source:
        raise ValueError("Missing display caller: " + name)
    return source.replace(anchor, anchor + value + ",\n")


def patch(source: str, filename: str) -> str:
    if "formatCoursePoints" in source:
        raise ValueError("Already display-patched: " + filename)
    if filename == "lib/format.ts":
        return (
            "import { displayIntegerPoints } from '../../tools/integer-manual-points.mjs';\n"
            + source
            + """
export function formatCoursePoints(value: number | null, integerManualPoints = false) {
  return integerManualPoints ? displayIntegerPoints(value) : formatPoints(value);
}
"""
        )
    if filename == "components/QuestionScore.tsx":
        source = once(
            source,
            "import { formatPoints }",
            "import { formatPoints, formatCoursePoints }",
        )
        source = once(
            source,
            "interface QuestionScorePanelContentProps {",
            "interface QuestionScorePanelContentProps {\n  integerManualPoints?: boolean;",
        )
        source = once(
            source,
            "export function QuestionScorePanelContent({",
            "export function QuestionScorePanelContent({\n  integerManualPoints = false,",
        )
        source = add_policy_calls(
            source, "InstanceQuestionPoints", "integerManualPoints"
        )
        source = once(
            source,
            "export function InstanceQuestionPoints({\nintegerManualPoints,",
            "export function InstanceQuestionPoints({\nintegerManualPoints = false,",
        )
        source = once(
            source,
            "  component: 'manual' | 'auto' | 'total';",
            "  integerManualPoints?: boolean;\n  component: 'manual' | 'auto' | 'total';",
        )
        source = once(
            source,
            "formatPoints(points)",
            "formatCoursePoints(points, integerManualPoints)",
        )
        return once(
            source,
            "${maxPoints}</span></small>",
            "${integerManualPoints ? formatCoursePoints(maxPoints, true) : maxPoints}</span></small>",
        )
    if filename == "components/AssessmentScorePanel.tsx":
        source = once(
            source, "import { formatPoints }", "import { formatCoursePoints }"
        )
        source = once(
            source,
            "export function AssessmentScorePanel({",
            "export function AssessmentScorePanel({\n  integerManualPoints = false,",
        )
        source = once(
            source,
            "  assessment_instance: AssessmentInstance;",
            "  integerManualPoints?: boolean;\n  assessment_instance: AssessmentInstance;",
        )
        source = once(
            source,
            "formatPoints(assessment_instance.points)",
            "formatCoursePoints(assessment_instance.points, integerManualPoints)",
        )
        return once(
            source,
            "assessment_instance.max_points,",
            "assessment_instance.max_points, integerManualPoints,",
        ).replace("formatPoints(", "formatCoursePoints(")
    if filename in [
        "pages/studentInstanceQuestion/studentInstanceQuestion.html.ts",
        "lib/question-render.ts",
    ]:
        value = "integerManualPoints: " + (
            "resLocals.course.options?.integerManualPoints === true"
            if filename.startswith("pages/")
            else "course.options?.integerManualPoints === true"
        )
        for name in [
            "AssessmentScorePanel",
            "QuestionScorePanel"
            if filename.startswith("pages/")
            else "QuestionScorePanelContent",
        ]:
            source = add_policy_calls(source, name, value)
        return source
    if filename == "pages/studentAssessmentInstance/studentAssessmentInstance.html.tsx":
        source = once(
            source, "import { formatPoints }", "import { formatCoursePoints }"
        )
        source = once(
            source,
            "  let savedAnswers = 0;",
            "  const formatPoints = (value: number | null) => formatCoursePoints(value, resLocals.course.options?.integerManualPoints === true);\n  let savedAnswers = 0;",
        )
        return add_policy_calls(
            source,
            "QuestionTableBody",
            "integerManualPoints: resLocals.course.options?.integerManualPoints === true",
        )
    if filename == "pages/studentAssessmentInstance/components/QuestionTableBody.tsx":
        source = once(
            source, "import { formatPoints }", "import { formatCoursePoints }"
        )
        for name in ["QuestionTableBody", "ExamQuestionCells", "HomeworkQuestionCells"]:
            source = once(
                source,
                "function " + name + "({\n",
                "function " + name + "({\n  integerManualPoints = false,\n",
            )
        source = once(
            source,
            "  rows: InstanceQuestionRow[];",
            "  integerManualPoints?: boolean;\n  rows: InstanceQuestionRow[];",
        )
        if source.count("  row: InstanceQuestionRow;") != 2:
            raise ValueError("Table helper boundaries differ")
        source = source.replace(
            "  row: InstanceQuestionRow;",
            "  integerManualPoints?: boolean;\n  row: InstanceQuestionRow;",
        )
        # The main function has no formatter; its two cell helpers each use the policy.
        source = source.replace(
            "}) {\n  return html`",
            "}) {\n  const formatPoints = (value: number | null) => formatCoursePoints(value, integerManualPoints);\n  return html`",
            2,
        )
        for name in [
            "ExamQuestionCells",
            "HomeworkQuestionCells",
            "InstanceQuestionPoints",
        ]:
            anchor = name + "({\n"
            source = source.replace(anchor, anchor + "integerManualPoints,\n")
            # Restore destructuring defaults in declarations, not call sites.
            source = source.replace(
                "function "
                + name
                + "({\nintegerManualPoints,\n  integerManualPoints = false,",
                "function " + name + "({\n  integerManualPoints = false,",
            )
        return source
    if (
        filename
        == "pages/instructorAssessmentInstance/instructorAssessmentInstance.html.tsx"
    ):
        source = once(
            source,
            "import { formatFloat, formatPoints }",
            "import { formatFloat, formatCoursePoints }",
        )
        source = source.replace(
            "formatPoints(resLocals.assessment_instance.points)",
            "formatCoursePoints(resLocals.assessment_instance.points, resLocals.course.options?.integerManualPoints === true)",
        )
        source = source.replace(
            "formatPoints(resLocals.assessment_instance.max_points)",
            "formatCoursePoints(resLocals.assessment_instance.max_points, resLocals.course.options?.integerManualPoints === true)",
        )
        return add_policy_calls(
            source,
            "InstanceQuestionPoints",
            "integerManualPoints: resLocals.course.options?.integerManualPoints === true",
        )
    if filename == PANEL + "components/GradingPoints.tsx":
        source = (
            "import { formatCoursePoints } from '../../../../lib/format.js';\n" + source
        )
        # Preserve exact automatic values: a manual save must not re-submit rounded hidden values.
        hidden = "\n          disabled={disabled}"
        if source.count(hidden) != 2:
            raise ValueError("Hidden score fields differ")
        source = source.replace(
            hidden,
            "\n          disabled={disabled || (integerPointDisplay && type === 'auto' && !editing)}",
        )
        # Both display components get a display-only flag, independent from input validation.
        for name in ["GradingPoints", "TotalPoints"]:
            source = once(
                source,
                "function " + name + "({",
                "function " + name + "({\n  integerPointDisplay = false,",
            )
        if source.count("  maxPoints: number;") != 2:
            raise ValueError("Point display component boundaries differ")
        source = source.replace(
            "  maxPoints: number;",
            "  integerPointDisplay?: boolean;\n  maxPoints: number;",
        )
        source = once(
            source,
            "{pointsValue} / {maxPoints}",
            "{integerPointDisplay ? formatCoursePoints(Number(pointsValue), true) : pointsValue} / {integerPointDisplay ? formatCoursePoints(maxPoints, true) : maxPoints}",
        )
        return once(
            source,
            "`${pointsValue} / ${maxPoints}`",
            "`${integerPointDisplay ? formatCoursePoints(Number(pointsValue), true) : pointsValue} / ${integerPointDisplay ? formatCoursePoints(maxPoints, true) : maxPoints}`",
        )
    if filename == PANEL + "components/InstanceQuestionGradingPanel.tsx":
        source = once(
            source,
            "  const totalPoints = roundPoints(\n    Number(formState.autoPoints || 0) + Number(formState.manualPoints || 0),\n  );",
            "  const rawTotalPoints = Number(formState.autoPoints || 0) + Number(formState.manualPoints || 0);\n  const totalPoints = data.integerManualPoints ? rawTotalPoints : roundPoints(rawTotalPoints);",
        )
        source = once(
            source,
            "pointsValue={pointsValue(totalPoints)}",
            "pointsValue={data.integerManualPoints ? String(totalPoints) : pointsValue(totalPoints)}",
        )
        # JSX call sites only; the raw number strings in controlled inputs stay untouched.
        source = source.replace(
            "<GradingPoints\n",
            "<GradingPoints\n                integerPointDisplay={data.integerManualPoints}\n",
        )
        return once(
            source,
            "<TotalPoints\n",
            "<TotalPoints\n                integerPointDisplay={data.integerManualPoints}\n",
        )
    if filename == PANEL + "utils/gradingPanelState.ts":
        return once(
            source,
            "autoPoints: current?.autoPoints ?? pointsValue(data.instanceQuestion.autoPoints),",
            "autoPoints: current?.autoPoints ?? (data.integerManualPoints ? String(data.instanceQuestion.autoPoints) : pointsValue(data.instanceQuestion.autoPoints)),",
        )
    if filename == TABLE + "utils/columnUtils.tsx":
        source = once(
            source, "import { formatPoints }", "import { formatCoursePoints }"
        )
        source = once(
            source,
            "formatPoints(points)",
            "formatCoursePoints(points, integerManualPoints)",
        )
        return once(
            source,
            "{maxPoints}</span>",
            "{integerManualPoints ? formatCoursePoints(maxPoints, true) : maxPoints}</span>",
        )
    raise ValueError("Unknown display boundary: " + filename)


FILES = [
    "lib/format.ts",
    "components/QuestionScore.tsx",
    "components/AssessmentScorePanel.tsx",
    "pages/studentInstanceQuestion/studentInstanceQuestion.html.ts",
    "lib/question-render.ts",
    "pages/studentAssessmentInstance/studentAssessmentInstance.html.tsx",
    "pages/studentAssessmentInstance/components/QuestionTableBody.tsx",
    "pages/instructorAssessmentInstance/instructorAssessmentInstance.html.tsx",
    PANEL + "components/GradingPoints.tsx",
    PANEL + "components/InstanceQuestionGradingPanel.tsx",
    TABLE + "utils/columnUtils.tsx",
    PANEL + "utils/gradingPanelState.ts",
]


def apply(root: Path) -> None:
    outputs = {
        root / "src" / name: patch((root / "src" / name).read_text(), name)
        for name in FILES
    }
    for path, content in outputs.items():
        path.write_text(content)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch-integer-point-display.py PRAIRIELEARN_APP_ROOT")
    apply(Path(sys.argv[1]))
