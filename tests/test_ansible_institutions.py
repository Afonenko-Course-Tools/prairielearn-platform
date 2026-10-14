"""Реальный локальный Ansible packaging на новом release, без private runtime."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('ansible-playbook'),'Для локальной packaging проверки нужен Ansible')
class AnsibleInstitutionPackaging(unittest.TestCase):
    def test_fresh_release_copies_catalog_and_repeat_is_unchanged(self):
        import yaml
        tasks=yaml.safe_load((ROOT/'ansible/roles/platform/tasks/main.yml').read_text())
        # Execute actual public packaging tasks only, never runtime or service tasks.
        packaging=[task for task in tasks if (
            str(task.get('ansible.builtin.copy',{}).get('src','')).startswith('{{ pl_source_dir }}/')
            and str(task.get('ansible.builtin.copy',{}).get('dest','')).startswith('{{ pl_release_dir }}/')
        ) or task.get('ansible.builtin.file',{}).get('path') in ('{{ pl_release_dir }}/tools','{{ pl_release_dir }}/config')]
        with tempfile.TemporaryDirectory(prefix='pl-institution-ansible-') as directory:
            root=Path(directory);release=root/'release';release.mkdir()
            self.assertFalse((release/'config').exists())
            playbook=[{'name':'Синтетическая проверка публичного release','hosts':'localhost','gather_facts':False,'vars':{'pl_source_dir':str(ROOT),'pl_release_dir':str(release)},'tasks':packaging}]
            (root/'playbook.yml').write_text(yaml.safe_dump(playbook,allow_unicode=True,sort_keys=False))
            (root/'inventory').write_text('localhost ansible_connection=local ansible_python_interpreter='+sys.executable+'\n')
            environment={**os.environ,'ANSIBLE_LOCAL_TEMP':str(root/'ansible-local'),'ANSIBLE_REMOTE_TEMP':str(root/'ansible-remote'),'ANSIBLE_NOCOLOR':'1'}
            command=['ansible-playbook','-i',str(root/'inventory'),str(root/'playbook.yml')]
            first=subprocess.run(command,env=environment,capture_output=True,text=True,timeout=90)
            self.assertEqual(first.returncode,0,first.stdout+first.stderr)
            self.assertEqual(json.loads((release/'config/institutions.json').read_text()),json.loads((ROOT/'config/institutions.json').read_text()))
            self.assertEqual((release/'config').stat().st_mode&0o777,0o755)
            self.assertEqual((release/'config/institutions.json').stat().st_mode&0o777,0o644)
            repeated=subprocess.run(command,env=environment,capture_output=True,text=True,timeout=90)
            self.assertEqual(repeated.returncode,0,repeated.stdout+repeated.stderr)
            self.assertRegex(repeated.stdout,r'changed=0\s')
            self.assertFalse((release/'private').exists())
