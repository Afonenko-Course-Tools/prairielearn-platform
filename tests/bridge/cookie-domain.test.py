import importlib.util,pathlib,tempfile,unittest
path=pathlib.Path(__file__).parents[2]/'images/prairielearn/patch-localhost-cookies.py'
class LocalhostCookiePatch(unittest.TestCase):
 def test_pinned_guard_becomes_host_only_localhost_exception(self):
  self.assertTrue(path.exists(),'host-only production patch is missing')
  spec=importlib.util.spec_from_file_location('patch',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  original='''    if (!config.cookieDomain) {\n      throw new Error('cookieDomain must be set in production environments');\n    }\n\n    if (!config.cookieDomain.startsWith('.')) {'''
  revised=m.patch(original)
  self.assertIn("config.cookieDomain === null && config.hostname === 'localhost'",revised)
  self.assertIn("if (!localhostHostOnly && !config.cookieDomain)",revised)
  self.assertIn("if (!localhostHostOnly && !config.cookieDomain?.startsWith('.'))",revised)
  with self.assertRaises(ValueError):m.patch('different upstream source')
if __name__=='__main__':unittest.main()
