import importlib.util
import pathlib
import unittest

class ProxmoxPreflight(unittest.TestCase):
    def setUp(self):
        path=pathlib.Path(__file__).parents[1]/'tools/proxmox-preflight.py'
        spec=importlib.util.spec_from_file_location('preflight',path)
        self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module)
        self.node={'maxmem':64*1024**3,'maxcpu':32,'cpu':0.05}
        self.guests=[{'vmid':710,'type':'qemu','status':'running','maxmem':43*1024**3,'mem':1*1024**3}]
    def test_assigned_qcl_memory_is_reserved_even_when_idle(self):
        self.node['maxmem']=50*1024**3
        with self.assertRaises(ValueError):self.module.admit(self.node,self.guests,102,8*1024**3)
    def test_only_new_id_and_adequate_headroom_are_admitted(self):
        self.assertGreater(self.module.admit(self.node,self.guests,102,8*1024**3)['remainingBytes'],4*1024**3)
        with self.assertRaises(ValueError):self.module.admit(self.node,self.guests,710,8*1024**3)
        self.node['cpu']=0.95
        with self.assertRaises(ValueError):self.module.admit(self.node,self.guests,102,8*1024**3)
if __name__=='__main__':unittest.main()
