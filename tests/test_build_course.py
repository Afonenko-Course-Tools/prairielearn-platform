"""Builder tests exercise real filesystem, git and exporter subprocess boundaries.

The fixture exporter replaces only the expensive Quarto boundary; it insists on
its actual command protocol and emits complete native delivery records.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'tools/build-course.py'

class CourseBuilderTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), 'Shared course builder is not implemented')
        spec = importlib.util.spec_from_file_location('course_builder', SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.config = self.source / 'prairielearn/export.json'
        self.out = self.root / 'delivery'
        self.bin = self.root / 'bin'; self.bin.mkdir()
        self.quarto = self.bin / 'quarto'
        self.quarto.write_text('''#!/usr/bin/env python3
import json, pathlib, shutil, sys
assert sys.argv[1] == 'run' and sys.argv[3:5] == ['.', 'tasks'], sys.argv
work=sys.argv[5]; binding=sys.argv[6]; output=pathlib.Path(sys.argv[7])
assert pathlib.Path(sys.argv[2]).is_file() and pathlib.Path(binding).is_file()
fixture=pathlib.Path('fixtures') / work
shutil.copytree(fixture,output,symlinks=True)
''')
        self.quarto.chmod(0o755)
        self.config_data = {'schema':'pl-source-v1','courseId':'course-a','book':'tasks','works':[{'id':'sec-a','binding':'prairielearn/binding.json'}],'shell':'prairielearn/native'}
        self.write(self.config, self.config_data)
        self.write(self.source/'prairielearn/binding.json', {'questions':{}})
        entry = self.source/'tasks/_extensions/Afonenko-Course-Tools/course-prairielearn/entrypoints/export.ts'
        entry.parent.mkdir(parents=True); entry.write_text('// fixture owner entrypoint\n')
        self.write(self.source/'providers.json', {'providers':{}})
        self.write(self.source/'installed-packages.json', {'packages':[]})
        self.write(self.source/'prairielearn/native/infoCourse.json', {'name':'SYN-A','title':'Synthetic A','topics':[]})
        self.write(self.source/'prairielearn/native/courseInstances/pilot/infoCourseInstance.json', {'uuid':'8ec804e0-f799-4c8c-a538-f34b07e2e12c','longName':'Synthetic pilot'})
        self.assessment = self.source/'prairielearn/native/courseInstances/pilot/assessments/test/infoAssessment.json'
        self.write(self.assessment, {'uuid':'0c9d1b4d-128b-4569-a9b0-c6b9411ef788','type':'Exam','title':'Test','set':'Exam','number':'1','zones':[{'questions':[{'id':'course-a/exr-one','autoPoints':[1,1,1]}]}]})
        self.fixture('sec-a', 'course-a')
        self.git('init','-q'); self.git('config','user.name','Synthetic'); self.git('config','user.email','synthetic@example.test'); self.git('remote','add','origin','https://example.test/source.git'); self.commit()
        self.env = patch.dict(os.environ, {'PATH':str(self.bin)+os.pathsep+os.environ['PATH']})
        self.env.start(); self.addCleanup(self.env.stop)

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True)+'\n')

    def fixture(self, work, course, text='Condition'):
        base=self.source/'fixtures'/work
        qid=course+'/exr-one'
        q=base/'questions'/qid
        self.write(q/'info.json', {'uuid':'61dafb49-b246-5385-8fea-39b9f6f11401','type':'v3','title':'exr-one','topic':'Java','externalGradingOptions':{'image':'synthetic-grader@sha256:'+'a'*64}})
        (q/'question.html').write_text(text)
        self.write(base/'delivery.json', {'course':course,'release':'source-release','works':[{'owner':course,'id':work,'key':course+'/'+work,'source':'tasks/work.qmd','kind':'test','title':'Test','items':[qid],'assignments':{qid:{'requirement':'required','workMode':'individual'}}}],'questions':[qid]})

    def git(self,*args):
        return subprocess.run(['git',*args],cwd=self.source,check=True,capture_output=True,text=True).stdout.strip()

    def commit(self):
        self.git('add','.'); self.git('commit','-qm','Synthetic source')

    def build(self):
        self.module.build_course(self.source,self.config,self.out)

    def refusal(self):
        with self.assertRaises(self.module.BuildError): self.build()
        self.assertFalse(self.out.exists(), 'Rejected build published a partial course')

    def test_shell_delivery_and_provenance_are_published_reproducibly(self):
        self.build()
        self.assertEqual((self.out/'questions/course-a/exr-one/question.html').read_text(),'Condition')
        self.assertTrue((self.out/'deliveries/sec-a.json').is_file())
        p=json.loads((self.out/'provenance.json').read_text())
        self.assertEqual(p['source']['commit'],self.git('rev-parse','HEAD'))
        first={str(f.relative_to(self.out)):f.read_bytes() for f in self.out.rglob('*') if f.is_file()}
        self.out=self.root/'second'; self.build()
        second={str(f.relative_to(self.out)):f.read_bytes() for f in self.out.rglob('*') if f.is_file()}
        self.assertEqual(first,second)

    def test_existing_output_is_preserved(self):
        self.out.mkdir(); (self.out/'sentinel').write_text('keep')
        with self.assertRaises(self.module.BuildError): self.build()
        self.assertEqual((self.out/'sentinel').read_text(),'keep')

    def test_identical_question_in_two_works_is_reused(self):
        self.fixture('sec-b','course-a')
        self.config_data['works'].append({'id':'sec-b','binding':'prairielearn/binding.json'})
        self.write(self.config,self.config_data); self.commit(); self.build()
        self.assertEqual(len(list((self.out/'questions').rglob('info.json'))),1)
        self.assertTrue((self.out/'deliveries/sec-b.json').is_file())

    def test_conflicting_duplicate_question_is_rejected(self):
        self.fixture('sec-b','course-a','Different condition')
        self.config_data['works'].append({'id':'sec-b','binding':'prairielearn/binding.json'})
        self.write(self.config,self.config_data); self.commit(); self.refusal()

    def test_missing_assessment_question_is_rejected(self):
        a=json.loads(self.assessment.read_text());a['zones'][0]['questions'][0]['id']='course-a/exr-missing'
        self.write(self.assessment,a); self.commit(); self.refusal()

    def test_path_traversal_is_rejected(self):
        self.config_data['shell']='../outside'
        self.write(self.config,self.config_data); self.commit(); self.refusal()

    def test_symlink_shell_is_rejected(self):
        (self.source/'prairielearn/native/link').symlink_to(self.root)
        self.commit(); self.refusal()

    def test_exporter_failure_does_not_publish(self):
        self.quarto.write_text('#!/usr/bin/env python3\nraise SystemExit(2)\n')
        self.refusal()

    def test_dirty_source_is_rejected(self):
        (self.source/'providers.json').write_text('changed')
        self.refusal()

    def test_wrong_course_namespace_is_rejected(self):
        self.config_data['courseId']='course-b';self.write(self.config,self.config_data);self.commit();self.refusal()

    def test_two_courses_keep_separate_native_question_namespaces(self):
        self.build()
        self.fixture('sec-a','course-b')
        import shutil
        shutil.rmtree(self.source/'fixtures/sec-a/questions/course-a')
        self.config_data['courseId']='course-b';self.write(self.config,self.config_data)
        a=json.loads(self.assessment.read_text());a['zones'][0]['questions'][0]['id']='course-b/exr-one';self.write(self.assessment,a)
        self.commit();self.out=self.root/'course-b';self.build()
        self.assertTrue((self.root/'delivery/questions/course-a/exr-one/info.json').is_file())
        self.assertTrue((self.out/'questions/course-b/exr-one/info.json').is_file())
        self.assertFalse((self.out/'questions/course-a').exists())

    def test_symlink_in_owner_export_is_rejected(self):
        (self.source/'fixtures/sec-a/questions/course-a/exr-one/leak').symlink_to('/etc/hosts')
        self.commit();self.refusal()

    def test_malformed_delivery_qid_is_rejected(self):
        p=self.source/'fixtures/sec-a/delivery.json';v=json.loads(p.read_text());v['questions']=[{}]
        self.write(p,v);self.commit();self.refusal()

    def test_uuid_collision_is_rejected(self):
        a=json.loads(self.assessment.read_text());a['uuid']='61dafb49-b246-5385-8fea-39b9f6f11401'
        self.write(self.assessment,a);self.commit();self.refusal()

if __name__ == '__main__': unittest.main()
