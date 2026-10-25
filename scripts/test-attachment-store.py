"""Pure ledger regressions: no AstrBot, network, model calls or user data."""
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

p=Path(__file__).resolve().parents[1]/'extensions/astrbot_plugin_qq_persona_models/attachment_store.py'
spec=importlib.util.spec_from_file_location('attachment_store',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.now=1000.;self.store=m.AttachmentStore(Path(self.temp.name),clock=lambda:self.now)
    def tearDown(self):self.temp.cleanup()
    def record(self,scope='s',mid='one',sender='A',count=1,kind='image'):
        return self.store.record(scope,'bot:G',mid,sender,sender,'message '+mid,[{'type':kind,'filename':'x.txt','source':{'path':'private'},'ordinal':i} for i in range(count)])
    def ready(self,record,data=b'pixels'):
        for asset_id in record['ids']:self.store.retain(record['scope'],record['epoch'],asset_id,data,'image/png','png')
    def test_duplicate_event_is_idempotent(self):
        a=self.record();b=self.record();self.assertEqual(a,b);self.assertEqual(self.store.stats()['messages'],1)
    def test_source_brief_uses_original_generated_request_and_scope(self):
        request=self.store.record('s','bot:G','request','A','A','基于角色原图生成完整三视图',[])
        generated=self.store.record('s','bot:G','result','bot','AI','已发送图片',[{'type':'image','source':{'generated':True,'request_seq':request['seq']}}],kind='generated')
        snapshot=self.store.snapshot('s');brief=self.store.source_briefs(snapshot,generated['ids'])
        self.assertEqual(brief[generated['ids'][0]]['source_text'],'基于角色原图生成完整三视图')
        with self.assertRaises(ValueError):self.store.source_briefs(self.store.snapshot('other'),generated['ids'])
        self.store.invalidate('s')
        with self.assertRaises(ValueError):self.store.source_briefs(snapshot,generated['ids'])
    def test_source_briefs_have_one_global_character_budget(self):
        for i in range(12):self.store.record('s','bot:G',str(i),'A','A','长资料'*100,[{'type':'image','source':{}}])
        snapshot=self.store.snapshot('s');briefs=self.store.source_briefs(snapshot,snapshot['ids'])
        self.assertLessEqual(sum(len(r['source_text']) for r in briefs.values()),640)
    def test_multiple_messages_and_image_positions_survive(self):
        a=self.record(count=2);b=self.record(mid='two');self.assertEqual(len(self.store.snapshot('s')['ids']),3);self.assertNotEqual(a['ids'][0],a['ids'][1]);self.assertNotEqual(a['ids'][0],b['ids'][0])
    def test_scope_and_authorized_ids_are_enforced(self):
        a=self.record();self.ready(a);snapshot=self.store.snapshot('other')
        with self.assertRaises(ValueError):self.store.resolve(snapshot,a['ids'])
    def test_inflight_snapshot_does_not_see_new_message(self):
        a=self.record();snapshot=self.store.snapshot('s');b=self.record(mid='two');self.ready(b)
        with self.assertRaises(ValueError):self.store.resolve(snapshot,b['ids'])
        self.assertEqual(self.store.messages(snapshot,message_id='two'),[])
    def test_boundary_freezes_at_ingress(self):
        a=self.record();self.record(mid='later');s=self.store.snapshot('s',boundary=a['seq']);self.assertEqual(s['ids'],a['ids'])
    def test_pruning_all_messages_never_reuses_sequence(self):
        a=self.record();snapshot=self.store.snapshot('s');self.now+=604801;self.store.prune(force=True)
        self.assertEqual(self.store.stats()['messages'],0)
        b=self.record(mid='later');self.assertGreater(b['seq'],a['seq'])
        self.assertEqual(self.store.messages(snapshot,message_id='later'),[])
    def test_reset_rejects_late_publication_and_old_ids(self):
        a=self.record();s=self.store.snapshot('s');self.store.invalidate('s')
        with self.assertRaises(ValueError):self.store.retain('s',a['epoch'],a['ids'][0],b'data','image/png','png')
        with self.assertRaises(ValueError):self.store.resolve(s,a['ids'])
        with self.assertRaises(ValueError):self.store.record('s','bot:G','late','A','A','',[],expected_epoch=a['epoch'])
    def test_restart_retains_pixels_and_epoch(self):
        a=self.record();self.ready(a);other=m.AttachmentStore(self.store.root,clock=lambda:self.now)
        rows=other.resolve(other.snapshot('s'),a['ids']);self.assertEqual(Path(rows[0]['path']).read_bytes(),b'pixels')
    def test_missing_or_corrupt_pixels_are_not_silently_used(self):
        a=self.record();self.ready(a);s=self.store.snapshot('s');row=self.store.resolve(s,a['ids'])[0];Path(row['path']).write_bytes(b'other')
        with self.assertRaises(ValueError):self.store.resolve(s,a['ids'])
        Path(row['path']).unlink()
        with self.assertRaises(ValueError):self.store.resolve(s,a['ids'])
    def test_task_input_copy_survives_cache_cleanup(self):
        a=self.record();self.ready(a);s=self.store.snapshot('s');paths=self.store.freeze(s,a['ids'],'task')
        self.now+=100;self.store.settings['scope_bytes']=0;self.store.prune(force=True)
        # Task pins have their own bounded lifetime; before it expires they are
        # independent of an asset that has been explicitly evicted.
        self.assertEqual(self.store.public(self.store._row(a['ids'][0]))['state'],'evicted')
        self.assertTrue(Path(paths[0]).is_file())
        self.assertEqual(Path(paths[0]).read_bytes(),b'pixels')
    def test_task_directory_isolated_even_if_platform_message_ids_collide(self):
        a=self.record(scope='a');b=self.record(scope='b');self.ready(a,b'red');self.ready(b,b'blue')
        pa=self.store.freeze(self.store.snapshot('a'),a['ids'],'same-request')
        pb=self.store.freeze(self.store.snapshot('b'),b['ids'],'same-request')
        self.assertNotEqual(pa,pb);self.assertEqual(Path(pa[0]).read_bytes(),b'red')
    def test_late_generated_task_does_not_become_newest_request(self):
        a=self.record(mid='first');b=self.record(mid='second')
        self.store.record('s','bot:G','late','bot','AI','',[{'type':'image','source':{'generated':True,'request_seq':a['seq']}}],kind='generated')
        rows=self.store.snapshot('s')['catalog']
        self.assertEqual(rows[0]['id'],b['ids'][0])
    def test_frozen_input_independent_of_source_removal(self):
        a=self.record();self.ready(a);s=self.store.snapshot('s');paths=self.store.freeze(s,a['ids'],'task')
        self.store._path(self.store._row(a['ids'][0])).unlink();self.assertEqual(Path(paths[0]).read_bytes(),b'pixels')
    def test_budget_eviction_is_visible_and_bounded(self):
        self.store.settings.update(total_bytes=3,scope_bytes=3)
        a=self.record();self.ready(a,b'xx');b=self.record(mid='two');self.ready(b,b'yy');self.store.prune(force=True)
        self.assertEqual(self.store.stats()['ready_bytes'],2)
        with self.assertRaises(ValueError):self.store.resolve(self.store.snapshot('s'),a['ids'])
    def test_query_extends_only_current_scope_snapshot(self):
        a=self.record(mid='target');self.ready(a)
        for i in range(24):self.record(mid='next'+str(i))
        s=self.store.snapshot('s',limit=2);self.assertNotIn(a['ids'][0],s['ids'])
        found=self.store.messages(s,query='target');self.assertTrue(found);self.assertIn(a['ids'][0],s['ids'])
        self.assertEqual(self.store.messages(self.store.snapshot('other'),query='target'),[])
    def test_public_catalog_never_contains_private_source(self):
        self.record();self.assertNotIn('private',str(self.store.snapshot('s')))

    def test_browser_includes_image_only_and_empty_text_events(self):
        a=self.store.record('s','bot:G','image-only','A','A','',[{'type':'image','ordinal':0}])
        rows=self.store.browse(self.store.snapshot('s'))['messages']
        self.assertEqual(rows[0]['message_id'],'image-only');self.assertEqual(rows[0]['attachments'][0]['id'],a['ids'][0])

    def test_browser_cursor_boundary_scope_and_filters(self):
        for i in range(6):self.record(mid='m'+str(i))
        snap=self.store.snapshot('s');first=self.store.browse(snap,limit=2)
        self.record(mid='future');second=self.store.browse(snap,limit=2,cursor=first['next_cursor'])
        self.assertFalse(set(r['message_id'] for r in first['messages'])&set(r['message_id'] for r in second['messages']))
        self.assertNotIn('future',str(second))
        for wrong,kw in [(self.store.snapshot('other'),{}),(snap,{'sender_id':'B'}),(snap,{'direction':'newer'})]:
            with self.assertRaises(ValueError):self.store.browse(wrong,cursor=first['next_cursor'],**kw)

    def test_browser_timestamp_sender_reply_filters(self):
        self.store.record('s','bot:G','a','A','A','one',[]);self.now+=10
        self.store.record('s','bot:G','b','B','B','two',[{'type':'reply','message_id':'a'}]);self.now+=10
        self.store.record('s','bot:G','c','A','A','three',[])
        snap=self.store.snapshot('s')
        self.assertEqual([r['message_id'] for r in self.store.browse(snap,sender_id='B',reply_to='a',since=1005,until=1015)['messages']],['b'])
        self.assertEqual([r['message_id'] for r in self.store.browse(snap,direction='newer',limit=2)['messages']],['a','b'])

    def test_browser_literal_like_and_reset(self):
        self.store.record('s','bot:G','percent','A','A','100%_literal',[]);self.record(mid='other')
        snap=self.store.snapshot('s');found=self.store.browse(snap,query='%_')
        self.assertEqual([r['message_id'] for r in found['messages']],['percent'])
        self.store.invalidate('s')
        with self.assertRaises(ValueError):self.store.browse(snap)


if __name__=='__main__':unittest.main(verbosity=2)
