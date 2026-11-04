"""Native Git index проверяется напрямую; свой SHA/receipt договор отсутствует."""
import hashlib,struct,unittest,shutil
import test_workspace_recipe_seed as fixtures
from grading_job import JobError
class WorkspaceIndexTail(unittest.TestCase):
 def test_optional_extensions_and_native_footer(self):
  helper=fixtures.RecipeSeed();self.addCleanup(helper.doCleanups);root,entries=helper.fixture({'notes.txt':b'notes\n'});index=entries['work/.git/index']
  for tail,valid in [(b'',True),(b'TEST'+struct.pack('>I',0),True),(b'fail'+struct.pack('>I',0),False),(b'fail',True)]:
   with self.subTest(tail=tail):
    shutil.rmtree(root/'native',ignore_errors=True)
    value=index[:-20]+tail;changed=dict(entries);changed['work/.git/index']=value+hashlib.sha1(value).digest()
    if valid:helper.proof(root,changed)
    else:
     with self.assertRaises(JobError):helper.proof(root,changed)
  shutil.rmtree(root/'native',ignore_errors=True)
  changed=dict(entries);changed['work/.git/index']=index[:-1]+bytes([index[-1]^1])
  with self.assertRaises(JobError):helper.proof(root,changed)
if __name__=='__main__':unittest.main()
