import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from mc_zh_tw_translator import release_smoke
from verify_desktop_package import verify


class ReleaseSmokeTests(unittest.TestCase):
    def test_https_context_and_ca_are_checked_without_network(self):
        with patch('requests.Session') as session:
            self.assertEqual(release_smoke.check_https(),dict(https_context=True,https_ca_loaded=True))
            session.assert_not_called()

    def test_missing_https_data_fails_smoke_before_starting_ui(self):
        from mc_zh_tw_translator.desktop import main
        with tempfile.TemporaryDirectory() as tmp, \
             patch('sys.argv',['MCTranslator.exe','--smoke-test',tmp]), \
             patch.object(release_smoke,'check_https',side_effect=FileNotFoundError('missing certificate data')), \
             patch.object(release_smoke,'check_cover_install') as cover:
            with self.assertRaises(SystemExit) as raised:main()
            self.assertEqual(raised.exception.code,1)
            report=json.loads((Path(tmp)/'smoke.json').read_bytes())
            self.assertEqual(report['status'],'failed');self.assertIn('FileNotFoundError',report['error'])
            cover.assert_not_called()

    def test_local_https_missing_file_is_not_reported_as_offline(self):
        import requests
        from urllib3.exceptions import ProtocolError
        from mc_zh_tw_translator.desktop_references import network_message
        error=requests.ConnectionError(ProtocolError('Connection aborted.',FileNotFoundError(2,'missing')))
        self.assertIn('本機檔案遺失',network_message(error))
        self.assertNotIn('檢查網路',network_message(error))
        self.assertIn('無法連上網路',network_message(requests.ConnectionError('unreachable')))

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
        base=dict(status='passed',version='test',frozen=True,https_context=True,https_ca_loaded=True,cover_generated=True,cover_readback=True,custom_cover_read=True,legacy_cloud_cover_install=True)
        cases=[(base,True),(dict(base,legacy_cloud_cover_install=False),False),(dict(base,frozen=False),False),
               (dict(base,https_context=False),False),(dict(base,https_ca_loaded=False),False),
               (dict(base,version='wrong'),False),(dict(status='failed',error='PIL missing'),False)]
        for report,success in cases:
            with self.subTest(report=report):
                def run(args,**kwargs):
                    (Path(args[2])/'smoke.json').write_text(json.dumps(report));return SimpleNamespace(returncode=0)
                with patch('verify_desktop_package.subprocess.run',side_effect=run):
                    if success:self.assertEqual(verify(Path('dummy.exe'),'test'),base)
                    else:
                        with self.assertRaises(RuntimeError):verify(Path('dummy.exe'),'test')
