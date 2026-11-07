"""CLI проверяет реальные Native controls и сообщает факты исполнения без receipt."""
import json,subprocess,sys,unittest
from pathlib import Path
import test_delivery5 as fixtures
ROOT=Path(__file__).resolve().parents[1]
class CheckCourse(unittest.TestCase):
 manifest: dict[str,object]
 def setUp(self) -> None:
  self.fixture=fixtures.Delivery5();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
  self.root=self.fixture.root;self.manifest={'schemaVersion':3,'courseId':'demo','bookRoot':'tasks','projects':[]}
 def run_check(self,*args: str) -> tuple[subprocess.CompletedProcess[str],dict[str,object]]:
  manifest=self.root/'private-checks.json';manifest.write_text(json.dumps(self.manifest));delivery=self.root/'delivery.json';delivery.write_text(json.dumps(self.fixture.d));output=self.root/'report.json'
  run=subprocess.run([sys.executable,str(ROOT/'tools/check-course.py'),'verify','--manifest',str(manifest),'--scope','delivery','--delivery',str(delivery),'--output',str(output),*args],capture_output=True,text=True)
  return run,fixtures.record(json.loads(output.read_text()))
 def test_manual_package_reports_controls_without_automatic_job_score_or_receipt(self) -> None:
  run,report=self.run_check();self.assertEqual(run.returncode,0,report);self.assertEqual(fixtures.record(report['automatic'])['state'],'not-applicable');self.assertEqual(report['results'],[]);self.assertNotIn('receipt',report);self.assertNotIn('Hash',json.dumps(report));self.assertEqual(fixtures.record(report['packageIntegrity'])['status'],'success')
 def test_unknown_native_question_is_tool_failure(self) -> None:
  run,report=self.run_check('--id','demo/exr-unknown');self.assertEqual(run.returncode,2);self.assertEqual(report['classification'],'infrastructure-failure')
 def test_selected_manual_scenario_is_partial_diagnostic(self) -> None:
  run,report=self.run_check('--scenario','starter');self.assertEqual(run.returncode,1);self.assertEqual(report['coverage'],'partial');self.assertNotIn('receipt',report)
 def test_unsafe_native_controls_never_become_zero_score(self) -> None:
  self.fixture.put('questions/'+self.fixture.q+'/question.html','<p>Нет ввода</p>');run,report=self.run_check();self.assertEqual(run.returncode,2);self.assertNotIn('score',report)
if __name__=='__main__':unittest.main()
