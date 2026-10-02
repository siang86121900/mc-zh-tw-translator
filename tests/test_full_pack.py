"""Whole-modpack sharing: pack the owner's translated modpack, install it as a new CurseForge profile."""
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from mc_zh_tw_translator import full_pack, patches

LOADER = {'name': 'forge-47.4.10', 'forgeVersion': '47.4.10', 'type': 1, 'installMethod': 3,
          'downloadUrl': 'https://modloaders.forgecdn.net/647622546/maven/net/minecraftforge/forge/1.20.1-47.4.10/forge-1.20.1-47.4.10.jar',
          'versionJson': json.dumps({'libraries': [{'downloads': {'artifact': {'url': 'https://modloaders.forgecdn.net/647622546/maven/a.jar'}}}]}),
          # Forge's real install profile carries a sponsor link in a comment; it is never downloaded.
          'installProfileJson': json.dumps({'_comment_': ['Please support https://www.patreon.com/LexManos/'], 'libraries': []})}
LISTING = b'[{"name":"Other Pack","guid":"aaaa","installPath":"%s"}]'


def sha(data):return hashlib.sha256(data).hexdigest()


def jar(text):
    """A small valid jar; the same text gives the same bytes."""
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as z:z.writestr(zipfile.ZipInfo('a.txt',(2026,1,1,0,0,0)),text)
    return buffer.getvalue()


def url(n,name):return f'https://edge.forgecdn.net/files/{n}/{n}/{name}'


class Server:
    """CurseForge's file server and Google Drive in one; records requests."""
    def __init__(self,files):self.files=files;self.asked=[];self.html=False;self.cut=None
    def get(self,address,stream=False,timeout=None,headers=None):
        import requests
        self.asked.append((address,dict(headers or {})));server=self
        data=self.files.get(address.split('&confirm')[0] if 'drive.usercontent' in address else address)
        start=int((headers or {}).get('Range','bytes=0-')[6:-1] or 0)
        class Response:
            status_code=404 if data is None else 206 if start else 200
            url=address;history=[]
            headers={'Content-Type':'text/html; charset=utf-8' if server.html else 'application/octet-stream'}
            def __enter__(inner):return inner
            def __exit__(inner,*_):pass
            def raise_for_status(inner):
                if inner.status_code>=400:raise requests.HTTPError(str(inner.status_code),response=inner)
            def iter_content(inner,size):
                body=data[start:];size=min(size,256)
                for i in range(0,len(body),size):
                    if server.cut is not None and start+i>=server.cut:
                        server.cut=None;raise requests.ConnectionError('reset')
                    yield body[i:i+size]
        return Response()


class FullPackTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.home=self.root/'app'
        self.owner=self.root/'owner/My Pack';(self.owner/'mods').mkdir(parents=True)
        self.served=jar('curseforge mod');self.changed=jar('translated copy');self.handmade=jar('not on curseforge')
        (self.owner/'mods/served.jar').write_bytes(self.served)
        (self.owner/'mods/changed.jar').write_bytes(self.changed)
        (self.owner/'mods/handmade.jar').write_bytes(self.handmade)
        (self.owner/'mods/.connector').mkdir();(self.owner/'mods/.connector/gen.jar').write_bytes(b'generated')
        (self.owner/'config').mkdir();(self.owner/'config/a.toml').write_text('# 設定\nx=1\n',encoding='utf-8')
        (self.owner/'resourcepacks').mkdir();(self.owner/'resourcepacks/MCTranslator-zh_tw.zip').write_bytes(jar('translation'))
        for personal in ('saves/World/level.dat','logs/latest.log','xaero/minimap/a.txt','XaeroWaypoints_BACKUP1/b.txt','crash-reports/c.txt'):
            (self.owner/personal).parent.mkdir(parents=True,exist_ok=True);(self.owner/personal).write_text('mine')
        for personal in ('servers.dat','usercache.json','optionsof.txt'):(self.owner/personal).write_text('mine')
        (self.owner/'options.txt').write_text('key_key.jump:key.keyboard.space\nlang:en_us\nresourcePacks:["vanilla","file/MCTranslator-zh_tw.zip"]\n',encoding='utf-8')
        (self.owner/'manifest.json').write_text(json.dumps({'name':'My Pack','version':'2.7','minecraft':{'version':'1.20.1','recommendedRam':10000}}),encoding='utf-8')
        addons=[dict(addonID=n,name=name,installedFile=dict(id=n*10,fileName=name,fileLength=len(data),downloadUrl=url(n,name)))
                for n,(name,data) in enumerate((('served.jar',self.served),('changed.jar',self.changed)),1)]
        (self.owner/'minecraftinstance.json').write_text(json.dumps(dict(name='My Pack',projectID=0,fileID=0,gameVersion='1.20.1',
                                                                         baseModLoader=LOADER,installedAddons=addons)),encoding='utf-8')
        # CurseForge serves the original of changed.jar, so only served.jar may be linked.
        self.server=Server({url(1,'served.jar'):self.served,url(2,'changed.jar'):jar('curseforge original')})
        self.package=self.root/'pack.zip'
        self.manifest=full_pack.build(self.owner,self.package,session=self.server,workers=1)
        self.instances=self.root/'cf/Instances';(self.instances/'Other Pack').mkdir(parents=True)
        self.listing=self.root/'cf/MinecraftGameInstance.json'
        self.listing.write_bytes(LISTING%json.dumps(str(self.instances/'Other Pack')+'\\')[1:-1].encode())
        self.before=self.listing.read_bytes()

    def install(self,**more):
        more.setdefault('running',lambda:False)
        return full_pack.install(self.package,self.home,session=self.server,listing=self.listing,pause=lambda _:None,**more)

    def test_pack_leaves_out_personal_files_and_links_only_identical_curseforge_mods(self):
        files={e['path']:e for e in self.manifest['files']}
        self.assertEqual(files['mods/served.jar']['source'],'curseforge')
        self.assertEqual(files['mods/changed.jar']['source'],'zip')
        self.assertEqual(files['mods/handmade.jar']['source'],'zip')
        for gone in ('saves/World/level.dat','logs/latest.log','xaero/minimap/a.txt','XaeroWaypoints_BACKUP1/b.txt','crash-reports/c.txt',
                     'servers.dat','usercache.json','optionsof.txt','minecraftinstance.json','mods/.connector/gen.jar'):
            self.assertNotIn(gone,files)
        with zipfile.ZipFile(self.package) as z:
            options=z.read('files/options.txt').decode()
            self.assertNotIn('files/mods/served.jar',z.namelist())
        self.assertIn('lang:zh_tw',options);self.assertIn('MCTranslator-zh_tw.zip',options);self.assertNotIn('key_key.jump',options)
        self.assertEqual(self.manifest['recommendedRam'],10000)

    def test_curseforge_modpack_is_refused(self):
        record=json.loads((self.owner/'minecraftinstance.json').read_text());record['projectID']=5
        (self.owner/'minecraftinstance.json').write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError,'正式版本'):full_pack.build(self.owner,self.root/'x.zip',session=self.server)

    def test_install_creates_a_checked_profile_and_keeps_the_rest_of_the_list(self):
        result=self.install()
        folder=Path(result['folder'])
        self.assertEqual(folder,self.instances/'My Pack')
        for e in self.manifest['files']:
            self.assertEqual(sha((folder/e['path']).read_bytes()),e['sha256'],e['path'])
        after=self.listing.read_bytes()
        self.assertTrue(after.startswith(self.before[:-1]+b','))
        data=json.loads(after);self.assertEqual(len(data),2)
        entry=data[-1];self.assertEqual(entry['name'],'My Pack');self.assertEqual(entry['installPath'],str(folder)+'\\')
        self.assertEqual(entry['installedAddons'],[]);self.assertEqual(entry['baseModLoader']['name'],'forge-47.4.10')
        self.assertFalse(entry['isMemoryOverride'])
        self.assertEqual(json.loads((folder/'minecraftinstance.json').read_text(encoding='utf-8'))['guid'],entry['guid'])
        self.assertEqual(len(list(self.home.glob('output/My Pack/CurseForge紀錄備份/*/MinecraftGameInstance.json'))),1)
        self.assertIn(str(folder).casefold(),full_pack.installed(self.home))
        self.assertFalse(list(self.instances.glob('.mctranslator-*')))
        # A second install never touches the first one.
        second=Path(self.install()['folder'])
        self.assertEqual(second.name,'My Pack (2)');self.assertEqual(len(json.loads(self.listing.read_bytes())),3)

    def test_waits_for_curseforge_to_close_and_cancel_leaves_nothing(self):
        state={'n':0}
        def running():
            state['n']+=1;return state['n']<3
        self.install(running=running)
        self.assertEqual(state['n'],3)
        listing=self.listing.read_bytes();cancel={'now':False}
        def still_running():
            cancel['now']=True;return True
        with self.assertRaises(InterruptedError):
            self.install(running=still_running,cancelled=lambda:cancel['now'])
        self.assertEqual(self.listing.read_bytes(),listing)
        self.assertFalse((self.instances/'My Pack (2)').exists());self.assertFalse(list(self.instances.glob('.mctranslator-*')))

    def test_a_different_curseforge_file_stops_before_anything_is_registered(self):
        self.server.files[url(1,'served.jar')]=jar('someone replaced it')
        with self.assertRaises(ValueError):self.install()
        self.assertEqual(self.listing.read_bytes(),self.before)
        self.assertEqual([p.name for p in self.instances.iterdir()],['Other Pack'])

    def test_unreadable_curseforge_list_is_not_changed(self):
        self.listing.write_bytes(b'{"not":"a list"}')
        with self.assertRaisesRegex(ValueError,'看不懂'):self.install()
        self.assertEqual(self.listing.read_bytes(),b'{"not":"a list"}')
        self.assertEqual([p.name for p in self.instances.iterdir()],['Other Pack'])

    def test_broken_paths_in_the_curseforge_list_fall_back_to_its_default_folder(self):
        for broken in ('\\\\','Instances\\\\Other\\\\','C:\\\\'):
            self.listing.write_bytes(('[{"name":"x","installPath":"%s"}]'%broken).encode())
            self.assertEqual(full_pack.curseforge_root(self.listing),Path.home()/'curseforge/minecraft/Instances')
        self.listing.write_bytes(self.before)
        self.assertEqual(full_pack.curseforge_root(self.listing),self.instances)

    def test_no_curseforge(self):
        with self.assertRaisesRegex(ValueError,'沒有 CurseForge'):
            full_pack.install(self.package,self.home,session=self.server,listing=self.root/'missing.json',running=lambda:False)

    def tampered(self,change):
        with zipfile.ZipFile(self.package) as z:items={n:z.read(n) for n in z.namelist()}
        manifest=json.loads(items[full_pack.MANIFEST]);change(manifest,items)
        items[full_pack.MANIFEST]=json.dumps(manifest).encode()
        bad=self.root/'bad.zip'
        with zipfile.ZipFile(bad,'w') as z:
            for n,d in items.items():z.writestr(n,d)
        return bad

    def test_unsafe_packages_are_refused(self):
        def traversal(m,items):m['files'][0]['path']='../evil.jar'
        def unlisted(m,items):items['files/mods/extra.jar']=b'x'
        def loader(m,items):m['loader']=dict(LOADER,downloadUrl='https://evil.example/forge.jar')
        def mod_url(m,items):
            e=next(e for e in m['files'] if e['source']=='curseforge');e['url']='https://evil.example/files/1/1/served.jar'
        def record(m,items):
            m['files'].append(dict(path='minecraftinstance.json',size=1,sha256='0'*64,source='zip'));items['files/minecraftinstance.json']=b'x'
        for change in (traversal,unlisted,loader,mod_url,record):
            with self.subTest(change.__name__),self.assertRaises(ValueError):full_pack.read(self.tampered(change))

    def test_drive_download_resumes_checks_and_explains_blocked_files(self):
        data=self.package.read_bytes();pack=dict(driveId='A'*33,sha256=sha(data),size=len(data))
        self.server.files[full_pack.drive_url(pack['driveId']).split('&confirm')[0]]=data
        self.server.cut=len(data)//2
        path=full_pack.download(pack,self.home,session=self.server,pause=lambda _:None)
        self.assertEqual(path.read_bytes(),data)
        self.assertTrue(any(h.get('Range') for _,h in self.server.asked))
        path.unlink();self.server.html=True
        with self.assertRaisesRegex(ValueError,'知道連結的任何人'):full_pack.download(pack,self.home,session=self.server,pause=lambda _:None)
        self.server.html=False
        with self.assertRaisesRegex(ValueError,'校驗不符'):
            full_pack.download(dict(pack,sha256='0'*64),self.home,session=self.server,pause=lambda _:None)

    def test_catalog_lists_full_packs_and_old_entries_still_work(self):
        entry=dict(kind='full',name='My Pack',version='2.7',driveId='B'*33,sha256='a'*64,size=1000,totalSize=5000,revision=2)
        pack=patches.full_entry(entry)
        self.assertEqual(patches.match_catalog([pack],[],{},{})[0]['status'],'full')
        folder=self.root/'cf/Instances/My Pack';folder.mkdir()
        mine={str(folder).casefold():dict(path=str(folder),name='My Pack',sha256='a'*64)}
        self.assertEqual(patches.match_catalog([pack],[],{},mine)[0]['status'],'full_installed')
        mine[str(folder).casefold()]['sha256']='b'*64
        self.assertEqual(patches.match_catalog([pack],[],{},mine)[0]['status'],'full_update')
        for bad in (dict(entry,driveId='../x'),dict(entry,size=0),dict(entry,sha256='zz')):
            with self.assertRaises(ValueError):patches.full_entry(bad)


if __name__=='__main__':
    unittest.main()
