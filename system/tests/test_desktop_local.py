"""The desktop's real local authority preserves config, identity and native ownership."""
import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from gbox import desktop_local as D
from gbox.config import Config,HOST_OS,Library


def entry(path,**fields):
    return {'game_id':'owned_game_123','title':'Owned local game','platform':'gamecube',
        'source_paths':[str(path)],'format':'iso','profile_id':'owned_game_123',
        'launch':{'kind':'emulator','path':str(path),'archive_member':'disc.iso'},**fields}


class DesktopLocalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.cfg=Config(data_dir=self.root/'data',cache_dir=self.root/'cache',public_url='http://127.0.0.1:18765')
    def tearDown(self):self.tmp.cleanup()

    def test_loopback_override_preserves_files_data_token_cache_and_runtime(self):
        cfg=self.root/'gbox.toml'
        text='data_dir="data"\napi_host="0.0.0.0"\napi_port=8765\npublic_url="http://remote.example:8765"\n'
        cfg.write_text(text);loaded=D.local_config(cfg,18766)
        self.assertEqual((loaded.api_host,loaded.api_port,loaded.public_url),('127.0.0.1',18766,'http://127.0.0.1:18766'))
        self.assertEqual(loaded.data_dir,self.root/'data');self.assertEqual(cfg.read_text(),text)
        for port in (0,80,65536,True):
            with self.assertRaises(ValueError):D.local_config(cfg,port)

    def test_network_owned_data_is_not_silently_moved_or_mounted(self):
        cfg=self.root/'gbox.toml';cfg.write_text('data_dir="//offline.example/share/data"\n')
        with self.assertRaisesRegex(ValueError,'configured network paths were preserved'):D.local_config(cfg)

    def test_existing_local_game_keeps_original_id_profile_and_launch_recipe(self):
        file=self.root/'disc.iso';file.write_bytes(b'owned');row=entry(file,size=5)
        before=copy.deepcopy(row);result=D.local_entry(row,self.cfg)
        self.assertEqual(result['game_id'],row['game_id']);self.assertEqual(result['profile_id'],row['profile_id'])
        self.assertEqual(result['launch']['archive_member'],'disc.iso');self.assertEqual(result['launch']['path'],str(file))
        self.assertTrue(result['local_availability']['verified']);self.assertEqual(row,before)

    def test_cached_copy_is_available_with_no_unc_stat_or_renamed_game_identity(self):
        file=self.cfg.cache/'owned_game_123'/'disc.iso';file.parent.mkdir(parents=True);file.write_bytes(b'owned')
        row=entry('//offline.example/share/disc.iso',size=5)
        original=Path.is_file
        def guarded(path):
            self.assertFalse(D.network_path(path),'offline source must never be statted')
            return original(path)
        with patch.object(Path,'is_file',guarded):result=D.local_entry(row,self.cfg)
        self.assertEqual(result['source_paths'],[str(file)])
        self.assertEqual(result['game_id'],'owned_game_123');self.assertIsNone(result['library'])

    def test_missing_incomplete_or_path_traversal_rows_do_not_enter_local_catalog(self):
        file=self.root/'disc.iso';file.write_bytes(b'short')
        self.assertIsNone(D.local_entry(entry(file,size=500),self.cfg))
        self.assertIsNone(D.local_entry(entry(file,game_id='../outside'),self.cfg))
        self.assertIsNone(D.local_entry(entry(self.root/'missing.iso'),self.cfg))
        partial=self.root/'disc.iso.part';partial.write_bytes(b'owned')
        self.assertIsNone(D.local_entry(entry(partial),self.cfg))

    def test_native_library_mapping_is_checked_locally_and_original_metadata_unchanged(self):
        library=self.root/'games';library.mkdir();file=library/'disc.iso';file.write_bytes(b'owned')
        cfg=self.cfg.model_copy(update={'libraries':[Library(id='owned',paths={HOST_OS:str(library)})]})
        row=entry('//offline.example/disc.iso',library='owned',rel_path='disc.iso')
        self.assertEqual(D.local_entry(row,cfg)['launch']['path'],str(file))
        row['rel_path']='../outside.iso';self.assertIsNone(D.local_entry(row,cfg))

    def test_seeding_only_verifies_available_files_and_never_submits_launches_or_remote_jobs(self):
        file=self.root/'disc.iso';file.write_bytes(b'owned');saved=[]
        class Store:
            def upsert_catalog(self,rows):saved.extend(rows)
        count=D.seed_catalog(self.cfg,Store(),[entry(file),entry(self.root/'missing.iso'),None,{}])
        self.assertEqual(count,1);self.assertEqual(len(saved),1);self.assertNotIn('session_id',saved[0])

    def test_local_service_identity_is_exact_to_config_and_data_and_contains_no_token(self):
        one=D.installation_key(self.root/'gbox.toml',self.cfg)
        other=D.installation_key(self.root/'different.toml',self.cfg)
        self.assertEqual(len(one),64);self.assertNotEqual(one,other)
        # the same checkout path on two PCs must not pair as one authority
        nuc=D.installation_key(self.root/'gbox.toml',self.cfg,machine='i9-NUC')
        jay=D.installation_key(self.root/'gbox.toml',self.cfg,machine='JAYBUILTFINALE')
        self.assertNotEqual(nuc,jay);self.assertEqual(jay,D.installation_key(self.root/'gbox.toml',self.cfg,machine='jaybuiltfinale'))

    def test_a_live_native_owner_blocks_new_worker_without_kill_or_adoption(self):
        from gbox import worker
        from gbox.worker_results import ResultOutbox
        local=D.LocalWorker(self.cfg,'test-local');waits=[]
        class Stop:
            done=False
            def is_set(self):return self.done
            def wait(self,seconds):waits.append(seconds);self.done=True
        local.stop=Stop()
        with patch.object(ResultOutbox,'protected_sessions',return_value=['original-native-session']), \
             patch.object(worker,'run',side_effect=AssertionError('must not start a second worker')):
            local._run()
        self.assertEqual(waits,[3.]);self.assertEqual(local.state['state'],'stopped')

    def test_legacy_idle_worker_using_same_runtime_blocks_duplicate_dispatcher(self):
        from types import SimpleNamespace
        import sys
        config=self.root/'gbox.toml';config.write_text('data_dir="data"\n')
        process=SimpleNamespace(pid=12345,info={'cmdline':['python','-m','gbox','--config',str(config),'worker',
                                  '--server','http://old-central.example:8765']})
        fake=SimpleNamespace(process_iter=lambda *args:[process],Error=RuntimeError)
        with patch.dict(sys.modules,{'psutil':fake}),patch.object(D,'HOST_OS','windows'):
            self.assertEqual(D.legacy_worker_owner(self.cfg),12345)
            process.info['cmdline'][3]='gbox.desktop_local'
            self.assertIsNone(D.legacy_worker_owner(self.cfg))

    def test_installed_steam_directory_requires_exact_completed_native_manifest(self):
        folder=self.root/'Steam'/'steamapps'/'common'/'Owned Game';folder.mkdir(parents=True)
        manifest=folder.parent.parent/'appmanifest_123.acf'
        manifest.write_text('"AppState" {"appid" "123" "installdir" "Owned Game" "StateFlags" "4"}')
        row=entry(folder,game_id='steam-123',platform='pc_steam',format='steam_app',size=999999,
                  launch={'kind':'steam','appid':'123'})
        verified=D.local_entry(row,self.cfg)
        self.assertIsNotNone(verified);self.assertEqual(verified['launch'],row['launch'])
        self.assertEqual(verified['local_availability']['source'],'installed_steam_manifest')
        manifest.write_text('"AppState" {"appid" "456" "installdir" "Owned Game" "StateFlags" "4"}')
        self.assertIsNone(D.local_entry(row,self.cfg))
        self.assertIsNone(D.local_entry(entry(folder),self.cfg),'arbitrary directories are not launch-ready')

    def test_extracted_ps3_native_catalog_shape_preserves_eboot_path_and_recipe(self):
        eboot=self.root/'Owned Game'/'PS3_GAME'/'USRDIR'/'EBOOT.BIN';eboot.parent.mkdir(parents=True);eboot.write_bytes(b'ELF')
        row=entry(eboot,platform='ps3',format='ps3_folder',size=3,
                  launch={'kind':'emulator','platform':'ps3','path':str(eboot)})
        verified=D.local_entry(row,self.cfg)
        self.assertEqual(verified['launch'],row['launch']);self.assertEqual(verified['source_paths'],row['source_paths'])


if __name__=='__main__':unittest.main()
