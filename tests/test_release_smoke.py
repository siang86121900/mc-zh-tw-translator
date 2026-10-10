import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mc_zh_tw_translator import release_smoke
from verify_desktop_package import verify


class ReleaseSmokeTests(unittest.TestCase):
    def test_isolated_legacy_install_executes_cover_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();report=release_smoke.check_cover_install(root)
            self.assertTrue(report['legacy_cloud_cover_install'])
            profile=next((root/'Instances').glob('*/minecraftinstance.json'))
            record=json.loads(profile.read_bytes())
            self.assertTrue(Path(record['profileImagePath']).is_relative_to(root))
            self.assertEqual(len(json.loads((root/'MinecraftGameInstance.json').read_bytes())),2)

    def test_missing_picture_dependency_fails_smoke_before_starting_ui(self):
        from mc_zh_tw_translator.desktop import main
        with tempfile.TemporaryDirectory() as tmp, \
             patch('sys.argv',['MCTranslator.exe','--smoke-test',tmp]), \
             patch.object(release_smoke.covers,'generate',side_effect=ModuleNotFoundError("No module named 'PIL'")):
            with self.assertRaises(SystemExit) as raised:main()
            self.assertEqual(raised.exception.code,1)
            report=json.loads((Path(tmp)/'smoke.json').read_bytes())
            self.assertEqual(report['status'],'failed');self.assertIn('PIL',report['error'])

    def test_packaged_verifier_requires_actual_cover_checks_and_frozen_exe(self):
        base=dict(status='passed',version='test',frozen=True,cover_generated=True,cover_readback=True,custom_cover_read=True,legacy_cloud_cover_install=True)
        cases=[(base,True),(dict(base,legacy_cloud_cover_install=False),False),(dict(base,frozen=False),False),
               (dict(base,version='wrong'),False),(dict(status='failed',error='PIL missing'),False)]
        for report,success in cases:
            with self.subTest(report=report):
                def run(args,**kwargs):
                    (Path(args[2])/'smoke.json').write_text(json.dumps(report));return SimpleNamespace(returncode=0)
                with patch('verify_desktop_package.subprocess.run',side_effect=run):
                    if success:self.assertEqual(verify(Path('dummy.exe'),'test'),base)
                    else:
                        with self.assertRaises(RuntimeError):verify(Path('dummy.exe'),'test')
