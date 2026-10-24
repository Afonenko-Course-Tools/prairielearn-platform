"""Реальный Quarto owner export из synthetic private stage; без запуска grader."""
from gradle_unit_fixtures import write_registry as unit_registry_file
import importlib.util,json,os,shutil,subprocess,tempfile,unittest,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('private_source',ROOT/'tools/prepare-private-source.py');stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)
spec=importlib.util.spec_from_file_location('builder',ROOT/'tools/build-course.py');builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
@unittest.skipUnless(os.environ.get('CORE') and os.environ.get('EXPORTER') and os.environ.get('DOWNLOAD'),'Укажите candidate CORE, EXPORTER и DOWNLOAD для native integration')
class NativePrivateSource(unittest.TestCase):
 def test_real_owner_export_and_runtime_provenance(self):
  with tempfile.TemporaryDirectory(prefix='private-source-native-') as d:
   root=Path(d);public=root/'public';exporter=Path(os.environ['EXPORTER']);shutil.copytree(exporter/'examples/native-course',public)
   teacher=root/'teacher';project=public/'tasks/projects/add'
   for partition in ['reference','tests']:
    target=teacher/'projects/add'/partition;target.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(project/partition),target)
   config=public/'tasks/_quarto.yml';config.write_text(config.read_text().replace('mode: editor\n      ace-mode: ace/mode/java','mode: upload').replace('project-checks:\n  defaults:\n','project-checks:\n  defaults:\n    feedback: {requirement: "Сложить числа с расширением до long", what-check: "Проверьте тип операции до сложения"}\n    public-cases:\n      - {id: normal, name: "Сложение обычных чисел", test: "AddTest#normal", action: "Сложить 2 и 3", expected: "5"}\n      - {id: boundary, name: "Сложение нулей", test: "AddTest#boundary", input: "0 0", expected: "0"}\n'))
   tests=teacher/'projects/add/tests/junit/AddTest.java';tests.write_text(tests.read_text().replace('final class AddTest {','final class AddTest {\n @Test void normal(org.junit.jupiter.api.TestReporter reporter){long actual=demo.Add.sum(2,3);reporter.publishEntry(java.util.Map.of("public-case","normal","actual",Long.toString(actual)));assertEquals(5L,actual); }\n @Test void boundary(org.junit.jupiter.api.TestReporter reporter){long actual=demo.Add.sum(0,0);reporter.publishEntry(java.util.Map.of("public-case","boundary","actual",Long.toString(actual)));assertEquals(0L,actual); }'))
   (project/'student/README.md').write_text('Публичная инструкция: данные в data/sample.txt\n')
   (project/'student/data').mkdir();(project/'student/data/sample.txt').write_text('PUBLIC_DATA')
   (project/'student/diagram.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"><text>PUBLIC_FIGURE</text></svg>')
   config.write_text(config.read_text().replace('filters: [course-core, course-prairielearn]','filters: [course-core, course-prairielearn, project-download]')+'\nproject-download: {course-model: true}\n')
   lab=public/'tasks/lab.qmd';lab.write_text(lab.read_text().replace('\n::::\n','\n\n{{< project-download exr-add kind="conditions" text="Скачать условие для локального просмотра" >}}\n\n[README](projects/add/student/README.md)\n\n![Схема](projects/add/student/diagram.svg)\n::::\n'))
   reference=teacher/'projects/add/reference/demo/Add.java';reference.write_text(reference.read_text()+'\n// PRIVATE_REFERENCE_CANARY\n')
   (public/'.gitignore').write_text('.quarto/\n**/.quarto/\n**/_generated/\n')
   def run(args,cwd=public):
    result=subprocess.run(args,cwd=cwd,text=True,capture_output=True)
    self.assertEqual(result.returncode,0,result.stdout+result.stderr)
   run(['quarto','add',os.environ['CORE'],'--no-prompt'],public/'tasks');run(['quarto','add',str(exporter),'--no-prompt'],public/'tasks')
   run(['quarto','add',os.environ['DOWNLOAD'],'--no-prompt'],public/'tasks')
   for args in [['init','-q'],['remote','add','origin','https://example.invalid/synthetic-course.git'],['add','.'],['-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','Synthetic public source']]:run(['git',*args])
   run(['quarto','run',str(public/'tasks/_extensions/course-core/entrypoints/export.ts'),'--','--book','tasks','--work','sec-add','--output',str(root/'capture.json')])
   materialized=root/'materialized'
   run(['quarto','run',str(public/'tasks/_extensions/course-core/entrypoints/materialize-projects.ts'),'--','--root',str(public/'tasks'),'--model',str(public/'tasks/_generated/course-spec/native-run.json'),'--output-root',str(materialized),'--audience','grading','--teacher-root',str(teacher),'--task','exr-add','--write'])
   private=root/'private';receipt=root/'receipt.json';stage.prepare(public,'tasks',materialized,private,receipt)
   candidate=root/'native';builder.build_course(private,'tasks','pilot',candidate,staging_receipt=receipt,runtime_registry=unit_registry_file(root))
   provenance=json.loads((candidate/'provenance.json').read_text())['source']
   self.assertEqual(provenance['mode'],'private-stage');self.assertTrue(provenance['runtimeInventory']);self.assertTrue((candidate/'questions/native-java-demo/exr-add/info.json').exists())
   question=candidate/'questions/native-java-demo/exr-add'
   descriptor=json.loads((question/'tests/grading-job.json').read_text());self.assertEqual([c['name'] for c in descriptor['publicCases']],['Сложение обычных чисел','Сложение нулей']);self.assertEqual(descriptor['feedback']['requirement'],'Сложить числа с расширением до long')
   import sys;sys.path.insert(0,str(ROOT/'tools'))
   import delivery_verification as verification
   delivery=json.loads((candidate/'delivery.json').read_text());verification.package_integrity(delivery,candidate)
   html=(question/'question.html').read_text()
   self.assertIn('file-names="demo/Add.java"',html)
   self.assertIn('starter.zip',html);self.assertIn('starter/README.md',html);self.assertIn('{{options.client_files_question_url}}/projects/add/student/diagram.svg',html)
   with zipfile.ZipFile(question/'clientFilesQuestion/starter.zip') as archive:
    self.assertIn('README.md',archive.namelist());self.assertIn('src/main/java/demo/Add.java',archive.namelist());self.assertEqual(archive.read('data/sample.txt'),b'PUBLIC_DATA');self.assertFalse(any('reference' in name or 'tests/' in name for name in archive.namelist()))
   self.assertFalse(any(b'PRIVATE_REFERENCE_CANARY' in path.read_bytes() for path in (question/'clientFilesQuestion').rglob('*') if path.is_file()))
   self.assertFalse((public/'tasks/projects/add/reference').exists());stage.validate(private,receipt,allow_runtime=True)
   # Вторая fresh private stage проверяет реальный optional CLI/consumer с publicBase,
   # отличным от origin-less private Git commit. Первая поставка остаётся baseline.
   self.assertFalse((question/'clientFilesQuestion/exr-add-conditions.zip').exists())
   private2=root/'private-conditions';receipt2=root/'receipt-conditions.json';staged=stage.prepare(public,'tasks',materialized,private2,receipt2)
   self.assertNotEqual(staged['publicBase']['commit'],staged['privateStage']['commit']);self.assertEqual(staged['privateStage']['remotes'],[])
   self.assertEqual(subprocess.check_output(['git','remote'],cwd=private2,text=True).strip(),'')
   accepted=root/'historical-publication.json';accepted.write_text(json.dumps({'fixture':'explicit accepted historical publication','sourceCommit':'b'*40}))
   conditions=root/'exr-add-conditions.zip'
   with zipfile.ZipFile(conditions,'w') as archive:archive.writestr('index.html','<!doctype html><title>Условие</title><p>Публичное условие синтетического курса</p>')
   import hashlib
   def typed(path):return {'path':str(path),'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
   conditions_input=root/'publication-conditions.json';conditions_input.write_text(json.dumps({'schema':'pl-publication-conditions-v1','courseId':'native-java-demo','source':staged['publicBase'],'publication':{'repository':staged['publicBase']['repository'],'commit':'b'*40,'receipt':typed(accepted)},'archives':[{'questionId':'exr-add','source':'lab.qmd','sourceSha256':hashlib.sha256((private2/'tasks/lab.qmd').read_bytes()).hexdigest(),'file':typed(conditions)}]}))
   before=(conditions.read_bytes(),conditions_input.read_bytes(),accepted.read_bytes())
   candidate2=root/'native-conditions';builder.build_course(private2,'tasks','pilot',candidate2,staging_receipt=receipt2,runtime_registry=unit_registry_file(root),publication_conditions=conditions_input)
   self.assertEqual(before,(conditions.read_bytes(),conditions_input.read_bytes(),accepted.read_bytes()))
   question2=candidate2/'questions/native-java-demo/exr-add';self.assertEqual((question2/'clientFilesQuestion/exr-add-conditions.zip').read_bytes(),conditions.read_bytes())
   self.assertIn('{{options.client_files_question_url}}/exr-add-conditions.zip',(question2/'question.html').read_text());self.assertIn('Скачать условие для локального просмотра',(question2/'question.html').read_text())
   self.assertEqual((question2/'clientFilesQuestion/starter.zip').read_bytes(),(question/'clientFilesQuestion/starter.zip').read_bytes())
   p2=json.loads((candidate2/'provenance.json').read_text());self.assertEqual(p2['source']['publicBase'],staged['publicBase']);self.assertEqual(p2['source']['privateStage'],staged['privateStage']);self.assertEqual(set(p2),{'schema','source','builder','deliveryHash','sourceSnapshotHash','inventoryHash','platformImages','files'})
   delivery2=json.loads((candidate2/'delivery.json').read_text());verification.package_integrity(delivery2,candidate2)
   self.assertIn('questions/native-java-demo/exr-add/clientFilesQuestion/exr-add-conditions.zip',delivery2['files']);stage.validate(private2,receipt2,allow_runtime=True)
   config=public/'tasks/_quarto.yml';config.write_text(config.read_text()+'\n# CONFIG_ONLY_COMMIT\n')
   run(['git','add','tasks/_quarto.yml']);run(['git','-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','Config only after materialization'])
   with self.assertRaisesRegex(stage.StageError,'sourceCommit'):stage.prepare(public,'tasks',materialized,root/'config-drift',root/'config-drift-receipt.json')
   self.assertFalse((root/'config-drift').exists());self.assertFalse((root/'config-drift-receipt.json').exists())
   if os.environ.get('PRIVATE_SOURCE_EVIDENCE'):
    evidence=Path(os.environ['PRIVATE_SOURCE_EVIDENCE']);evidence.mkdir(parents=True,exist_ok=True)
    for name,path in [('staging-receipt.json',receipt),('materialization.json',materialized/'materialization.json'),('provenance.json',candidate/'provenance.json')]:shutil.copyfile(path,evidence/name)
    (evidence/'native-files.json').write_text(json.dumps(stage.inventory(candidate),sort_keys=True,indent=2)+'\n')
