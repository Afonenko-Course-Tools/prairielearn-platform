"""Exercise exact Git transport and checkout over a temporary verified HTTPS server."""
from gradle_unit_fixtures import registry as unit_registry
import functools
import hashlib
import http.server
import importlib.util
import json
import os
import shutil
from pathlib import Path
import ssl
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

SCRIPT=Path(__file__).resolve().parents[1]/'tools/stage_courses.py'
class CourseStorageTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(),'Course storage is not implemented')
        spec=importlib.util.spec_from_file_location('storage',SCRIPT);self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.repo=self.root/'native.git';self.repo.mkdir()
        def git(*args):return subprocess.run(['git',*args],cwd=self.repo,check=True,capture_output=True,text=True).stdout.strip()
        self.git=git;git('init','-q');git('config','user.name','Synthetic');git('config','user.email','synthetic@example.test')
        (self.repo/'infoCourse.json').write_text(json.dumps({'uuid':'4174cd08-ddff-4006-81cc-d7a6b67d3ee0','name':'SYN','title':'Synthetic','timezone':'Europe/Minsk','topics':[{'name':'fixture','color':'gray1','description':'Synthetic'}]}))
        from grading_job import load_runtime_registry
        self.registry=unit_registry()
        for profile in self.registry['profiles'].values():profile['image']='synthetic@sha256:'+'a'*64
        registry_patch=patch.object(self.module,'load_runtime_registry',return_value=self.registry);registry_patch.start();self.addCleanup(registry_patch.stop)
        self.update_provenance()
        git('add','.');git('commit','-qm','Native v1');self.first=git('rev-parse','HEAD');git('update-server-info')
        cert=self.root/'cert.pem';key=self.root/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-keyout',str(key),'-out',str(cert),'-subj','/CN=localhost','-addext','subjectAltName=IP:127.0.0.1'],check=True,capture_output=True)
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self,*args):pass
        self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Quiet,directory=str(self.root)))
        ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain(cert,key);self.server.socket=ctx.wrap_socket(self.server.socket,server_side=True)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.addCleanup(self.stop)
        self.env=patch.dict(os.environ,{'GIT_SSL_CAINFO':str(cert),'GIT_TERMINAL_PROMPT':'0'});self.env.start();self.addCleanup(self.env.stop)
        self.course={'id':'course-a','repository':f'https://127.0.0.1:{self.server.server_port}/native.git/.git','commit':self.first,'mount':'/course'}
        self.storage=self.root/'storage';self.storage.mkdir()
    def update_provenance(self):
        from grading_job import digest,verify_results
        import test_review_receipts as review
        qid='synthetic/exr-one';image='synthetic@sha256:'+'a'*64
        q=self.repo/'questions'/qid;q.mkdir(parents=True,exist_ok=True)
        uuid='37d79ee7-fd7d-44db-bd45-6587711862a5'
        (q/'info.json').write_text(json.dumps({'uuid':uuid,'type':'v3','title':'Synthetic','topic':'fixture','gradingMethod':'External','externalGradingOptions':{'enabled':True,'image':image}}))
        (q/'question.html').write_text('<pl-file-editor file-name="S.java"></pl-file-editor><pl-external-grader-results></pl-external-grader-results>')
        (q/'clientFilesQuestion').mkdir(exist_ok=True);(q/'clientFilesQuestion/README.md').write_text('PUBLIC_STARTER')
        instance=self.repo/'courseInstances/fixture';(instance/'assessments/lab').mkdir(parents=True,exist_ok=True)
        (instance/'infoCourseInstance.json').write_text(json.dumps({'uuid':'b1017718-408e-410a-ae67-b525de725a6d','longName':'Synthetic'}))
        (instance/'assessments/lab/infoAssessment.json').write_text(json.dumps({'uuid':'9af557f9-c196-46bd-b813-09036235e732','type':'Homework','title':'Synthetic','set':'Homework','number':'1','zones':[{'questions':[{'id':qid,'points':1}]}]}))
        (q/'tests').mkdir(exist_ok=True)
        cfg={'schemaVersion':1,'sourceFiles':['S.java'],'testFiles':['T.java'],'mode':'implementation','runtime':'java25-junit-v1','java':{'release':25,'encoding':'UTF-8','compiler-options':['-proc:none','-Xmaxerrs','5']},'limits':{'outer-seconds':30,'compile-seconds':15,'run-seconds':10,'networking':False,'max-output-bytes':65536},'scoring':{'mode':'weighted'},'discovery':{'min-executed':1,'allow-skipped':False}}
        (q/'tests/grading-job.json').write_text(json.dumps(cfg))
        scenarios=[{'qualifiedId':qid,'scenario':name,'optional':False} for name in ['contract:counterexample','reference:default','starter']]
        files={p.relative_to(self.repo).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in self.repo.rglob('*') if p.is_file() and '.git' not in p.relative_to(self.repo).parts and p.name not in ('delivery.json','provenance.json','verification-receipt.json')}
        slot='synthetic/lab/exr-one'
        binding={'uuid':uuid,'grading':{'method':'external'},'submission':{'mode':'editor'},'sourceRoot':'projects/one','projectCheck':'junit','runtime':'java25-junit-v1','sources':[{'projectRelativePath':'student/S.java','submissionRelativePath':'S.java','sha256':'c'*64}]}
        delivery={'schemaVersion':3,'courseId':'synthetic','bookRoot':'tasks','sourceSnapshotHash':'a'*64,'inventoryHash':'b'*64,'questions':[qid],'gradingPayloads':{qid:binding},'verificationInventoryHash':digest(scenarios),'files':files,'works':[{'id':'lab','slots':[{'id':slot,'selection':'fixed','candidates':[qid],'assignment':{'requirement':'required','workMode':'individual'}}],'policy':{},'completion':{'schemaVersion':2,'mode':'required-slot-completion','source':'per-slot-results-v2','slotIds':[slot],'requiredSlotIds':[slot],'atLeast':1,'fullyCompletedScore':1}}],'instances':{'fixture':{'works':['lab'],'selfEnrollment':False}}}
        delivery['deliveryHash']=digest(delivery)
        (self.repo/'delivery.json').write_text(json.dumps(delivery))
        results=[]
        for entry in scenarios:
            r=review.result(entry['scenario'],image);r.update(qualifiedId=qid,deliveryHash=delivery['deliveryHash']);results.append(r)
        automatic=verify_results(results,{},scenarios,registry=self.registry)
        from delivery_verification import delivery_receipt
        checks={'sourceSnapshotHash':'a'*64,'inventoryHash':'b'*64,'projects':[{'qualifiedId':qid,'projectRoot':'projects/one','check':{'runtime':'java25-junit-v1','profile':'junit'},'sources':binding['sources']}]}
        receipt=delivery_receipt(delivery,self.repo,checks,automatic,self.registry)
        (self.repo/'verification-receipt.json').write_text(json.dumps(receipt))
        data={'schema':'pl-provenance-v1','source':{'commit':'a'*40,'dirty':False},'builder':{'commit':'b'*40,'dirty':False},'deliveryHash':delivery['deliveryHash'],'sourceSnapshotHash':'a'*64,'inventoryHash':'b'*64,'files':{name:hashlib.sha256((self.repo/name).read_bytes()).hexdigest() for name in [*files,'delivery.json','verification-receipt.json']}}
        (self.repo/'provenance.json').write_text(json.dumps(data))
    def rename_course(self,name):
        p=self.repo/'infoCourse.json';value=json.loads(p.read_text());value['name']=name;p.write_text(json.dumps(value))
    def stop(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def stage(self):return self.module.stage_course(self.course,self.storage)
    def test_exact_commit_checkout_and_repeat_are_stable(self):
        path=self.stage();self.assertEqual(path,self.storage/'course-a'/self.first)
        self.assertEqual(json.loads((path/'infoCourse.json').read_text())['name'],'SYN')
        self.assertEqual(self.stage(),path)
    def test_upgrade_retains_previous_delivery(self):
        first=self.stage();self.rename_course('SYN2');self.update_provenance();self.git('add','.');self.git('commit','-qm','Native v2');self.course['commit']=self.git('rev-parse','HEAD');self.git('update-server-info')
        second=self.stage();self.assertNotEqual(first,second);self.assertIn('SYN2',(second/'infoCourse.json').read_text());self.assertEqual(json.loads((first/'infoCourse.json').read_text())['name'],'SYN')
    def test_dirty_existing_checkout_is_refused(self):
        path=self.stage();(path/'infoCourse.json').write_text('changed')
        with self.assertRaises(self.module.StorageError):self.stage()
    def test_missing_provenance_commits_are_refused(self):
        data=json.loads((self.repo/'provenance.json').read_text())
        data['source'].pop('commit');data['builder'].pop('commit')
        (self.repo/'provenance.json').write_text(json.dumps(data));self.git('add','.');self.git('commit','-qm','Missing provenance pins');self.course['commit']=self.git('rev-parse','HEAD');self.git('update-server-info')
        with self.assertRaises(self.module.StorageError):self.stage()
    def test_symlink_git_metadata_is_refused_before_git_execution(self):
        path=self.stage();metadata=self.root/'external-git';shutil.move(path/'.git',metadata);(path/'.git').symlink_to(metadata)
        with patch.object(self.module,'git',wraps=self.module.git) as invoked:
            with self.assertRaises(self.module.StorageError):self.stage()
            invoked.assert_not_called()

    def test_nonexistent_commit_leaves_no_published_directory(self):
        self.course['commit']='f'*40
        with self.assertRaises(self.module.StorageError):self.stage()
        self.assertFalse((self.storage/'course-a'/('f'*40)).exists())
    def test_symlink_payload_is_refused(self):
        (self.repo/'leak').symlink_to('/etc/hosts');self.git('add','.');self.git('commit','-qm','Unsafe native');self.course['commit']=self.git('rev-parse','HEAD');self.git('update-server-info')
        with self.assertRaises(self.module.StorageError):self.stage()
    def test_two_course_ids_keep_separate_storage(self):
        first=self.stage();self.course['id']='course-b';self.course['mount']='/course2';second=self.stage();self.assertNotEqual(first,second);self.assertTrue(first.is_dir());self.assertTrue(second.is_dir())
    def test_registry_upgrade_one_course_preserves_other_pin_and_payload(self):
        a=dict(self.course);b=dict(self.course,id='course-b',mount='/course2')
        registry={'schema':'pl-courses-v1','courses':[a,b]}
        images=self.module.builder.read_json(SCRIPT.parents[1]/'images.lock.json')
        first=self.module.stage_registry(registry,images,self.storage)
        original=(Path(first['services']['pl']['volumes'][0]['source'])/'infoCourse.json').read_bytes()
        self.rename_course('SYN2');self.update_provenance();self.git('add','.');self.git('commit','-qm','Only B upgraded');self.git('update-server-info')
        b['commit']=self.git('rev-parse','HEAD')
        second=self.module.stage_registry(registry,images,self.storage)
        self.assertEqual(first['services']['pl']['volumes'][0],second['services']['pl']['volumes'][0])
        self.assertEqual((Path(second['services']['pl']['volumes'][0]['source'])/'infoCourse.json').read_bytes(),original)
        self.assertNotEqual(first['services']['pl']['volumes'][1]['source'],second['services']['pl']['volumes'][1]['source'])
        self.assertTrue(Path(first['services']['pl']['volumes'][1]['source']).exists())
    def test_symlink_storage_parent_is_refused(self):
        (self.storage/'course-a').symlink_to(self.repo)
        with self.assertRaises(self.module.StorageError):self.stage()
    def test_missing_successful_receipt_blocks_staging(self):
        (self.repo/'verification-receipt.json').unlink(missing_ok=True);self.git('add','-A');self.git('commit','-qm','Missing receipt');self.course['commit']=self.git('rev-parse','HEAD');self.git('update-server-info')
        with self.assertRaises(self.module.StorageError):self.stage()
    def test_receipt_wrong_delivery_hash_blocks_staging(self):
        p=self.repo/'verification-receipt.json';p.write_text('{"scope":"delivery","status":"success","deliveryHash":"wrong"}')
        self.git('add','.');self.git('commit','-qm','Wrong receipt');self.course['commit']=self.git('rev-parse','HEAD');self.git('update-server-info')
        with self.assertRaises(self.module.StorageError):self.stage()

    def test_v2_institution_reference_survives_staging_and_repeat(self):
        catalog={'schema':'pl-institutions-v1','institutions':{'synthetic':{'shortName':'SYN','longName':'Synthetic University','displayTimezone':'Europe/Minsk','uidRegexp':None}}}
        course={**self.course,'institution':'synthetic'}
        registry={'schema':'pl-courses-v2','courses':[course]}
        images=self.module.builder.read_json(SCRIPT.parents[1]/'images.lock.json')
        first=self.module.stage_registry(registry,images,self.storage,catalog)
        self.assertEqual(first,self.module.stage_registry(registry,images,self.storage,catalog))
        self.assertTrue(Path(first['services']['pl']['volumes'][0]['source']).is_dir())

    def test_unknown_institution_rejects_before_checkout(self):
        catalog={'schema':'pl-institutions-v1','institutions':{'synthetic':{'shortName':'SYN','longName':'Synthetic University','displayTimezone':'Europe/Minsk','uidRegexp':None}}}
        registry={'schema':'pl-courses-v2','courses':[{**self.course,'institution':'unknown'}]}
        images=self.module.builder.read_json(SCRIPT.parents[1]/'images.lock.json')
        with patch.object(self.module,'git',wraps=self.module.git) as invoked:
            with self.assertRaises(self.module.RegistryError):self.module.stage_registry(registry,images,self.storage,catalog)
            invoked.assert_not_called()

    def rewrite_receipt(self,receipt):
        from grading_job import digest
        automatic=receipt.get('automatic',{}).get('receipt')
        if automatic:automatic['identityHash']=digest({k:v for k,v in automatic.items() if k!='identityHash'})
        receipt['identityHash']=digest({k:v for k,v in receipt.items() if k!='identityHash'})
        path=self.repo/'verification-receipt.json';path.write_text(json.dumps(receipt))
        p=self.repo/'provenance.json';value=json.loads(p.read_text());value['files']['verification-receipt.json']=hashlib.sha256(path.read_bytes()).hexdigest();p.write_text(json.dumps(value))
        self.git('add','.');self.git('commit','-qm','Review receipt fixture');self.course['commit']=self.git('rev-parse','HEAD');self.git('update-server-info')
    def test_partial_starter_only_receipt_cannot_stage_reference_and_contract_inventory(self):
        receipt=json.loads((self.repo/'verification-receipt.json').read_text());receipt['automatic']['receipt']['coverage']='partial';receipt['automatic']['receipt']['expectations']=[x for x in receipt['automatic']['receipt']['expectations'] if x['scenario']=='starter'];self.rewrite_receipt(receipt)
        with self.assertRaises(self.module.StorageError):self.stage()
    def test_staged_question_image_must_match_receipt_binding(self):
        receipt=json.loads((self.repo/'verification-receipt.json').read_text());image='synthetic@sha256:'+'d'*64
        receipt['automatic']['receipt']['runtimes']['java25-junit-v1']=image;receipt['automatic']['receipt']['questionBindings'][0]['imageDigest']=image;self.rewrite_receipt(receipt)
        with self.assertRaises(self.module.StorageError):self.stage()
    def test_staged_runtime_dependency_closure_must_match_registry(self):
        receipt=json.loads((self.repo/'verification-receipt.json').read_text());receipt['automatic']['receipt']['runtimeEvidence']['java25-junit-v1']['dependencyHashes']['runner/grade.py']='d'*64;self.rewrite_receipt(receipt)
        with self.assertRaises(self.module.StorageError):self.stage()
