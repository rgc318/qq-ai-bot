"""History retrieval, old-session continuity and isolation; no network."""
import concurrent.futures
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

path=Path(__file__).resolve().parents[1]/'extensions/astrbot_plugin_qq_persona_models/chat_history_store.py'
spec=importlib.util.spec_from_file_location('chat_history_store',path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.root=Path(self.tmp.name)
        self.store=module.ChatHistoryStore(self.root/'history.db')
        self.namespace='group:aiocqhttp:qq-snowluma:347440128'
        self.owner={'scope':module.scope_id(self.namespace,'大肥鱼'),'namespace':self.namespace,'persona':'大肥鱼','cid':'old-conversation','umo':'qq-snowluma:GroupMessage:347440128'}
        self.history=[{'role':'user','content':'社团集合地点和暗号是什么？'},{'role':'assistant','content':'集合在北门图书馆。暗号是纸鸢A731。'}]
    def tearDown(self):self.tmp.cleanup()
    def test_cross_new_conversation_and_search_original(self):
        self.store.ingest(self.owner,self.history)
        new={**self.owner,'cid':'new-conversation'}
        self.store.ingest(new,[{'role':'user','content':'我们换一个新会话。'}])
        result=self.store.search(new['scope'],'社团 集合 暗号')
        self.assertIn('纸鸢A731',result['results'][0]['excerpt'])
        self.assertEqual(result['results'][0]['conversation_id'],'old-conversation')
    def test_persona_group_and_member_scope_isolation(self):
        self.store.ingest(self.owner,self.history)
        record=self.store.search(self.owner['scope'],'暗号')['results'][0]['record_id']
        scopes=[module.scope_id(self.namespace,'龙娘'),module.scope_id('group:aiocqhttp:qq-snowluma:other','大肥鱼'),module.scope_id('member:aiocqhttp:qq-snowluma:347440128:B','大肥鱼')]
        for scope in scopes:
            self.assertEqual(self.store.search(scope,'暗号')['count'],0)
            self.assertFalse(self.store.read(scope,record)['found'])
    def test_overlapping_archive_deduplicated(self):
        self.assertEqual(self.store.ingest(self.owner,self.history),1)
        self.assertEqual(self.store.ingest(self.owner,self.history,'another-source'),0)
        self.assertEqual(self.store.stats()['documents'],1)
    def test_full_text_read_is_paginated(self):
        body='这是一段长配置说明。'*1000+'结尾是查验值Z928。'
        self.store.ingest(self.owner,[{'role':'user','content':'完整配置'},{'role':'assistant','content':body}])
        row=self.store.search(self.owner['scope'],'Z928')['results'][0]
        self.assertIn('Z928',row['excerpt'])
        combined='';offset=0
        while True:
            page=self.store.read(self.owner['scope'],row['record_id'],offset)
            self.assertLessEqual(len(page['text']),3200)
            combined+=page['text']
            if page['next_offset'] is None:break
            offset=page['next_offset']
        self.assertEqual(combined,list(module.text_turns([{'role':'user','content':'完整配置'},{'role':'assistant','content':body}]))[0])
    def test_topic_digest_is_bounded_and_not_full_answer(self):
        self.store.ingest(self.owner,self.history)
        catalog=self.store.catalog(self.owner['scope'],100)
        self.assertLessEqual(len(catalog),100)
        self.assertIn('暗号',catalog)
        self.assertNotIn('纸鸢A731',catalog)
    def test_no_system_tool_payload_or_image_bytes_indexed(self):
        rows=[{'role':'system','content':'SYSTEMSECRET'},{'role':'user','content':[{'type':'text','text':'看看这张图'},{'type':'image_url','image_url':{'url':'data:image/png;base64,IMAGESECRET'}}]},{'role':'tool','content':'TOOLSECRET'},{'role':'assistant','content':'看过图片了。'}]
        self.store.ingest(self.owner,rows)
        for secret in ['SYSTEMSECRET','TOOLSECRET','IMAGESECRET']:
            self.assertEqual(self.store.search(self.owner['scope'],secret)['count'],0)
    def test_empty_and_operator_query_are_data(self):
        self.store.ingest(self.owner,self.history)
        self.assertEqual(self.store.search(self.owner['scope'],'')['count'],0)
        self.store.search(self.owner['scope'],'" OR scope:other * - ()')
        self.assertFalse(self.store.read(self.owner['scope'],'../../secret')['found'])
    def test_conversation_owner_cannot_be_reassigned(self):
        self.store.ingest(self.owner,self.history)
        with self.assertRaises(ValueError):self.store.ingest({**self.owner,'scope':'other'},self.history)
    def test_concurrent_ingest_keeps_one_copy(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            added=list(pool.map(lambda _:self.store.ingest(self.owner,self.history),range(8)))
        self.assertEqual(sum(added),1)
    def test_legacy_archive_requires_verified_binding(self):
        native=self.root/'native.db';folder=self.root/'archive';folder.mkdir()
        db=sqlite3.connect(native)
        db.execute('CREATE TABLE conversations(conversation_id TEXT,user_id TEXT,persona_id TEXT,platform_id TEXT,content TEXT)')
        db.execute('INSERT INTO conversations VALUES(?,?,?,?,?)',(self.owner['cid'],self.owner['umo'],'大肥鱼','aiocqhttp','[]'))
        db.commit();db.close()
        def archive(cid,persona):
            data=json.dumps({'conversation_id':cid,'persona':persona,'history':self.history},ensure_ascii=False).encode()
            (folder/(hashlib.sha256(data).hexdigest()+'.json.gz')).write_bytes(gzip.compress(data))
        archive(self.owner['cid'],'大肥鱼');archive('unknown','大肥鱼');archive(self.owner['cid'],'龙娘')
        binding={'bindings':{self.namespace:{'personas':{'大肥鱼':self.owner['cid']}}}}
        result=self.store.bootstrap(native,binding,folder,['347440128'])
        self.assertEqual(result['archives_imported'],1)
        self.assertEqual(result['archives_skipped'],2)
        self.assertEqual(result['documents'],1)
        again=self.store.bootstrap(native,binding,folder,['347440128'])
        self.assertEqual(again['added'],0)
    def test_unbound_member_archive_never_becomes_public_group(self):
        native=self.root/'native.db';folder=self.root/'archive';folder.mkdir()
        db=sqlite3.connect(native)
        db.execute('CREATE TABLE conversations(conversation_id TEXT,user_id TEXT,persona_id TEXT,platform_id TEXT,content TEXT)')
        db.execute('INSERT INTO conversations VALUES(?,?,?,?,?)',('member-cid',self.owner['umo'],'大肥鱼','aiocqhttp',json.dumps(self.history)))
        db.commit();db.close()
        result=self.store.bootstrap(native,{},folder,['347440128'])
        self.assertEqual(result['documents'],0)
if __name__=='__main__':unittest.main(verbosity=2)
