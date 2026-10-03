"""Server folder for a modpack: copy, official loader, trial starts that take out client-only mods, run.bat."""
import hashlib
import io
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from mc_zh_tw_translator import server_pack as sp


def jar(path, mod, client_only=False):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('META-INF/neoforge.mods.toml', f'modLoader="javafml"\n{"clientSideOnly=true" if client_only else ""}\n[[mods]]\nmodId="{mod}"\n')
        z.writestr(f'{mod}/Main.class', b'\xca\xfe\xba\xbe')


def make_instance(root, loader='neoforge-21.1.244', mc='1.21.1'):
    instance = root/'Instances'/'Demo Pack'
    for d in ('mods', 'config/ftbquests/quests/lang', 'kubejs/server_scripts', 'saves/world', 'resourcepacks', 'shaderpacks'):
        (instance/d).mkdir(parents=True)
    (instance/'manifest.json').write_text(json.dumps({'minecraft': {'version': mc, 'modLoaders': [{'id': loader, 'primary': True}],
                                                                  'recommendedRam': 12128}, 'name': 'Demo Pack'}), encoding='utf-8')
    (instance/'config/ftbquests/quests/lang/zh_tw.snbt').write_text('{ "quest.1.title": "第一章" }', encoding='utf-8')
    (instance/'kubejs/server_scripts/a.js').write_text("Text.of('你好')", encoding='utf-8')
    (instance/'options.txt').write_text('lang:zh_tw', encoding='utf-8')
    jar(instance/'mods/content.jar', 'content')
    jar(instance/'mods/imblocker.jar', 'imblocker')
    jar(instance/'mods/menu.jar', 'fancymenu')
    jar(instance/'mods/konkrete.jar', 'konkrete')
    jar(instance/'mods/lanprops.jar', 'lanserverproperties', client_only=True)
    jar(instance/'mods/kubejs.jar', 'kubejs')
    return instance


def tree_hash(folder):
    h = hashlib.sha256()
    for p in sorted(folder.rglob('*')):
        h.update(str(p.relative_to(folder)).encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


NEO_CLIENT = """---- Minecraft Crash Report ----
Description: Mod loading failures have occurred; consult the issue messages for more details

-- Mod loading issue for: imblocker --
Details:
\tMod file: /C:/Users/User/Desktop/Minecraft server/?? Server/mods/imblocker.jar
\tFailure message: IMBlocker (imblocker) has failed to load correctly
\t\tjava.lang.RuntimeException: Attempted to load class net/minecraft/client/KeyMapping for invalid dist DEDICATED_SERVER
\tMod version: 5.6.2
\tException message: java.lang.RuntimeException: Attempted to load class net/minecraft/client/KeyMapping for invalid dist DEDICATED_SERVER

-- Mod loading issue for: konkrete --
Details:
\tMod file: /C:/Users/User/Desktop/Minecraft server/?? Server/mods/??.jar
\tFailure message: Konkrete (konkrete) has failed to load correctly
\t\tjava.lang.NoClassDefFoundError: net/minecraft/client/gui/screens/Screen
\tException message: java.lang.ClassNotFoundException: net.minecraft.client.gui.screens.Screen
"""
NEO_REQUIRES = """-- Mod loading issue for: fancymenu --
Details:
\tMod file: /C:/x/mods/menu.jar
\tFailure message: Mod fancymenu requires konkrete 1.9.4 or above
\t\tCurrently, konkrete is not installed
\tException message: <No associated exception found>
"""
FORGE_SCRIPT = """Description: Mod loading error has occurred
\tMod File: /C:/x/mods/kubejs.jar
\tFailure message: KubeJS (kubejs) encountered an error during the complete event phase
\t\tjava.lang.RuntimeException: There were KubeJS startup script syntax errors! See logs/kubejs/startup.log for more info
\tException message: java.lang.RuntimeException: There were KubeJS startup script syntax errors!
"""


class LoaderTests(unittest.TestCase):
    def test_reads_loader_and_builds_official_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            neo = sp.loader_of(make_instance(Path(tmp)))
            self.assertEqual(neo, dict(kind='neoforge', version='21.1.244', mc='1.21.1'))
            self.assertEqual(sp.installer_url(neo), 'https://maven.neoforged.net/releases/net/neoforged/neoforge/21.1.244/neoforge-21.1.244-installer.jar')
        self.assertEqual(sp.installer_url(dict(kind='forge', version='47.4.10', mc='1.20.1')),
                         'https://maven.minecraftforge.net/net/minecraftforge/forge/1.20.1-47.4.10/forge-1.20.1-47.4.10-installer.jar')
        self.assertIn('/net/neoforged/forge/1.20.1-47.1.106/', sp.installer_url(dict(kind='neoforge', version='47.1.106', mc='1.20.1')))

    def test_unsupported_loaders_are_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'Quilt'):
                sp.loader_of(make_instance(Path(tmp), 'quilt-0.26.0'))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, '1.16.5'):
                sp.loader_of(make_instance(Path(tmp), 'forge-36.2.39', '1.16.5'))

    def test_java_version_matches_minecraft(self):
        self.assertEqual(sp.java_needed('1.21.1'), 21)
        self.assertEqual(sp.java_needed('1.20.1'), 17)
        self.assertEqual(sp.java_needed('1.16.5'), 8)
        versions = {Path('a'): 8, Path('b'): 21, Path('c'): 17}
        self.assertEqual(sp.find_java('1.20.1', list(versions), versions.get), (Path('c'), 17))
        self.assertEqual(sp.find_java('1.21.1', list(versions), versions.get), (Path('b'), 21))
        self.assertEqual(sp.find_java('1.16.5', list(versions), versions.get), (Path('a'), 8))
        with self.assertRaisesRegex(ValueError, 'Java 21'):
            sp.find_java('1.21.1', [Path('a')], versions.get)
        # A newer Java is fine for 1.20.1 but never stands in for Java 8.
        self.assertEqual(sp.find_java('1.20.1', [Path('b')], versions.get), (Path('b'), 21))
        with self.assertRaises(ValueError):
            sp.find_java('1.16.5', [Path('b')], versions.get)

    def test_memory_leaves_room_for_the_game_and_another_game(self):
        self.assertEqual(sp.server_memory(250, 32*1024, 12128)['mb'], 8192)
        self.assertEqual(sp.server_memory(80, 32*1024, 8192)['mb'], 4096)
        tight = sp.server_memory(250, 16*1024, 8192)
        self.assertEqual(tight['mb'], 4096)
        self.assertIn('不夠用', tight['warning'])


class FolderTests(unittest.TestCase):
    def test_target_is_a_new_folder_never_inside_the_modpack(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); instance = make_instance(root); parent = root/'Minecraft server'
            self.assertEqual(sp.target_folder(f'"{parent}"', 'Demo Pack', instance), parent.resolve()/'Demo Pack Server')
            (parent/'Demo Pack Server').mkdir(parents=True); (parent/'Demo Pack Server/world').mkdir()
            self.assertEqual(sp.target_folder(parent, 'Demo Pack', instance).name, 'Demo Pack Server (2)')
            for bad in (instance, instance/'mods', 'relative/folder', '', Path(tmp).anchor):
                with self.assertRaises(ValueError):
                    sp.target_folder(bad, 'Demo Pack', instance)
            self.assertEqual(sp.folder_name('A: B/C?'), 'A  B C Server')


class CulpritTests(unittest.TestCase):
    index = {'imblocker': 'imblocker.jar', 'konkrete': 'konkrete.jar', 'fancymenu': 'menu.jar', 'kubejs': 'kubejs.jar'}
    present = set(index.values())

    def test_client_only_mods_found_even_when_the_path_shows_question_marks(self):
        found = sp.culprits(NEO_CLIENT, self.index, self.present)
        self.assertEqual([(x['file'], x['kind']) for x in found], [('imblocker.jar', 'client'), ('konkrete.jar', 'client')])

    def test_dependency_ids_are_not_the_jars_own(self):
        # Tensura's FancyMenu lists Drippy Loading Screen among its dependencies; Drippy is another jar.
        toml = ('modLoader="javafml"\nclientSideOnly=false\n[[mods]]\nmodId="fancymenu"\n'
                '[[dependencies.fancymenu]]\nmodId="konkrete"\n[[dependencies.fancymenu]]\nmodId="drippyloadingscreen"\n')
        self.assertEqual(sp.declared_ids(toml), ['fancymenu'])
        self.assertEqual(sp.declared_ids(toml.replace('clientSideOnly=false', 'broken = = toml')), ['fancymenu'])

    def test_crash_without_mod_information_is_traced_to_its_jar(self):
        # Tensura's particle_effects reads its client settings on the server ("Mod file: <No mod information provided>").
        text = ('-- Mod loading issue --\nDetails:\n\tMod file: <No mod information provided>\n'
                '\tFailure message: An uncaught parallel processing error has occurred.\n'
                '\t\tjava.lang.IllegalStateException: Cannot get config value before config is loaded.\n'
                '\tException message: java.lang.IllegalStateException: Cannot get config value before config is loaded.\nStacktrace:\n'
                '\tat MC-BOOTSTRAP/com.google.common@32.1.2-jre/x(Preconditions.java:512) ~[guava-32.1.2-jre.jar%2387!/:?] {}\n'
                '\tat TRANSFORMER/particle_effects@1.0.1/x(ParticleEffectsManager.java:133) ~[particle_effects-1.0.1.jar%23514!/:?] {}\n'
                '-- System Details --\n\tkubejs.jar |KubeJS| ~[kubejs.jar%2311!/:?]\n')
        found = sp.culprits(text, self.index, self.present | {'particle_effects-1.0.1.jar'})
        self.assertEqual([(x['file'], x['kind']) for x in found], [('particle_effects-1.0.1.jar', 'client_config')])
        self.assertIn('設定', sp.plain_reason(found[0]))
        # An issue that names its own mod (already taken out) is never pinned on another jar in its stack.
        named = NEO_CLIENT.replace('Mod version: 5.6.2', 'at x ~[menu.jar%2312!/:?]')
        self.assertEqual([x['file'] for x in sp.culprits(named, self.index, self.present - {'imblocker.jar'})], ['konkrete.jar'])

    def test_requires_and_other_errors_are_told_apart(self):
        req = sp.culprits(NEO_REQUIRES, self.index, self.present)
        self.assertEqual((req[0]['file'], req[0]['kind'], req[0]['needs']), ('menu.jar', 'requires', 'konkrete'))
        err = sp.culprits(FORGE_SCRIPT, self.index, self.present)
        self.assertEqual((err[0]['file'], err[0]['kind']), ('kubejs.jar', 'error'))
        self.assertEqual(sp.culprits('Exception in server tick loop', self.index, self.present), [])


class FakeStarts:
    """Each start returns the next scripted outcome; mods named in a crash must be gone by then."""
    def __init__(self, outcomes):
        self.outcomes = list(outcomes); self.calls = []

    def __call__(self, server, java, args, notify, cancelled):
        self.calls.append(sorted(p.name for p in (server/'mods').glob('*.jar')))
        self.properties = (server/'server.properties').read_text(encoding='utf-8')
        (server/sp.TRIAL_WORLD/'region').mkdir(parents=True, exist_ok=True)  # what the real server writes
        text = self.outcomes.pop(0)
        return dict(ok=text.startswith('ok'), text='' if text.startswith('ok') else text, tail=[text[-40:]], timed_out=False,
                    stop_hung=text == 'ok-hung')


def fake_install(server, installer, java, notify, cancelled, loader=None):
    args = server/'libraries/net/neoforged/neoforge/21.1.244/win_args.txt'
    args.parent.mkdir(parents=True); args.write_text('-cp x', encoding='utf-8')


def fake_download(loader, home, notify, cancelled):
    return home/'installer.jar'


class BuildTests(unittest.TestCase):
    def build(self, outcomes, **kw):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name); instance = make_instance(root); before = tree_hash(instance)
        starts = FakeStarts(outcomes)
        result = sp.build_server(instance, root/'Minecraft server', root/'home', java=Path('C:/Java/bin/java.exe'), memory_mb=8192,
                                 name='Demo Pack', download=fake_download, install=fake_install, start=starts, **kw)
        self.assertEqual(tree_hash(instance), before, 'the modpack itself must not change')
        return result, Path(result['folder']), starts

    def test_client_mods_taken_out_until_the_server_starts(self):
        result, server, starts = self.build([NEO_CLIENT, NEO_REQUIRES, 'ok'])
        self.assertTrue(result['ok']); self.assertEqual(result['tries'], 3)
        self.assertEqual([x['file'] for x in result['removed']], ['lanprops.jar', 'imblocker.jar', 'konkrete.jar', 'menu.jar'])
        self.assertEqual(result['removed'][-1]['needs_file'], 'konkrete.jar')
        self.assertNotIn('lanprops.jar', starts.calls[0])  # declared client-only: out before the first start
        self.assertEqual(sorted(p.name for p in (server/sp.REMOVED_DIR).iterdir()), ['imblocker.jar', 'konkrete.jar', 'lanprops.jar', 'menu.jar'])
        self.assertEqual(sorted(p.name for p in (server/'mods').iterdir()), ['content.jar', 'kubejs.jar'])
        # Only what a server reads is copied; the translated quests and scripts come along.
        self.assertTrue((server/'config/ftbquests/quests/lang/zh_tw.snbt').exists())
        self.assertTrue((server/'kubejs/server_scripts/a.js').exists())
        for name in ('saves', 'resourcepacks', 'shaderpacks', 'options.txt'):
            self.assertFalse((server/name).exists(), name)
        self.assertIn('eula=true', (server/'eula.txt').read_text(encoding='utf-8'))
        properties = (server/'server.properties').read_text(encoding='utf-8')
        self.assertIn('server-port=25565', properties); self.assertIn('level-name=world', properties)
        # The trial ran on a free port in a world of its own, removed afterwards.
        self.assertIn('level-name='+sp.TRIAL_WORLD, starts.properties); self.assertNotIn('server-port=25565', starts.properties)
        self.assertFalse((server/sp.TRIAL_WORLD).exists())
        self.assertFalse(result['stop_hung'])
        run = (server/'run.bat').read_text(encoding='ascii')
        self.assertIn('"C:\\Java\\bin\\java.exe" @user_jvm_args.txt @libraries/net/neoforged/neoforge/21.1.244/win_args.txt', run)
        self.assertIn('cd /d "%~dp0"', run)
        self.assertIn('-Xmx8G', (server/'user_jvm_args.txt').read_text(encoding='ascii'))
        note = (server/sp.NOTE_FILE).read_text(encoding='utf-8-sig')
        self.assertIn('imblocker.jar：玩家端專用', note); self.assertIn('localhost', note)

    def test_a_server_that_does_not_end_after_stop_is_mentioned(self):
        result, server, _ = self.build(['ok-hung'])
        self.assertTrue(result['ok'] and result['stop_hung'])
        self.assertIn('沒有自己結束', (server/sp.NOTE_FILE).read_text(encoding='utf-8-sig'))

    def test_a_script_error_stops_without_taking_anything_out(self):
        result, server, _ = self.build([FORGE_SCRIPT])
        self.assertFalse(result['ok'])
        self.assertIn('kubejs.jar', result['problem']); self.assertIn('沒有拿掉', result['problem'])
        self.assertTrue((server/'mods/kubejs.jar').exists())
        self.assertEqual([x['file'] for x in result['removed']], ['lanprops.jar'])
        self.assertIn('還沒有成功開啟', (server/sp.NOTE_FILE).read_text(encoding='utf-8-sig'))

    def test_missing_mod_that_was_never_there_is_not_guessed(self):
        text = NEO_REQUIRES.replace('konkrete', 'architectury')
        result, server, _ = self.build([text])
        self.assertFalse(result['ok']); self.assertIn('architectury', result['problem'])
        self.assertTrue((server/'mods/menu.jar').exists())

    def test_unknown_crash_and_try_limit(self):
        result, _, _ = self.build(['Exception in server tick loop'])
        self.assertIn('沒有指出是哪個模組', result['problem'])
        result, _, _ = self.build([NEO_CLIENT], max_tries=1)
        self.assertIn('試了 1 次', result['problem'])

    def test_stop_keeps_the_folder_and_says_so(self):
        def stopped(*_):
            raise sp.Stopped('已停止。')
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); root = Path(tmp.name)
        with self.assertRaises(sp.Stopped):
            sp.build_server(make_instance(root), root/'srv', root/'home', java=Path('java.exe'), download=fake_download,
                            install=fake_install, start=stopped)
        server = root/'srv'/'Demo Pack Server'
        self.assertIn('server-port=25565', (server/'server.properties').read_text(encoding='utf-8'))


class FakeProcess:
    def __init__(self, lines):
        self.stdout = io.StringIO(''.join(lines)); self.stdin = io.StringIO(); self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0; return 0

    def kill(self):
        self.returncode = -9


class StartTests(unittest.TestCase):
    def test_done_line_means_started_and_the_server_is_stopped(self):
        procs = []
        def popen(cmd, **kw):
            procs.append((cmd, kw)); p = FakeProcess(['[Server thread/INFO] [minecraft/DedicatedServer]: Done (12.345s)! For help, type "help"\n',
                                                      '[Server thread/INFO] [minecraft/MinecraftServer]: Stopping server\n', 'Saving worlds\n'])
            procs.append(p); return p
        with tempfile.TemporaryDirectory() as tmp:
            out = sp.try_start(Path(tmp), Path('java.exe'), 'libraries/x/win_args.txt', popen=popen)
        self.assertTrue(out['ok'])
        self.assertEqual(procs[0][0], ['java.exe', '@user_jvm_args.txt', '@libraries/x/win_args.txt', 'nogui'])
        self.assertEqual(procs[1].stdin.getvalue(), 'stop\n')
        # Read to the end after "stop", or the server blocks on its own output and never saves.
        self.assertEqual(procs[1].stdout.read(), ''); self.assertIn('Saving worlds', out['text'])
        self.assertFalse(out['stop_hung'])

    def test_crash_report_written_during_the_start_is_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = Path(tmp)
            def popen(cmd, **kw):
                (server/'crash-reports').mkdir(exist_ok=True)
                (server/'crash-reports/crash-2026-10-01_10.00.00-fml.txt').write_text(NEO_CLIENT, encoding='utf-8')
                return FakeProcess(['[main/ERROR]: Mod loading failed\n'])
            out = sp.try_start(server, Path('java.exe'), 'a.txt', popen=popen)
        self.assertFalse(out['ok']); self.assertIn('imblocker', out['text'])

    def test_a_server_that_stays_open_after_its_crash_report_is_closed(self):
        # Forge 1.20.1 in The Foll wrote its crash report and kept running; the trial waited for it forever.
        import threading
        from unittest.mock import patch
        class Hanging(FakeProcess):
            def __init__(self):
                super().__init__([]); self.killed = threading.Event()
                def lines():
                    yield '[main/FATAL] [net.minecraftforge.server.loading.ServerModLoader/]: Crash report saved to .\\crash-reports\\crash.txt\n'
                    self.killed.wait(20)  # the real process only ends when it is killed
                self.stdout = lines()
            def kill(self):
                self.returncode = -9; self.killed.set()
        procs = []
        with tempfile.TemporaryDirectory() as tmp, patch.object(sp, 'CRASH_GRACE', 0.5):
            started = time.monotonic()
            out = sp.try_start(Path(tmp), Path('java.exe'), 'a.txt', popen=lambda *a, **k: procs.append(Hanging()) or procs[-1])
        self.assertLess(time.monotonic()-started, 10)
        self.assertTrue(procs[0].killed.is_set())
        self.assertFalse(out['ok']); self.assertFalse(out['timed_out'])  # read as a failed start: the next try follows


class Response:
    def __init__(self, body, url, status=200):
        self.body = body; self.url = url; self.status_code = status; self.text = body.decode('latin-1') if isinstance(body, bytes) else body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def iter_content(self, n):
        yield self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class DownloadTests(unittest.TestCase):
    def installer(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('install_profile.json', '{}')
        return buf.getvalue()

    def session(self, body, digest, host='maven.neoforged.net'):
        class S:
            def get(_, url, **kw):
                if url.endswith('.sha256'):
                    return Response(digest, 'https://maven.neoforged.net/x.sha256')
                return Response(body, f'https://{host}/x.jar')
        return S()

    def test_only_an_official_installer_with_the_published_hash_is_kept(self):
        loader = dict(kind='neoforge', version='21.1.244', mc='1.21.1'); body = self.installer()
        good = hashlib.sha256(body).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            path = sp.download_installer(loader, Path(tmp), session=self.session(body, good))
            self.assertEqual(path.read_bytes(), body)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, '校驗碼不符'):
                sp.download_installer(loader, Path(tmp), session=self.session(body, '0'*64))
            with self.assertRaisesRegex(ValueError, '官方以外'):
                sp.download_installer(loader, Path(tmp), session=self.session(body, good, 'evil.example.com'))
            with self.assertRaisesRegex(ValueError, '校驗碼'):
                sp.download_installer(loader, Path(tmp), session=self.session(body, '<html>'))
            self.assertEqual([p.name for p in (Path(tmp)/'downloads/server').iterdir()], [])


class WindowTests(unittest.TestCase):
    def test_card_button_asks_folder_and_eula_before_building(self):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from unittest.mock import patch
        from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton
        from mc_zh_tw_translator.desktop import MainWindow
        app = QApplication.instance() or QApplication([])
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); root = Path(tmp.name)
        instance = make_instance(root)
        entry = dict(name='Demo Pack', projectID=123, fileID=456, version='1.0', gameVersion='1.21.1', translator='我', updated='2026-09-30',
                     modpackDate='', revision=1, notes='', url='https://raw.githubusercontent.com/x', sha256='a'*64, size=1)
        window = MainWindow(root/'home'); self.addCleanup(window.deleteLater)
        found = [dict(name='Demo Pack', path=instance, projectID=123, fileID=456, gameVersion='1.21.1')]
        buttons = lambda: [b for b in window.pages.widget(6).findChildren(QPushButton) if b.text() == '建立伺服器']
        with patch('mc_zh_tw_translator.desktop_jobs.curseforge_instances', return_value=[]):
            window.catalog_loaded([entry])
        self.assertEqual(buttons(), [], 'no modpack on this computer: nothing to build a server from')
        with patch('mc_zh_tw_translator.desktop_jobs.curseforge_instances', return_value=found):
            window.catalog_loaded([entry])
            self.assertEqual(len(buttons()), 1)
            window.memory_total = 32*1024
            for eula, ran in ((False, False), (True, True)):
                with patch.object(window, 'server_parent', return_value=root/'Minecraft server'),                      patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes) as asked,                      patch.object(QMessageBox, 'information'), patch.object(window, 'ask_eula', return_value=eula),                      patch.object(window, 'run_worker') as run:
                    buttons()[0].click()
                self.assertEqual(run.called, ran)
                text = asked.call_args[0][2]
                self.assertIn(str((root/'Minecraft server').resolve()/'Demo Pack Server'), text)
                self.assertIn('NeoForge', text); self.assertIn('還沒裝好', text)
            self.assertEqual(run.call_args[0][0], 'patch_server')

    def test_whole_modpack_card_builds_from_its_installed_copy(self):
        # A whole modpack shared from Drive has no CurseForge project number; the card's own install is used.
        import os
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from unittest.mock import patch
        from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton
        from mc_zh_tw_translator.desktop import MainWindow
        app = QApplication.instance() or QApplication([])
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); root = Path(tmp.name)
        instance = make_instance(root)
        entry = dict(kind='full', name='Demo Pack v0.3.0', packId='demo pack', projectID=0, fileID=0, version='', gameVersion='1.21.1',
                     loader='', translator='我', updated='2026-10-02', modpackDate='', revision=1, notes='', recommendedRam=0,
                     driveId='x', sha256='a'*64, size=1, totalSize=0, mods=3, url='', addedMods=[])
        installed = {'k': dict(packId='demo pack', name='Demo Pack v0.3.0', path=str(instance), sha256='a'*64)}
        window = MainWindow(root/'home'); self.addCleanup(window.deleteLater)
        buttons = lambda: [b for b in window.pages.widget(6).findChildren(QPushButton) if b.text() == '建立伺服器']
        with patch('mc_zh_tw_translator.desktop_jobs.curseforge_instances', return_value=[]), \
             patch('mc_zh_tw_translator.full_pack.still_installed', return_value=installed):
            window.catalog_loaded([entry])
        self.assertEqual(len(buttons()), 1)
        window.memory_total = 32*1024
        with patch.object(window, 'server_parent', return_value=root/'Minecraft server'), \
             patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes) as asked, \
             patch.object(QMessageBox, 'information') as told, patch.object(window, 'ask_eula', return_value=True), \
             patch.object(window, 'run_worker') as run:
            buttons()[0].click()
        self.assertFalse(told.called, 'must not say the modpack cannot be found')
        self.assertTrue(run.called)
        self.assertIn(instance.name, asked.call_args[0][2])
        # The progress shows on the card that was clicked, with a stop button: the page's status line is out of
        # sight once the list is scrolled down (reported 2026-10-02: "按了建立伺服器但沒有進度").
        key = window.catalog_key(window.catalog[0])
        self.assertEqual(window.active_card, key)
        window.mode = 'patch_server'; window.worker = None
        window.on_progress(40, '試開伺服器', '第 1 次')
        card, stop = window.card_progress[key], window.card_stop[key]
        self.assertFalse(card.isHidden()); self.assertIn('試開伺服器：第 1 次（40%）', card.text())
        self.assertFalse(stop.isHidden())
        window.finish_worker()
        self.assertTrue(card.isHidden()); self.assertTrue(stop.isHidden()); self.assertIsNone(window.active_card)


def fabric_jar(path, mod, environment='*', provides=(), bundled=()):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('fabric.mod.json', json.dumps({'schemaVersion': 1, 'id': mod, 'environment': environment, 'provides': list(provides)}))
        for inner in bundled:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, 'w') as nested:
                nested.writestr('fabric.mod.json', json.dumps({'schemaVersion': 1, 'id': inner}))
            z.writestr(f'META-INF/jars/{inner}.jar', buf.getvalue())


def make_fabric(root):
    instance = make_instance(root, 'fabric-0.18.4')
    for p in (instance/'mods').glob('*.jar'):
        p.unlink()
    fabric_jar(instance/'mods/cobblemon.jar', 'cobblemon')
    fabric_jar(instance/'mods/fabric-api.jar', 'fabric-api', bundled=('fabric-api-base', 'fabric-key-binding-api-v1'))
    fabric_jar(instance/'mods/sodium.jar', 'sodium', environment='client')
    fabric_jar(instance/'mods/menu.jar', 'fancymenu')
    fabric_jar(instance/'mods/konkrete.jar', 'konkrete')
    return instance


FABRIC_ENTRY_CLIENT = """[16:12:01] [main/ERROR]: Failed to start the minecraft server
java.lang.RuntimeException: Could not execute entrypoint stage 'main' due to errors, provided by 'konkrete' at 'de.keksuccino.konkrete.Konkrete'!
\tat net.fabricmc.loader.impl.FabricLoaderImpl.lambda$invokeEntrypoints$2(FabricLoaderImpl.java:403) ~[fabric-loader-0.18.4.jar:?]
Caused by: java.lang.NoClassDefFoundError: net/minecraft/class_437
\tat de.keksuccino.konkrete.Konkrete.onInitialize(Konkrete.java:20) ~[konkrete.jar:?]
Caused by: java.lang.ClassNotFoundException: net.minecraft.class_437
"""
FABRIC_REQUIRES = """[16:11:40] [main/ERROR]: Incompatible mods found!
net.fabricmc.loader.impl.FormattedException: Some of your mods are incompatible with the game or each other!
A potential solution has been determined, this may resolve your problem:
\t - Install konkrete, any version.
More details:
\t - Mod 'FancyMenu' (fancymenu) 3.2.0 requires any version of konkrete, which is missing!
"""
FABRIC_REQUIRES_ZH = """[16:13:14] [main/WARN]: Mod resolution failed
[16:13:14] [main/INFO]: Immediate reason: [HARD_DEP_NO_CANDIDATE controlling 19.0.5 {depends searchables @ [>=1.0.1]}, ROOT_FORCELOAD_SINGLE controlling 19.0.5]
[16:13:14] [main/INFO]: Reason: [HARD_DEP controlling 19.0.5 {depends searchables @ [>=1.0.1]}, HARD_DEP c2me-opts-natives-math 0.4.0-alpha.0.23+1.21.1 {depends java @ [>=25]}]
[16:13:14] [main/ERROR]: Incompatible mods found!
net.fabricmc.loader.impl.FormattedException: Some of your mods are incompatible with the game or each other!
\t - 模組 'Controlling' (controlling) 19.0.5 需要 版本 1.0.1 以上（含） searchables，但該版本缺失！
"""
# COBBLEVERSE with Sodium's "client" label removed (2026-10-03).
FABRIC_SODIUM = """[16:16:34] [main/WARN]: Error loading class: org/quiltmc/loader/api/plugin/ModContainerExt (java.lang.ClassNotFoundException: org/quiltmc/loader/api/plugin/ModContainerExt)
[16:16:34] [main/ERROR]: A mod crashed on startup!
net.fabricmc.loader.impl.FormattedException: java.lang.RuntimeException: Could not execute entrypoint stage 'preLaunch' due to errors, provided by 'sodium' at 'net.caffeinemc.mods.sodium.fabric.SodiumPreLaunch'!
\tat net.fabricmc.loader.impl.FormattedException.ofLocalized(FormattedException.java:63) ~[fabric-loader-0.18.4.jar:?]
Caused by: java.lang.RuntimeException: Could not execute entrypoint stage 'preLaunch' due to errors, provided by 'sodium' at 'net.caffeinemc.mods.sodium.fabric.SodiumPreLaunch'!
\tat net.fabricmc.loader.impl.FabricLoaderImpl.lambda$invokeEntrypoints$0(FabricLoaderImpl.java:409) ~[fabric-loader-0.18.4.jar:?]
\t... 3 more
Caused by: java.lang.NoClassDefFoundError: org/lwjgl/Version
\tat knot/net.caffeinemc.mods.sodium.client.compatibility.checks.PreLaunchChecks.isUsingKnownCompatibleLwjglVersion(PreLaunchChecks.java:136) ~[sodium.jar:?]
Caused by: java.lang.ClassNotFoundException: org.lwjgl.Version
"""
# Logged by every Fabric start of COBBLEVERSE, also the ones that work.
FABRIC_WARNINGS = """[16:13:52] [main/WARN]: Error loading class: net/minecraft/class_906 (java.lang.ClassNotFoundException: net/minecraft/class_906)
[16:13:52] [main/WARN]: @Mixin target net.minecraft.class_906 was not found porting_lib_item_abilities.mixins.json:FishingHookRendererMixin from mod porting_lib_item_abilities
"""
FABRIC_PORT = """[16:14:28] [Server thread/WARN]: **** FAILED TO BIND TO PORT!
[16:14:28] [Server thread/ERROR]: Encountered an unexpected exception
java.lang.IllegalStateException: Failed to initialize server
\tat knot/net.minecraft.server.MinecraftServer.runServer(MinecraftServer.java:716) ~[server-intermediary.jar:?]
[16:14:29] [Server thread/ERROR]: Exception stopping the server
java.lang.NullPointerException: Cannot invoke "net.minecraft.server.PlayerManager.getPlayerList()"
\tat knot/com.cobblemon.mod.fabric.CobblemonFabric.initialize$lambda$10(CobblemonFabric.kt:166) ~[Cobblemon-fabric-1.7.3+1.21.1.jar:?]
"""
FABRIC_ENTRY_ERROR = """java.lang.RuntimeException: Could not execute entrypoint stage 'main' due to errors, provided by 'cobblemon' at 'x'!
Caused by: java.lang.IllegalStateException: Duplicate registration
"""


class FabricTests(unittest.TestCase):
    def test_loader_from_manifest_and_from_curseforge_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            loader = sp.loader_of(make_fabric(Path(tmp)))
        self.assertEqual(loader, dict(kind='fabric', version='0.18.4', mc='1.21.1'))
        with tempfile.TemporaryDirectory() as tmp:
            # COBBLEVERSE's minecraftinstance.json alone: fabric-<loader>-<Minecraft>.
            instance = Path(tmp)
            (instance/'minecraftinstance.json').write_text(json.dumps({'baseModLoader': {'name': 'fabric-0.18.4-1.21.1'}}), encoding='utf-8')
            self.assertEqual(sp.loader_of(instance), dict(kind='fabric', version='0.18.4', mc='1.21.1'))
        self.assertEqual(sp.installer_url(dict(kind='fabric', version='0.18.4', mc='1.21.1', installer='1.1.2')),
                         'https://maven.fabricmc.net/net/fabricmc/fabric-installer/1.1.2/fabric-installer-1.1.2.jar')

    def test_fabric_ids_bundled_modules_and_client_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            mods = make_fabric(Path(tmp))/'mods'
            index = sp.mod_ids(mods)
            self.assertEqual(index['fabric-api-base'], 'fabric-api.jar')
            self.assertEqual(index['konkrete'], 'konkrete.jar')
            self.assertEqual(sp.declared_client_only(mods), ['sodium.jar'])

    def test_fabric_crashes(self):
        index = {'konkrete': 'konkrete.jar', 'fancymenu': 'menu.jar', 'cobblemon': 'cobblemon.jar'}
        present = set(index.values())
        found = sp.fabric_culprits(FABRIC_ENTRY_CLIENT, index, present)
        self.assertEqual([(x['file'], x['kind']) for x in found], [('konkrete.jar', 'client')])
        req = sp.fabric_culprits(FABRIC_REQUIRES, index, present)
        self.assertEqual([(x['file'], x['kind'], x['needs']) for x in req], [('menu.jar', 'requires', 'konkrete')])
        err = sp.fabric_culprits(FABRIC_ENTRY_ERROR, index, present)
        self.assertEqual([(x['file'], x['kind']) for x in err], [('cobblemon.jar', 'error')])
        # No mod named: the first mod jar under the missing class; the loader's own jar is not a mod.
        bare = FABRIC_WARNINGS+'java.lang.NoClassDefFoundError: net/minecraft/class_437\n'+FABRIC_ENTRY_CLIENT.split('\n', 2)[2]
        self.assertEqual([(x['file'], x['kind']) for x in sp.fabric_culprits(bare, index, present)], [('konkrete.jar', 'client')])
        # Sodium on a server: its pre-launch check needs LWJGL, the game's window and sound library.
        sodium = sp.fabric_culprits(FABRIC_SODIUM, {'sodium': 'sodium.jar'}, {'sodium.jar'})
        self.assertEqual([(x['file'], x['kind']) for x in sodium], [('sodium.jar', 'client')])
        # The warnings every Fabric start logs for mixins aimed at the player's game blame nobody.
        self.assertEqual(sp.fabric_culprits(FABRIC_WARNINGS+FABRIC_PORT, index, present | {'Cobblemon-fabric-1.7.3+1.21.1.jar'}), [])
        # Fabric writes its sentences in the computer's language; the resolver's English line names the mods.
        index['controlling'] = 'Controlling.jar'
        req = sp.fabric_culprits(FABRIC_REQUIRES_ZH, index, present | {'Controlling.jar'})
        self.assertEqual([(x['file'], x['kind'], x['needs']) for x in req], [('Controlling.jar', 'requires', 'searchables')])
        self.assertEqual(sp.fabric_culprits('Exception in server tick loop', index, present), [])

    def test_fabric_install_command_and_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = Path(tmp); installer = server.parent/(server.name+'-installer.jar'); installer.write_bytes(b'PK')
            self.addCleanup(installer.unlink)
            calls = []
            def popen(cmd, **kw):
                calls.append(cmd); (server/sp.FABRIC_LAUNCHER).write_bytes(b'PK'); (server/'server.jar').write_bytes(b'PK')
                return FakeProcess(['Done\n'])
            sp.install_loader(server, installer, Path('java.exe'), loader=dict(kind='fabric', version='0.18.4', mc='1.21.1'), popen=popen)
            self.assertEqual(calls[0][3:], ['server', '-dir', '.', '-mcversion', '1.21.1', '-loader', '0.18.4', '-downloadMinecraft'])
            self.assertEqual(sp.args_file(server), sp.FABRIC_LAUNCHER)
            self.assertFalse((server/installer.name).exists())
            started = []
            def start(cmd, **kw):
                started.append(cmd); return FakeProcess(['[16:12:30] [Server thread/INFO]: Done (21.5s)! For help, type "help"\n'])
            self.assertTrue(sp.try_start(server, Path('java.exe'), sp.FABRIC_LAUNCHER, popen=start)['ok'])
            self.assertEqual(started[0], ['java.exe', '@user_jvm_args.txt', '-jar', 'fabric-server-launch.jar', 'nogui'])
        self.assertTrue(sp.DONE.search('[Server thread/INFO] (Minecraft) Done (3.2s)! For help'))

    def test_fabric_build_takes_out_client_mods(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); root = Path(tmp.name)
        instance = make_fabric(root); before = tree_hash(instance)
        def install(server, installer, java, notify, cancelled, loader=None):
            self.assertEqual(loader['kind'], 'fabric')
            (server/sp.FABRIC_LAUNCHER).write_bytes(b'PK'); (server/'server.jar').write_bytes(b'PK')
        starts = FakeStarts([FABRIC_ENTRY_CLIENT, FABRIC_REQUIRES, 'ok'])
        result = sp.build_server(instance, root/'srv', root/'home', java=Path('C:/Java/bin/java.exe'), name='Cobble',
                                 download=fake_download, install=install, start=starts)
        self.assertEqual(tree_hash(instance), before)
        self.assertTrue(result['ok'])
        self.assertEqual([(x['file'], x['kind']) for x in result['removed']],
                         [('sodium.jar', 'declared'), ('konkrete.jar', 'client'), ('menu.jar', 'requires')])
        server = Path(result['folder'])
        self.assertIn('@user_jvm_args.txt -jar fabric-server-launch.jar', (server/'run.bat').read_text(encoding='ascii'))
        self.assertIn('sodium.jar：模組自己標明只給玩家端用', (server/sp.NOTE_FILE).read_text(encoding='utf-8-sig'))

    def test_fabric_installer_version_from_fabric_list(self):
        class S:
            def __init__(self, loader_status=200, broken=False):
                self.loader_status = loader_status; self.broken = broken
            def get(self, url, **kw):
                if '/versions/loader/' in url:
                    return Response(b'[]', url, self.loader_status)
                if self.broken:
                    raise __import__('requests').ConnectionError('down')
                r = Response(b'', url); r.json = lambda: [{'version': '1.2.0', 'stable': False}, {'version': '1.1.9', 'stable': True}]
                return r
        loader = dict(kind='fabric', version='0.18.4', mc='1.21.1')
        self.assertEqual(sp.fabric_installer(loader, S(), {}), '1.1.9')
        self.assertEqual(sp.fabric_installer(loader, S(broken=True), {}), sp.FABRIC_INSTALLER)
        with self.assertRaisesRegex(ValueError, 'Fabric Loader 0.18.4'):
            sp.fabric_installer(loader, S(400), {})


if __name__ == '__main__':
    unittest.main()
