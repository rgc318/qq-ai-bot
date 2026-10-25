"""Scoped message/attachment ledger. No model calls or platform I/O."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import time


class AttachmentStore:
    def __init__(self,root,settings=None,clock=time.time):
        self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True)
        self.blobs=self.root/'blobs';self.blobs.mkdir(exist_ok=True)
        self.tasks=self.root/'tasks';self.tasks.mkdir(exist_ok=True)
        self.path=self.root/'attachments.sqlite3';self.settings=settings or {};self.clock=clock
        self.lock=threading.RLock();self.last_prune=0
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS scopes(scope TEXT PRIMARY KEY,epoch INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY,scope TEXT NOT NULL,epoch INTEGER NOT NULL,
              message_id TEXT NOT NULL,umo TEXT NOT NULL,sender TEXT NOT NULL,name TEXT NOT NULL,text TEXT NOT NULL,
              received REAL NOT NULL,parts TEXT NOT NULL,kind TEXT NOT NULL,UNIQUE(scope,epoch,message_id));
            CREATE INDEX IF NOT EXISTS event_scope ON events(scope,epoch,seq);
            CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,scope TEXT NOT NULL,epoch INTEGER NOT NULL,
              seq INTEGER NOT NULL,message_id TEXT NOT NULL,sender TEXT NOT NULL,name TEXT NOT NULL,
              ordinal INTEGER NOT NULL,kind TEXT NOT NULL,filename TEXT NOT NULL,source TEXT NOT NULL,
              created REAL NOT NULL,expires REAL NOT NULL,state TEXT NOT NULL DEFAULT 'pending',
              digest TEXT NOT NULL DEFAULT '',suffix TEXT NOT NULL DEFAULT '',mime TEXT NOT NULL DEFAULT '',
              size INTEGER NOT NULL DEFAULT 0,parents TEXT NOT NULL DEFAULT '[]',error TEXT NOT NULL DEFAULT '');
            CREATE INDEX IF NOT EXISTS asset_scope ON assets(scope,epoch,seq);
            CREATE TABLE IF NOT EXISTS task_inputs(id TEXT PRIMARY KEY,scope TEXT NOT NULL,epoch INTEGER NOT NULL,
              created REAL NOT NULL,parents TEXT NOT NULL,paths TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS event_clock(singleton INTEGER PRIMARY KEY,value INTEGER NOT NULL);
            INSERT OR IGNORE INTO event_clock SELECT 1,coalesce(max(seq),0) FROM events;
            ''')

    @contextmanager
    def db(self):
        with self.lock:
            db=sqlite3.connect(self.path,timeout=2);db.row_factory=sqlite3.Row
            try:yield db;db.commit()
            finally:db.close()

    def epoch(self,scope):
        with self.db() as db:
            row=db.execute('SELECT epoch FROM scopes WHERE scope=?',(scope,)).fetchone()
            if row:return row[0]
            db.execute('INSERT OR IGNORE INTO scopes(scope) VALUES(?)',(scope,))
            return 0

    def invalidate(self,scope):
        with self.db() as db:
            db.execute('INSERT OR IGNORE INTO scopes(scope) VALUES(?)',(scope,))
            db.execute('UPDATE scopes SET epoch=epoch+1 WHERE scope=?',(scope,))
        return self.epoch(scope)

    def record(self,scope,umo,message_id,sender,name,text,parts,kind='user',parents=(),expected_epoch=None):
        """One immutable event per received platform ID; quote origin stays explicit."""
        epoch=self.epoch(scope)
        if expected_epoch is not None and epoch!=expected_epoch:raise ValueError('会话已清空，拒绝迟到的附件登记')
        with self.db() as db:
            if self.epoch(scope)!=epoch:raise ValueError('会话范围已变更')
            db.execute('UPDATE event_clock SET value=value+1 WHERE singleton=1')
            allocated=db.execute('SELECT value FROM event_clock WHERE singleton=1').fetchone()[0]
            db.execute('INSERT OR IGNORE INTO events(seq,scope,epoch,message_id,umo,sender,name,text,received,parts,kind) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                       (allocated,scope,epoch,str(message_id),umo,sender,name[:80],text[:12000],self.clock(),'[]',kind))
            seq=db.execute('SELECT seq FROM events WHERE scope=? AND epoch=? AND message_id=?',(scope,epoch,str(message_id))).fetchone()[0]
            public=[];ids=[]
            for i,part in enumerate(parts):
                if part.get('type') in ('image','document','audio','video','unsupported'):
                    origin=str(part.get('origin_message') or message_id)
                    ordinal=int(part.get('ordinal',i));key=f'{scope}|{epoch}|{message_id}|{origin}|{ordinal}|{part["type"]}'
                    asset_id='a_'+hashlib.sha256(key.encode()).hexdigest()[:24]
                    db.execute('''INSERT OR IGNORE INTO assets(id,scope,epoch,seq,message_id,sender,name,ordinal,kind,filename,source,created,expires,parents)
                      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(asset_id,scope,epoch,seq,origin,str(part.get('sender') or sender),str(part.get('sender_name') or name)[:80],ordinal,part['type'],str(part.get('filename') or '')[:160],json.dumps(part.get('source',{})),self.clock(),self.clock()+float(self.settings.get('media_ttl_seconds',86400)),json.dumps(list(parents))))
                    ids.append(asset_id);public.append({'type':part['type'],'attachment_id':asset_id,'origin_message':origin,'ordinal':ordinal})
                else:public.append({k:v for k,v in part.items() if k in ('type','message_id','user_id','text')})
            db.execute('UPDATE events SET parts=? WHERE seq=?',(json.dumps(public,ensure_ascii=False),seq))
        return {'scope':scope,'epoch':epoch,'seq':seq,'ids':ids}

    def _row(self,asset_id):
        with self.db() as db:return db.execute('SELECT * FROM assets WHERE id=?',(asset_id,)).fetchone()

    def source(self,scope,epoch,asset_id):
        row=self._row(asset_id)
        if not row or row['scope']!=scope or row['epoch']!=epoch or self.epoch(scope)!=epoch:raise ValueError('附件不在当前会话范围')
        return dict(row)

    def retain(self,scope,epoch,asset_id,data,mime,suffix):
        if not data or len(data)>int(self.settings.get('max_file_bytes',20*1024*1024)):raise ValueError('附件为空或超过大小上限')
        if not re.fullmatch(r'[a-z0-9]{1,10}',suffix):raise ValueError('不支持的附件格式')
        digest=hashlib.sha256(data).hexdigest();target=self.blobs/(digest+'.'+suffix)
        with self.db() as db:
            row=self.source(scope,epoch,asset_id)
            if row['state']=='ready' and self._path(row).is_file():return row['digest']
            # Every publishing step checks scope generation after asynchronous I/O.
            if self.epoch(scope)!=epoch:raise ValueError('附件读取期间会话已清空')
            if target.is_symlink():raise ValueError('缓存路径无效')
            if not target.exists():
                temp=target.with_suffix(target.suffix+'.tmp')
                temp.write_bytes(data);os.replace(temp,target)
            db.execute('UPDATE assets SET state=\'ready\',digest=?,suffix=?,mime=?,size=?,error=\'\' WHERE id=?',(digest,suffix,mime,len(data),asset_id))
        return digest

    def failed(self,scope,epoch,asset_id,error,state='failed'):
        with self.db() as db:
            db.execute('UPDATE assets SET state=?,error=? WHERE id=? AND scope=? AND epoch=? AND state!=\'ready\'',(state,str(error)[:80],asset_id,scope,epoch))

    def _path(self,row):
        if not re.fullmatch(r'[0-9a-f]{64}',row['digest']) or not re.fullmatch(r'[a-z0-9]{1,10}',row['suffix']):return self.blobs/'missing'
        return self.blobs/(row['digest']+'.'+row['suffix'])

    def public(self,row):
        state=row['state']
        if row['expires']<=self.clock():state='expired'
        elif state=='ready' and not self._path(row).is_file():state='expired'
        return {'id':row['id'],'type':row['kind'],'message_id':row['message_id'],'sender':row['sender'],'name':row['name'],
                'position':row['ordinal'],'filename':row['filename'],'state':state,'age_seconds':round(max(0,self.clock()-row['created']),1),'bytes':row['size'],
                'generated':bool(json.loads(row['source']).get('generated')),'request_order':json.loads(row['source']).get('request_seq',row['seq'])}

    def snapshot(self,scope,limit=20,boundary=None):
        epoch=self.epoch(scope)
        with self.db() as db:
            seq=db.execute('SELECT coalesce(max(seq),0) FROM events WHERE scope=? AND epoch=?',(scope,epoch)).fetchone()[0]
            if boundary is not None:seq=min(seq,int(boundary))
            rows=db.execute('SELECT * FROM assets WHERE scope=? AND epoch=? AND seq<=? ORDER BY seq DESC,ordinal LIMIT 80',(scope,epoch,seq)).fetchall()
            rows=sorted(rows,key=lambda r:(json.loads(r['source']).get('request_seq',r['seq']),r['seq'],-r['ordinal']),reverse=True)[:max(1,min(limit,80))]
        return {'scope':scope,'epoch':epoch,'seq':seq,'ids':[r['id'] for r in rows],'catalog':[self.public(r) for r in rows]}

    def resolve(self,snapshot,ids,kind=None,max_count=4):
        if not isinstance(ids,list) or not 1<=len(ids)<=max_count or len(set(ids))!=len(ids):raise ValueError('请提供目录中互不重复的附件ID列表')
        if self.epoch(snapshot['scope'])!=snapshot['epoch']:raise ValueError('本轮会话已失效')
        result=[]
        for asset_id in ids:
            if asset_id not in snapshot['ids']:raise ValueError('附件不在本轮授权目录，请先读取对应消息')
            row=self.source(snapshot['scope'],snapshot['epoch'],asset_id)
            if row['seq']>snapshot['seq'] or kind and row['kind']!=kind:raise ValueError('附件类型或消息顺序不符')
            if self.public(row)['state']!='ready':raise ValueError('附件内容不可用：'+self.public(row)['state'])
            path=self._path(row)
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=row['digest']:raise ValueError('附件完整性检查失败')
            result.append({**row,'path':str(path)})
        return result

    def messages(self,snapshot,message_id='',query='',limit=3):
        if self.epoch(snapshot['scope'])!=snapshot['epoch']:raise ValueError('本轮会话已失效')
        args=[snapshot['scope'],snapshot['epoch'],snapshot['seq']]
        sql='SELECT * FROM events WHERE scope=? AND epoch=? AND seq<=?'
        if message_id:sql+=' AND message_id=?';args.append(str(message_id))
        elif query:
            sql+=' AND (text LIKE ? OR EXISTS(SELECT 1 FROM assets a WHERE a.seq=events.seq AND a.filename LIKE ?))'
            args.extend(['%'+str(query)[:160]+'%']*2)
        with self.db() as db:rows=db.execute(sql+' ORDER BY seq DESC LIMIT ?',(*args,max(1,min(int(limit),5)))).fetchall()
        output=[]
        for row in rows:
            parts=json.loads(row['parts']);attachments=[]
            for part in parts:
                asset_id=part.get('attachment_id')
                if asset_id:
                    asset=self.source(snapshot['scope'],snapshot['epoch'],asset_id)
                    if asset_id not in snapshot['ids']:snapshot['ids'].append(asset_id)
                    attachments.append(self.public(asset))
            output.append({'message_id':row['message_id'],'sender':row['sender'],'name':row['name'],'text':row['text'][:3200],'received_at':row['received'],'parts':parts,'attachments':attachments})
        return output

    def freeze(self,snapshot,ids,task_id):
        with self.lock:return self._freeze(snapshot,ids,task_id)

    def browse(self,snapshot,query='',sender_id='',reply_to='',since=0,until=0,cursor='',direction='older',limit=5):
        """Browse original events, including image-only messages, in one scope."""
        import base64
        import math
        if self.epoch(snapshot['scope'])!=snapshot['epoch']:raise ValueError('本轮会话已失效')
        if direction not in ('older','newer'):raise ValueError('direction必须为older或newer')
        limit=max(1,min(int(limit),10));since=float(since or 0);until=float(until or 0)
        if not math.isfinite(since) or not math.isfinite(until) or since<0 or until<0 or until and since>until:raise ValueError('时间范围无效')
        filters=[str(query)[:160],str(sender_id)[:120],str(reply_to)[:120],since,until]
        fingerprint=hashlib.sha256(json.dumps(filters,ensure_ascii=False).encode()).hexdigest()[:16]
        anchor=snapshot['seq']+1 if direction=='older' else 0
        if cursor:
            if not isinstance(cursor,str) or len(cursor)>4096:raise ValueError('分页游标无效')
            try:token=json.loads(base64.urlsafe_b64decode(cursor+'='*(-len(cursor)%4)))
            except Exception:raise ValueError('分页游标无效') from None
            if not isinstance(token,list) or len(token)!=6 or token[:3]!=[snapshot['scope'],snapshot['epoch'],snapshot['seq']] or token[4:]!=[direction,fingerprint] or type(token[3]) is not int:raise ValueError('游标不属于本轮范围或筛选条件')
            anchor=token[3]
        sql='SELECT seq,message_id FROM events WHERE scope=? AND epoch=? AND seq<=? AND seq'+(' < ?' if direction=='older' else ' > ?')
        args=[snapshot['scope'],snapshot['epoch'],snapshot['seq'],anchor]
        if query:
            sql+=" AND text LIKE ? ESCAPE '\\'"
            args.append('%'+str(query)[:160].replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%')
        if sender_id:sql+=' AND sender=?';args.append(str(sender_id))
        if since:sql+=' AND received>=?';args.append(since)
        if until:sql+=' AND received<=?';args.append(until)
        if reply_to:
            sql+=" AND EXISTS (SELECT 1 FROM json_each(events.parts) p WHERE json_extract(p.value,'$.type')='reply' AND json_extract(p.value,'$.message_id')=?)"
            args.append(str(reply_to))
        sql+=' ORDER BY seq '+('DESC' if direction=='older' else 'ASC')+' LIMIT ?'
        with self.db() as db:rows=db.execute(sql,(*args,limit+1)).fetchall()
        more=len(rows)>limit;rows=rows[:limit];messages=[]
        for row in rows:messages.extend(self.messages(snapshot,message_id=row['message_id'],limit=1))
        token=[snapshot['scope'],snapshot['epoch'],snapshot['seq'],rows[-1]['seq'],direction,fingerprint] if more and rows else None
        return {'messages':list(reversed(messages)) if direction=='older' else messages,
                'next_cursor':base64.urlsafe_b64encode(json.dumps(token,ensure_ascii=False).encode()).decode().rstrip('=') if token else '',
                'direction':direction,'has_more':more,'snapshot_boundary':snapshot['seq']}

    def _freeze(self,snapshot,ids,task_id):
        rows=self.resolve(snapshot,ids,'image')
        key=hashlib.sha256(json.dumps([snapshot['scope'],snapshot['epoch'],str(task_id)]).encode()).hexdigest()[:24]
        with self.db() as db:existing=db.execute('SELECT id,scope,paths FROM task_inputs WHERE id!=?',(key,)).fetchall()
        total=scope_total=0
        for task in existing:
            size=sum(Path(p).stat().st_size for p in json.loads(task['paths']) if Path(p).is_file())
            total+=size
            if task['scope']==snapshot['scope']:scope_total+=size
        size=sum(r['size'] for r in rows)
        if total+size>int(self.settings.get('total_bytes',512*1024*1024)) or scope_total+size>int(self.settings.get('scope_bytes',128*1024*1024)):raise ValueError('图片任务素材缓存已达容量上限，本次未启动')
        directory=self.tasks/key;directory.mkdir(exist_ok=True)
        paths=[]
        for i,row in enumerate(rows):
            target=directory/(str(i)+'.'+row['suffix']);shutil.copyfile(row['path'],target);paths.append(str(target))
        if self.epoch(snapshot['scope'])!=snapshot['epoch']:raise ValueError('会话已清空，未启动图片任务')
        with self.db() as db:db.execute('INSERT OR IGNORE INTO task_inputs VALUES(?,?,?,?,?,?)',(key,snapshot['scope'],snapshot['epoch'],self.clock(),json.dumps(ids),json.dumps(paths)))
        return paths

    def prune(self,force=False):
        now=self.clock()
        if not force and now-self.last_prune<60:return
        self.last_prune=now
        with self.db() as db:
            db.execute("UPDATE assets SET state='expired' WHERE expires<=?",(now,))
            # Bound media by group/persona scope and global capacity.
            for scope in [r[0] for r in db.execute("SELECT DISTINCT scope FROM assets WHERE state='ready'")]:
                rows=db.execute("SELECT id,size FROM assets WHERE scope=? AND state='ready' ORDER BY seq DESC",(scope,)).fetchall();total=0
                for r in rows:
                    total+=r['size']
                    if total>int(self.settings.get('scope_bytes',128*1024*1024)):db.execute("UPDATE assets SET state='evicted' WHERE id=?",(r['id'],))
            rows=db.execute("SELECT id,size FROM assets WHERE state='ready' ORDER BY seq DESC").fetchall();total=0
            for r in rows:
                total+=r['size']
                if total>int(self.settings.get('total_bytes',512*1024*1024)):db.execute("UPDATE assets SET state='evicted' WHERE id=?",(r['id'],))
            for scope in [r[0] for r in db.execute('SELECT scope FROM scopes')]:
                cutoff=now-float(self.settings.get('message_ttl_seconds',604800))
                db.execute('DELETE FROM events WHERE scope=? AND (received<? OR seq NOT IN (SELECT seq FROM events WHERE scope=? ORDER BY seq DESC LIMIT ?))',(scope,cutoff,scope,int(self.settings.get('messages_per_scope',5000))))
            db.execute('DELETE FROM assets WHERE seq NOT IN (SELECT seq FROM events)')
            live={r[0]+'.'+r[1] for r in db.execute("SELECT digest,suffix FROM assets WHERE state='ready'")}
            tasks=db.execute('SELECT id FROM task_inputs WHERE created<?',(now-86400,)).fetchall()
            for task in tasks:
                directory=self.tasks/task['id']
                if directory.is_dir() and directory.parent==self.tasks and not directory.is_symlink():shutil.rmtree(directory)
                db.execute('DELETE FROM task_inputs WHERE id=?',(task['id'],))
            for p in self.blobs.iterdir():
                if re.fullmatch(r'[0-9a-f]{64}\.[a-z0-9]{1,10}',p.name) and p.name not in live and not p.is_symlink():p.unlink(missing_ok=True)

    def stats(self):
        with self.db() as db:
            return {'messages':db.execute('SELECT count(*) FROM events').fetchone()[0],
                    'attachments':db.execute('SELECT count(*) FROM assets').fetchone()[0],
                    'states':dict(db.execute('SELECT state,count(*) FROM assets GROUP BY state').fetchall()),
                    'ready_bytes':db.execute("SELECT coalesce(sum(size),0) FROM assets WHERE state='ready'").fetchone()[0]}
