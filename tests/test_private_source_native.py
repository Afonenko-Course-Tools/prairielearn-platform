"""Реальный Quarto owner export из synthetic private stage; без запуска grader."""
from gradle_unit_fixtures import write_registry as unit_registry_file
import importlib.util,json,os,shutil,subprocess,tempfile,unittest,zipfile,hashlib,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
# Прямой запуск теста должен видеть соседние модули builder без порядка unittest discovery.
sys.path.insert(0,str(ROOT/'tools'))

sys.dont_write_bytecode=True
PUBLIC_RUNTIME='c0208e16d2480b45d0cf0ef3c44ed706aee293f0'
ASSET_PINS={'runtime-image.json':(698,'6082087c7e3f8b00e65cef02394ce8d396d70839eeb745c2272631a0c1565950'),'published-runtime-profiles.json':(6049,'618f05f9492ac3714b9a783cf9fe935704a043987a6017ddf0858d8ecf5c8fa6'),'published-toolchain-lock.json':(197547,'c44c6f648e0bafbd2f87871813a8c5b2095315c465ddbf14e1b6282acae574ca')}
def released_context(root):
 # Настоящий published c020 и три опубликованных asset; не UNIT registry/image.
 runtime=root/'runtime-c020';shutil.copytree(Path(os.environ['OLD_PLATFORM']),runtime)
 git=lambda *args:subprocess.check_output(['git','-C',str(runtime),*args],text=True).strip()
 assert git('rev-parse','HEAD')==PUBLIC_RUNTIME and git('rev-parse','v2.3.0^{commit}')==PUBLIC_RUNTIME
 assert git('rev-parse','HEAD^{tree}')=='fb36fb5d85160bf0b7ca7d0e5502cbb0e1971d09'
 assert hashlib.sha256((runtime/'tools/build-course.py').read_bytes()).hexdigest()=='61645504bf8c720997bc32b8fdb0120cbb146279d03ad4c635d07df223311e18'
 assets=root/'runtime-assets';assets.mkdir(mode=0o700)
 for name,(size,digest) in ASSET_PINS.items():
  data=(Path(os.environ['OLD_RELEASE_ASSETS'])/name).read_bytes();assert len(data)==size and hashlib.sha256(data).hexdigest()==digest
  (assets/name).write_bytes(data);(assets/name).chmod(0o600)
 receipt=json.loads((assets/'runtime-image.json').read_bytes());images=json.loads((runtime/'images.lock.json').read_bytes())
 for role,key in [('java','javaGrader'),('fish','fishGrader'),('community','communityGateway')]:
  record=images[key];record.update(image=receipt['images'][role],sourceCommit=PUBLIC_RUNTIME,version='2.3.0')
  if 'localImage' in record:record['localImage']=receipt['images'][role].split('@')[0]+':2.3.0'
  if 'localImageId' in record:record['localImageId']=subprocess.check_output(['docker','image','inspect',receipt['images'][role],'--format','{{.Id}}'],text=True).strip()
 images['releaseAssembly']={'schema':'pl-platform-release-assets-v1','repository':'https://github.com/Afonenko-Course-Tools/prairielearn-platform','sourceCommit':PUBLIC_RUNTIME,'sourceTree':git('rev-parse','HEAD^{tree}'),'version':'2.3.0','tag':'v2.3.0','assets':{name:digest for name,(_,digest) in ASSET_PINS.items()}}
 (assets/'images.lock.json').write_text(json.dumps(images,indent=2)+'\n');(assets/'images.lock.json').chmod(0o600)
 for target,name in [('runtime-profiles.json','published-runtime-profiles.json'),('runtime/gradle-jar-v1/toolchain-lock.json','published-toolchain-lock.json')]:shutil.copyfile(assets/name,runtime/target);(runtime/target).chmod(0o644)
 spec=importlib.util.spec_from_file_location('released_c020_context',runtime/'tools/release_assembly.py');assembly=importlib.util.module_from_spec(spec);spec.loader.exec_module(assembly)
 context=assembly.Context(runtime,assets/'images.lock.json');context.recheck()
 return runtime,assets/'published-runtime-profiles.json',context
spec=importlib.util.spec_from_file_location('private_source',ROOT/'tools/prepare-private-source.py');stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)
spec=importlib.util.spec_from_file_location('builder',ROOT/'tools/build-course.py');builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
@unittest.skipUnless(os.environ.get('CORE') and os.environ.get('EXPORTER') and os.environ.get('DOWNLOAD') and os.environ.get('OLD_PLATFORM') and os.environ.get('OLD_RELEASE_ASSETS'),'Укажите CORE/EXPORTER/DOWNLOAD и настоящий OLD_PLATFORM/OLD_RELEASE_ASSETS для native integration')
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
   runtime,registry,context=released_context(root)
   def old_cli(source,receipt_path,output,manifest):
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PRAIRIELEARN_PUBLICATION_CONDITIONS=str(manifest))
    command=[sys.executable,str(runtime/'tools/build-course.py'),'--source',str(source),'--book','tasks','--instance','pilot','--output',str(output),'--staging-receipt',str(receipt_path),'--runtime-registry',str(registry)]
    return subprocess.run(command,cwd=runtime,env=env,text=True,capture_output=True)
   # Неверная private Git identity не может заменить publicBase: отдельный fresh stage.
   private_bad=root/'private-wrong-authority';receipt_bad=root/'receipt-wrong-authority.json';bad=stage.prepare(public,'tasks',materialized,private_bad,receipt_bad)
   wrong=json.loads(conditions_input.read_text());wrong['source']['commit']=bad['privateStage']['commit'];wrong_input=root/'wrong-source.json';wrong_input.write_text(json.dumps(wrong))
   refused=old_cli(private_bad,receipt_bad,root/'native-wrong-authority',wrong_input)
   self.assertNotEqual(refused.returncode,0);self.assertIn('Чужой course/source authority',refused.stdout+refused.stderr);self.assertFalse((root/'native-wrong-authority').exists());context.recheck()
   candidate2=root/'native-conditions';actual=old_cli(private2,receipt2,candidate2,conditions_input)
   self.assertEqual(actual.returncode,0,actual.stdout+actual.stderr);context.recheck()
   lines=[line.split('PL publication conditions dependency ',1)[1] for line in actual.stdout.splitlines() if 'PL publication conditions dependency ' in line]
   self.assertEqual(len(lines),1);dependency=json.loads(lines[0]);self.assertEqual(dependency['manifestSha256'],hashlib.sha256(conditions_input.read_bytes()).hexdigest());self.assertEqual(dependency['source'],staged['publicBase'])
   print('OLD_C020_ENV_ROUTE',json.dumps({'builderCommit':PUBLIC_RUNTIME,'manifestSha256':dependency['manifestSha256'],'source':dependency['source'],'archiveCount':len(dependency['archives'])}))
   self.assertEqual(before,(conditions.read_bytes(),conditions_input.read_bytes(),accepted.read_bytes()))
   question2=candidate2/'questions/native-java-demo/exr-add';self.assertEqual((question2/'clientFilesQuestion/exr-add-conditions.zip').read_bytes(),conditions.read_bytes())
   self.assertIn('{{options.client_files_question_url}}/exr-add-conditions.zip',(question2/'question.html').read_text());self.assertIn('Скачать условие для локального просмотра',(question2/'question.html').read_text())
   self.assertEqual((question2/'clientFilesQuestion/starter.zip').read_bytes(),(question/'clientFilesQuestion/starter.zip').read_bytes())
   p2=json.loads((candidate2/'provenance.json').read_text());self.assertEqual(p2['source']['publicBase'],staged['publicBase']);self.assertEqual(p2['source']['privateStage'],staged['privateStage']);self.assertEqual(p2['schema'],'pl-provenance-v2');self.assertEqual(p2['builder'],context.builder);self.assertEqual(p2['platformImages'],context.images);self.assertEqual(set(p2),{'schema','source','builder','deliveryHash','sourceSnapshotHash','inventoryHash','platformImages','files'})
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
