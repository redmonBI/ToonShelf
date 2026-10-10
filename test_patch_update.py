import json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import patch_update as updater

class PatchTests(unittest.TestCase):
 def fixture(self,root):
  target=root/'existing';target.mkdir();(target/'ToonShelf.exe').write_bytes(b'old')
  (target/'state').mkdir();(target/'state'/'settings.json').write_bytes(b'personal')
  (target/'Downloads').mkdir();(target/'Downloads'/'image.jpg').write_bytes(b'original')
  (target/'custom.txt').write_bytes(b'keep');(target/'_internal').mkdir();(target/'_internal'/'module.dll').write_bytes(b'old dll')
  stage=root/'update'/'ready'/'ToonShelf';stage.mkdir(parents=True)
  (stage/'ToonShelf.exe').write_bytes(b'new');(stage/'_internal').mkdir();(stage/'_internal'/'module.dll').write_bytes(b'new dll')
  (stage/'state').mkdir();(stage/'state'/'settings.json').write_bytes(b'defaults')
  result={'path':str(stage),'version':'v3.1.2','sha256':'a'*64}
  return target,stage,Path(updater.prepare_patch(result,target,os.getpid()))
 def test_patch_preserves_personal_files_and_restarts_same_path(self):
  with tempfile.TemporaryDirectory() as tmp:
   target,stage,manifest=self.fixture(Path(tmp));calls=[]
   self.assertEqual(updater.apply_patch(manifest,wait=lambda pid:calls.append(pid),launch=lambda p:calls.append(p)),0)
   self.assertEqual((target/'ToonShelf.exe').read_bytes(),b'new');self.assertEqual((target/'_internal'/'module.dll').read_bytes(),b'new dll')
   self.assertEqual((target/'state'/'settings.json').read_bytes(),b'personal');self.assertEqual((target/'Downloads'/'image.jpg').read_bytes(),b'original');self.assertEqual((target/'custom.txt').read_bytes(),b'keep')
   self.assertEqual(calls,[os.getpid(),target/'ToonShelf.exe'])
   self.assertEqual((manifest.parent/'backup'/'ToonShelf.exe').read_bytes(),b'old')
 def test_failed_patch_rolls_back_and_launches_old_program(self):
  with tempfile.TemporaryDirectory() as tmp:
   target,stage,manifest=self.fixture(Path(tmp));real_replace=updater.replace_file;calls=[]
   def failing(dest,temp):
    if dest.name=='module.dll' and temp.read_bytes()==b'new dll':raise OSError('injected failure')
    real_replace(dest,temp)
   with patch.object(updater,'replace_file',side_effect=failing):
    self.assertEqual(updater.apply_patch(manifest,wait=lambda p:None,launch=lambda p:calls.append(p)),1)
   self.assertEqual((target/'ToonShelf.exe').read_bytes(),b'old');self.assertEqual((target/'_internal'/'module.dll').read_bytes(),b'old dll')
   self.assertEqual(calls,[target/'ToonShelf.exe']);self.assertEqual(json.loads((manifest.parent/'result.json').read_text())['status'],'rolled_back')
 def test_tampered_or_traversing_manifest_cannot_write(self):
  for traversal in (False,True):
   with tempfile.TemporaryDirectory() as tmp:
    target,stage,manifest=self.fixture(Path(tmp))
    if traversal:
     data=json.loads(manifest.read_text());data['files'][0]['name']='../outside';manifest.write_text(json.dumps(data))
    else:(stage/'ToonShelf.exe').write_bytes(b'changed')
    with self.assertRaises(ValueError):updater.apply_patch(manifest,wait=lambda p:self.fail('must not wait'),launch=lambda p:self.fail('must not restart'))
    self.assertEqual((target/'ToonShelf.exe').read_bytes(),b'old')
 @unittest.skipUnless(os.name=='nt','Windows process wait')
 def test_waits_for_previous_process_without_terminating_it(self):
  process=subprocess.Popen([sys.executable,'-c','import time;time.sleep(.15)'])
  updater.wait_for_exit(process.pid);self.assertEqual(process.wait(timeout=3),0)

if __name__=='__main__':unittest.main()
