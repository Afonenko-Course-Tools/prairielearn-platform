"""Реальный Quarto owner export из synthetic private stage; без запуска grader."""
import importlib.util,json,os,shutil,subprocess,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('private_source',ROOT/'tools/prepare-private-source.py');stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)
spec=importlib.util.spec_from_file_location('builder',ROOT/'tools/build-course.py');builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
@unittest.skipUnless(os.environ.get('CORE') and os.environ.get('EXPORTER'),'Укажите candidate CORE и EXPORTER для native integration')
class NativePrivateSource(unittest.TestCase):
 def test_real_owner_export_and_runtime_provenance(self):
  with tempfile.TemporaryDirectory(prefix='private-source-native-') as d:
   root=Path(d);public=root/'public';exporter=Path(os.environ['EXPORTER']);shutil.copytree(exporter/'examples/native-course',public)
   teacher=root/'teacher';project=public/'tasks/projects/add'
   for partition in ['reference','tests']:
    target=teacher/'projects/add'/partition;target.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(project/partition),target)
   (public/'.gitignore').write_text('.quarto/\n**/.quarto/\n**/_generated/\n')
   def run(args,cwd=public):
    result=subprocess.run(args,cwd=cwd,text=True,capture_output=True)
    self.assertEqual(result.returncode,0,result.stdout+result.stderr)
   run(['quarto','add',os.environ['CORE'],'--no-prompt'],public/'tasks');run(['quarto','add',str(exporter),'--no-prompt'],public/'tasks')
   for args in [['init','-q'],['remote','add','origin','https://example.invalid/synthetic-course.git'],['add','.'],['-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','Synthetic public source']]:run(['git',*args])
   run(['quarto','run',str(public/'tasks/_extensions/course-core/entrypoints/export.ts'),'--','--book','tasks','--work','sec-add','--output',str(root/'capture.json')])
   materialized=root/'materialized'
   run(['quarto','run',str(public/'tasks/_extensions/course-core/entrypoints/materialize-projects.ts'),'--','--root',str(public/'tasks'),'--model',str(public/'tasks/_generated/course-spec/native-run.json'),'--output-root',str(materialized),'--audience','grading','--teacher-root',str(teacher),'--task','exr-add','--write'])
   private=root/'private';receipt=root/'receipt.json';stage.prepare(public,'tasks',materialized,private,receipt)
   candidate=root/'native';builder.build_course(private,'tasks','pilot',candidate,staging_receipt=receipt)
   provenance=json.loads((candidate/'provenance.json').read_text())['source']
   self.assertEqual(provenance['mode'],'private-stage');self.assertTrue(provenance['runtimeInventory']);self.assertTrue((candidate/'questions/native-java-demo/exr-add/info.json').exists())
   self.assertFalse((public/'tasks/projects/add/reference').exists());stage.validate(private,receipt,allow_runtime=True)
   if os.environ.get('PRIVATE_SOURCE_EVIDENCE'):
    evidence=Path(os.environ['PRIVATE_SOURCE_EVIDENCE']);evidence.mkdir(parents=True,exist_ok=True)
    for name,path in [('staging-receipt.json',receipt),('materialization.json',materialized/'materialization.json'),('provenance.json',candidate/'provenance.json')]:shutil.copyfile(path,evidence/name)
    (evidence/'native-files.json').write_text(json.dumps(stage.inventory(candidate),sort_keys=True,indent=2)+'\n')
