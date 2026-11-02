"""Точечные hooks в pinned Community grading; без общего interceptor/daemon."""
from pathlib import Path
import sys,hashlib
PINNED={'grading': ['b2b31be8a082c36a9d4e481150b8dd6c0cac930d724bef5f51be0d030091f3fb', 'f032b127cdc92f053cf24eb78533e3fce2977c73dccfacaecea42b546e8633e7'], 'assessment-grading': ['71b0aa36b8f5356445850c909ccd3bd194c65ddb87cd7bc576f1ac9184ba0c66', 'b35c3291a9dcedfe69754ec032410eb4ba1000a36ad964809ad07960615843d0'], 'grading-job': ['d6e813fe2dccb286ca37f592e0899474895ce4e1e7275062ed2d08475688f590', 'df226ebcbab9d5993d4b1e08b3bbeece98cf02238ee975461b9e735901f22812'], 'assessment': ['87c99f8bed5e775d3d4d44cc22d7f34408da773a53f8ff456426073f95b6facd', '7c89366426b68367b7d778fe290ac06bd66d0f3dd675600a365856cedaa13117'], 'manualGrading': ['936ba0b00e5df70f886e640e26d6efcdec47a6caeb2fbfed51f7ef9938b2f54c', 'be841938fd2004739f3ca24073161f239a6600a8341216eb948c705963424743']}
IMPORT="import { applyRecognizedCredit } from '../../bridge/recognized-credit-native.mjs';\n"
def once(source,old,new):
    if source.count(old)!=1:raise ValueError('Pinned Community boundary differs: '+old[:80])
    return source.replace(old,new,1)
def patch(source,kind):
    if hashlib.sha256(source.encode()).hexdigest() not in PINNED.get(kind,[]):raise ValueError('Exact pinned native source/compiled file differs')
    if 'recognized-credit-native.mjs' in source:raise ValueError('Already patched; no duplicate hooks')
    if kind=='manualGrading':
        if source.count('export async function updateInstanceQuestionScore(')!=1:raise ValueError('Pinned native manual grading entrypoint differs')
        return source+"\nexport { recognizeCredit as recognizePreviousCredit } from '../../bridge/recognized-credit-native.mjs';\n"
    if kind=='grading':
        anchor='return { submission_id, variant };'
        hook="if (variant.assessment_instance_id != null) { await applyRecognizedCredit({ assessment_instance_id: variant.assessment_instance_id }); }\n    "
        source=once(source,anchor,hook+anchor)
    elif kind=='assessment-grading':
        anchor='if (credit == null) {'
        hook="const recognizedCreditCount = await applyRecognizedCredit({ assessment_instance_id });\n    if (recognizedCreditCount > 0) precomputedPointsByZone = undefined;\n    "
        source=once(source,anchor,hook+anchor)
        # Match native manual grading credit:100, bounded by trusted AI events.
        # Keep native points/maxima and existing bonus credit; no force-max.
        anchor='const instanceQuestionsUsedForGrade ='
        source=once(source,anchor,'if (recognizedCreditCount > 0) credit = Math.max(credit, 100);\n        '+anchor)
    elif kind=='grading-job':
        anchor='return gradingJob;'
        hook="if (!gradable && assessment_instance_id != null && instance_question_id != null) {\n      const recognizedCreditCount = await applyRecognizedCredit({ assessment_instance_id });\n      if (recognizedCreditCount > 0) await updateAssessmentInstanceGrade({ assessment_instance_id, authn_user_id: gradingJob.auth_user_id, credit });\n    }\n    "
        source=once(source,anchor,hook+anchor)
    elif kind=='assessment':
        anchor='const pointsByZone = await computeAssessmentInstanceScoreByZone({ assessment_instance_id });'
        hook='await applyRecognizedCredit({ assessment_instance_id });\n    '
        source=once(source,anchor,hook+anchor)
    else:raise ValueError('Unknown exact native boundary')
    return IMPORT+source
if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--stdin':sys.stdout.write(patch(sys.stdin.read(),sys.argv[2]))
    elif len(sys.argv)==2:
        root=Path(sys.argv[1]);outputs={}
        for subtree in('src','dist'):
            for kind,folder in [('grading','lib'),('assessment-grading','lib'),('grading-job','models'),('assessment','lib'),('manualGrading','lib')]:
                p=root/subtree/folder/(kind+('.ts' if subtree=='src'else'.js'));outputs[p]=patch(p.read_text(),kind)
        # All ten boundaries must match before any file is changed.
        for p,text in outputs.items():p.write_text(text)
    else:raise SystemExit('Usage: --stdin exact-kind OR exact PrairieLearn app root')
