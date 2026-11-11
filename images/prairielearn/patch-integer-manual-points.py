"""Явная opt-in политика ручных баллов для pinned Community source.

После patch обязателен штатный native build: сервер и hydrated browser assets.
Все anchors проверяются до записи; повторное применение — ошибка.
"""
from pathlib import Path
import sys

POLICY = "integerManualPoints"
PANEL = "pages/instructorAssessmentManualGrading/instanceQuestion/"
TABLE = "pages/instructorAssessmentManualGrading/assessmentQuestion/"


def once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError("Pinned integer-points boundary differs: " + old[:100])
    return source.replace(old, new, 1)


def patch(source: str, filename: str) -> str:
    if POLICY in source:
        raise ValueError("Already patched: " + filename)
    if filename == "schemas/infoCourse.ts":
        return once(source, "    devModeFeatures: z", "    integerManualPoints: z.boolean().optional(),\n    devModeFeatures: z")
    if filename == "sync/course-db.ts":
        return once(source, "    options: {\n      devModeFeatures,", "    options: {\n      integerManualPoints: info.options.integerManualPoints ?? false,\n      devModeFeatures,")
    if filename == "lib/manualGrading.ts":
        source = "import { assertIntegerManualPoints } from '../../tools/integer-manual-points.mjs';\n" + source
        anchor = "    let grading_job_id: string | null = null;"
        guard = '''    const pointPolicy = await sqldb.queryRow(
      `SELECT COALESCE((c.options->>'integerManualPoints')::boolean, false) AS integer_manual_points,
              ai.max_points AS assessment_max_points
       FROM assessment_instances AS ai
       JOIN assessments AS a ON a.id = ai.assessment_id
       JOIN course_instances AS ci ON ci.id = a.course_instance_id
       JOIN courses AS c ON c.id = ci.course_id
       WHERE ai.id = $assessment_instance_id AND a.id = $assessment_id`,
      { assessment_instance_id: current_submission.assessment_instance_id, assessment_id: assessment.id },
      z.object({ integer_manual_points: z.boolean(), assessment_max_points: z.number().nullable() }),
    );
    if (pointPolicy.integer_manual_points) {
      assertIntegerManualPoints(pointPolicy.assessment_max_points, current_submission.max_manual_points, null);
      assertIntegerManualPoints(current_submission.max_points,
        current_submission.max_manual_points, new_manual_points);
    }

'''

        return once(source, anchor, guard + anchor)
    if filename == PANEL + "components/InstanceQuestionGradingPanel.types.ts":
        return once(source, "  context: ManualGradingContext;", "  integerManualPoints?: boolean;\n  context: ManualGradingContext;")
    if filename == PANEL + "instanceQuestion.html.tsx":
        return once(source, "  return {\n    context,", "  return {\n    integerManualPoints: resLocals.course.options?.integerManualPoints === true,\n    context,")
    if filename == PANEL + "components/InstanceQuestionGradingPanel.tsx":
        source = once(source, "const usePercentage = maxPoints > 0 && preferPercentage;", "const usePercentage = !data.integerManualPoints && maxPoints > 0 && preferPercentage;")
        source = once(source, "        {maxPoints > 0 && (", "        {maxPoints > 0 && !data.integerManualPoints && (")
        source = once(source, '            label="Manual"', '            integerManualPoints={data.integerManualPoints}\n            label="Manual"')
        return once(source, "      adjustmentInputRef={adjustmentInputRef}", "      integerManualPoints={data.integerManualPoints}\n      adjustmentInputRef={adjustmentInputRef}")
    if filename in [PANEL + "components/GradingPoints.tsx", PANEL + "components/RubricInput.tsx"]:
        source = once(source, "  context,", "  integerManualPoints = false,\n  context,")
        source = once(source, "  context: ", "  integerManualPoints?: boolean;\n  context: ")
        source = once(source, 'step="any"', 'step={integerManualPoints ? 1 : "any"}')
        if filename.endswith("GradingPoints.tsx"):
            source = once(source, "            disabled={disabled}", "            min={integerManualPoints ? 0 : undefined}\n            max={integerManualPoints ? maxPoints : undefined}\n            disabled={disabled}")
        return source
    if filename == "components/EditQuestionPointsScore.tsx":
        # Four components pass policy explicitly, including the legacy HTML popover.
        for name in ["EditQuestionPointsScoreButtonHtml", "EditQuestionPointsScoreFormHtml", "EditQuestionPointsScoreForm", "EditQuestionPointsScoreButton"]:
            source = once(source, f"function {name}({{\n  field,", f"function {name}({{\n  integerManualPoints = false,\n  field,")
        source = source.replace("  field: ", "  integerManualPoints?: boolean;\n  field: ")
        source = once(source, "  const editForm = EditQuestionPointsScoreFormHtml({", "  const editForm = EditQuestionPointsScoreFormHtml({\n    integerManualPoints,")
        source = once(source, "          <EditQuestionPointsScoreForm\n", "          <EditQuestionPointsScoreForm\n            integerManualPoints={integerManualPoints}\n")
        source = once(source, '            step="any"\n            class="form-control"', '            class="form-control"\n            step="${integerManualPoints && field === \'manual_points\' ? 1 : \'any\'}"\n            min="${integerManualPoints && field === \'manual_points\' ? 0 : \'\'}"\n            max="${integerManualPoints && field === \'manual_points\' ? maxPoints : \'\'}"')
        return once(source, '            step="any"', '            step={integerManualPoints && field === "manual_points" ? 1 : "any"}\n            min={integerManualPoints && field === "manual_points" ? 0 : undefined}\n            max={integerManualPoints && field === "manual_points" ? maxPoints ?? 0 : undefined}')
    if filename == "pages/instructorAssessmentInstance/instructorAssessmentInstance.html.tsx":
        return once(source, "                                    field: 'manual_points',", "                                    integerManualPoints: resLocals.course.options?.integerManualPoints === true,\n                                    field: 'manual_points',")
    if filename == TABLE + "components/AssessmentQuestionTable.tsx":
        return once(source, "      createColumns({", "      createColumns({\n        integerManualPoints: course.options?.integerManualPoints === true,")
    if filename == TABLE + "utils/columnDefinitions.tsx":
        source = once(source, "interface CreateColumnsParams {", "interface CreateColumnsParams {\n  integerManualPoints?: boolean;")
        source = once(source, "export function createColumns({", "export function createColumns({\n  integerManualPoints,")
        return once(source, "    <PointsWithEditButton\n", "    <PointsWithEditButton\n      integerManualPoints={integerManualPoints}\n")
    if filename == TABLE + "utils/columnUtils.tsx":
        source = once(source, "export function PointsWithEditButton({", "export function PointsWithEditButton({\n  integerManualPoints,")
        source = once(source, "  field: 'manual_points' | 'auto_points' | 'points';", "  integerManualPoints?: boolean;\n  field: 'manual_points' | 'auto_points' | 'points';")
        return once(source, "          field={field}", "          integerManualPoints={integerManualPoints}\n          field={field}")
    raise ValueError("Unknown boundary: " + filename)


FILES = [
    "schemas/infoCourse.ts", "sync/course-db.ts", "lib/manualGrading.ts",
    PANEL + "components/InstanceQuestionGradingPanel.types.ts",
    PANEL + "instanceQuestion.html.tsx",
    PANEL + "components/InstanceQuestionGradingPanel.tsx",
    PANEL + "components/GradingPoints.tsx", PANEL + "components/RubricInput.tsx",
    "components/EditQuestionPointsScore.tsx",
    "pages/instructorAssessmentInstance/instructorAssessmentInstance.html.tsx",
    TABLE + "components/AssessmentQuestionTable.tsx",
    TABLE + "utils/columnDefinitions.tsx", TABLE + "utils/columnUtils.tsx",
]


def apply(root: Path) -> None:
    outputs = {root / "src" / name: patch((root / "src" / name).read_text(), name) for name in FILES}
    for path, content in outputs.items():
        path.write_text(content)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: patch-integer-manual-points.py PRAIRIELEARN_APP_ROOT")
    apply(Path(sys.argv[1]))
