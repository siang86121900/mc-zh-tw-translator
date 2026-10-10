import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mc_zh_tw_translator import covers


class CoverTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.instance=self.root/'Instances/Elemental Awakening'
        (self.instance/'mods').mkdir(parents=True);self.home=self.root/'app'
        self.profile=self.instance/'minecraftinstance.json'
        self.record=dict(guid='01234567-89ab-cdef-0123-456789abcdef',installPath=str(self.instance),name='Elemental Awakening',projectID=0,allocatedMemory=3072)
        self.profile.write_text(json.dumps(self.record),encoding='utf-8')
        self.listing=self.root/'agent/MinecraftGameInstance.json';self.listing.parent.mkdir()
        self.other=dict(guid='other',name='Keep',allocatedMemory=8192)
        self.listing.write_text(json.dumps([self.other,self.record]),encoding='utf-8')

    def apply(self,**kwargs):
        kwargs.setdefault('running',lambda:False)
        return covers.existing(self.instance,self.home,listing=self.listing,**kwargs)

    def test_artwork_is_valid_stable_and_differs_between_names(self):
        a=covers.generate('Elemental Awakening');b=covers.generate('The Foll')
        self.assertTrue(covers.valid(a));self.assertEqual(a,covers.generate('Elemental Awakening'));self.assertNotEqual(a,b)
        self.assertTrue(covers.valid(covers.generate('中文整合包名稱 非常長的名稱 '*12)))
        self.assertFalse(covers.valid(b'not an image'))

    def test_missing_artwork_updates_only_matching_profile_and_can_be_restored(self):
        before=self.profile.read_bytes();result=self.apply()
        record=json.loads(self.profile.read_bytes());listing=json.loads(self.listing.read_bytes())
        self.assertTrue(covers.valid((self.instance/covers.FILE).read_bytes()))
        self.assertEqual(record['profileImagePath'],str(self.instance/covers.FILE));self.assertEqual(record['allocatedMemory'],3072)
        self.assertEqual(listing[0],self.other);self.assertEqual(listing[1],record)
        self.assertTrue(Path(result['backup']).is_dir())
        from mc_zh_tw_translator.desktop_jobs import restore_backup
        restore_backup(Path(result['backup']),self.instance)
        self.assertEqual(self.profile.read_bytes(),before);self.assertFalse((self.instance/covers.FILE).exists())

    def test_existing_or_official_artwork_is_never_replaced(self):
        for extra in (dict(profileImagePath='D:/personal/cover.png'),dict(projectID=123),dict(installedModpack={'name':'Official'})):
            with self.subTest(extra=extra):
                self.profile.write_text(json.dumps(dict(self.record,**extra)))
                before=self.profile.read_bytes();cache=self.listing.read_bytes()
                with patch.object(covers,'generate',side_effect=AssertionError('must retain existing artwork')):
                    self.apply(running=lambda:True)
                self.assertEqual(self.profile.read_bytes(),before);self.assertEqual(self.listing.read_bytes(),cache)

    def test_missing_global_cache_is_not_created(self):
        self.listing.unlink();self.apply();self.assertFalse(self.listing.exists())
        self.assertTrue(json.loads(self.profile.read_bytes())['profileImagePath'])

    def test_waits_for_curseforge_and_can_cancel_without_changes(self):
        before=self.profile.read_bytes();cache=self.listing.read_bytes();calls=[]
        self.apply(running=lambda:True,cancelled=lambda:True)
        self.assertEqual(self.profile.read_bytes(),before);self.assertEqual(self.listing.read_bytes(),cache)
        states=iter([True,False,False,False])
        self.apply(running=lambda:next(states,False),pause=lambda seconds:calls.append(seconds))
        self.assertEqual(calls,[3])

    def test_cache_write_failure_rolls_back_profile_and_image(self):
        before=self.profile.read_bytes();cache=self.listing.read_bytes();real=covers.apply_reviewed;calls=[]
        def apply(*args,**kwargs):
            calls.append(args[0])
            if len(calls)==2:raise OSError('mock cache failure')
            return real(*args,**kwargs)
        with patch.object(covers,'apply_reviewed',side_effect=apply):
            with self.assertRaises(OSError):self.apply()
        self.assertEqual(self.profile.read_bytes(),before);self.assertEqual(self.listing.read_bytes(),cache)
        self.assertFalse((self.instance/covers.FILE).exists())

    def test_wrong_or_duplicate_global_record_is_rejected_before_writes(self):
        for entries in ([self.other],[self.record,self.record],[dict(self.record,installPath=str(self.root/'elsewhere'))]):
            with self.subTest(entries=entries):
                self.listing.write_text(json.dumps(entries));before=self.profile.read_bytes()
                with self.assertRaises(ValueError):self.apply()
                self.assertEqual(self.profile.read_bytes(),before);self.assertFalse((self.instance/covers.FILE).exists())

    def test_export_uses_only_selected_local_image(self):
        image=self.root/'original.png';image.write_bytes(covers.generate('Original'))
        self.assertEqual(covers.image_for(self.instance,dict(profileImagePath=str(image)),'Other'),image.read_bytes())
        image.write_bytes(b'broken')
        self.assertTrue(covers.valid(covers.image_for(self.instance,dict(profileImagePath=str(image)),'Other')))
