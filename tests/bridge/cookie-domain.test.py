import importlib.util,pathlib,subprocess,unittest,json
path=pathlib.Path(__file__).parents[2]/'images/prairielearn/patch-localhost-cookies.py'
class LocalhostCookiePatch(unittest.TestCase):
 def test_pinned_guard_becomes_host_only_localhost_exception(self):
  self.assertTrue(path.exists(),'host-only production patch is missing')
  spec=importlib.util.spec_from_file_location('patch',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  original='''    if (!config.cookieDomain) {\n      throw new Error('cookieDomain must be set in production environments');\n    }\n\n    if (!config.cookieDomain.startsWith('.')) {'''
  revised=m.patch(original)
  self.assertIn("config.cookieDomain === null",revised)
  self.assertIn("plHostOnlyIP(config.hostname)",revised)
  self.assertIn("if (!hostOnly && !config.cookieDomain)",revised)
  self.assertIn("if (!hostOnly && !config.cookieDomain?.startsWith('.'))",revised)
  with self.assertRaises(ValueError):m.patch('different upstream source')
 def test_ip_and_localhost_only_preserve_domain_and_key_guards(self):
  spec=importlib.util.spec_from_file_location('patch',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
  original="""if (!config.cookieDomain) {
 throw new Error('cookieDomain must be set in production environments');
 }
 if (!config.cookieDomain.startsWith('.')) { throw new Error('Invalid domain'); }
 if (config.databaseEncryptionKey === 'default') { throw new Error('Invalid encryption key'); }
 """
  revised=m.patch(original)
  guard=revised.replace("import { isIP as plHostOnlyIP } from 'node:net';", "const plHostOnlyIP = require('node:net').isIP;")
  for hostname,domain,allowed in [('localhost',None,True),('10.135.250.230',None,True),('2001:db8::1',None,True),('course.example',None,False),('10.135.250.999',None,False),('localhost:3000',None,False),('https://10.135.250.230',None,False),('course.example','.course.example',True),('10.135.250.230','',False)]:
   with self.subTest(hostname=hostname,domain=domain):
    config={'hostname':hostname,'cookieDomain':domain,'databaseEncryptionKey':'private-key'}
    run=subprocess.run(['node','-e','const config='+json.dumps(config)+';'+guard],capture_output=True,text=True)
    self.assertEqual(run.returncode==0,allowed,run.stderr)
  config={'hostname':'10.135.250.230','cookieDomain':None,'databaseEncryptionKey':'default'}
  self.assertNotEqual(subprocess.run(['node','-e','const config='+json.dumps(config)+';'+guard],capture_output=True).returncode,0)
if __name__=='__main__':unittest.main()
