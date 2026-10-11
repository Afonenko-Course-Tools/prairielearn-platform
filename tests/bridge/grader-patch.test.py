import importlib.util,pathlib,unittest

class Patch(unittest.TestCase):
 def test_pinned_body_is_wrapped_and_memory_is_bounded(self):
  path=pathlib.Path(__file__).parents[2]/'images/prairielearn/patch-local-grader.py'
  spec=importlib.util.spec_from_file_location('patch',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  source="(async () => {\n const job = {Memory: (1 << 30) * 2, MemorySwap: (1 << 30) * 2};\n })().catch((error) => { throw error; });"
  result=module.patch(source)
  self.assertIn('await acquireLocalGrader()',result);self.assertIn('finally',result)
  self.assertIn('Memory: 512 * 1024 * 1024',result);self.assertIn('MemorySwap: 512 * 1024 * 1024',result)
  with self.assertRaises(ValueError):module.patch('changed source')
if __name__=='__main__':unittest.main()
