"""Exercise exact Git transport and checkout over a temporary verified HTTPS server."""
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
        (self.repo/'infoCourse.json').write_text('{"name":"SYN"}\n')
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
        data={'schema':'pl-provenance-v1','source':{'commit':'a'*40,'dirty':False},'builder':{'commit':'b'*40,'dirty':False},'files':{'infoCourse.json':hashlib.sha256((self.repo/'infoCourse.json').read_bytes()).hexdigest()}}
        (self.repo/'provenance.json').write_text(json.dumps(data))
    def stop(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def stage(self):return self.module.stage_course(self.course,self.storage)
    def test_exact_commit_checkout_and_repeat_are_stable(self):
        path=self.stage();self.assertEqual(path,self.storage/'course-a'/self.first)
        self.assertEqual((path/'infoCourse.json').read_text(),'{"name":"SYN"}\n')
        self.assertEqual(self.stage(),path)
    def test_upgrade_retains_previous_delivery(self):
        first=self.stage();(self.repo/'infoCourse.json').write_text('{"name":"SYN2"}\n');self.update_provenance();self.git('add','.');self.git('commit','-qm','Native v2');self.course['commit']=self.git('rev-parse','HEAD');self.git('update-server-info')
        second=self.stage();self.assertNotEqual(first,second);self.assertIn('SYN2',(second/'infoCourse.json').read_text());self.assertIn('SYN"',(first/'infoCourse.json').read_text())
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
    def test_symlink_storage_parent_is_refused(self):
        (self.storage/'course-a').symlink_to(self.repo)
        with self.assertRaises(self.module.StorageError):self.stage()
