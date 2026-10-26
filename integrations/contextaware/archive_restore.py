"""Cold-start hydration from the EXISTING scoped attachment archive.

This does not select references or create another storage format. ContextAware
remains the only active image catalog. Old archive IDs are translated once into
its native IDs; source order, generated origin and available lineage survive.
There is no migration of real user data in this module's isolated tests.
"""
from dataclasses import replace
from pathlib import Path
import asyncio
import json
import hashlib
from types import SimpleNamespace


class ArchiveRestorer:
    """Bounded cold restore using upstream's existing index, not an index fork.

    Isolates the extra private dependency on ImageIndex resources/entry metadata.
    Changing this seam requires rerunning the pinned native tests before adoption.
    Runtime capture and successful-result persistence remain deployment gates.
    """
    def __init__(self, backend, store):
        self.backend = backend
        self.store = store
        self.maps = {}
        self.locks = {}

    async def hydrate(self, event, boundary=None, include_ids=()):
        view = self.backend.scoped(event)
        lock = self.locks.setdefault(view.scope, asyncio.Lock())
        async with lock:
            return await self._hydrate(view,boundary,include_ids)

    async def _hydrate(self, view,boundary,include_ids):
        plugin = self.backend.plugin
        index = plugin._image_index
        snapshot = await asyncio.to_thread(self.store.snapshot, view.scope, index.per_session,boundary)
        for asset_id in include_ids:
            if asset_id not in snapshot['ids']:
                row=await asyncio.to_thread(self.store.source,snapshot['scope'],snapshot['epoch'],asset_id)
                if row['seq']>snapshot['seq']:raise ValueError('附件晚于本轮消息快照')
                snapshot['ids'].append(asset_id);snapshot['catalog'].append(self.store.public(row))
        key = (view.scope, snapshot['epoch'])
        state = self.maps.get(view.scope)
        if state and state['key'] != key:
            # A reset must not resurrect the previous generation's pixels.
            index.clear(view.unified_msg_origin)
            await plugin._sessions.remove_session_async(view.unified_msg_origin)
            state = None
        if state is None:
            state = {'key': key, 'ids': {}}
            self.maps[view.scope] = state
        ids = state['ids']
        index.epoch(view.unified_msg_origin)
        imported = 0
        # No selection is inferred from message content; retain original order.
        wanted = [a['id'] for a in snapshot['catalog'] if a['type'] == 'image' and a['state'] == 'ready'
                  and not index.get(view.unified_msg_origin,ids.get(a['id'],''))]
        rows = await asyncio.to_thread(self.store.resolve, snapshot, wanted, 'image', 80) if wanted else []
        for row in sorted(rows, key=lambda row: (row['seq'], row['ordinal'])):
            archive_id = row['id']
            if index.get(view.unified_msg_origin, ids.get(archive_id, '')):
                continue
            data = await asyncio.to_thread(Path(row['path']).read_bytes)
            source = json.loads(row['source'])
            parents = json.loads(row['parents'])
            requester = row['sender']
            generated = bool(source.get('generated'))
            request_order = int(source.get('request_seq', row['seq']))
            if generated:
                def find_requester():
                    with self.store.db() as db:
                        r = db.execute('SELECT sender FROM events WHERE scope=? AND epoch=? AND seq=?',
                                       (view.scope, snapshot['epoch'], request_order)).fetchone()
                        return r['sender'] if r else ''
                requester = source.get('requested_by') or await asyncio.to_thread(find_requester)
            message = SimpleNamespace(msg_id='archive:'+archive_id,
                sender_id=requester, sender_name=row['name'], timestamp=row['created'],
                is_bot=False, has_gif=False, image_count=1, image_urls=['retained-archive'])
            if generated:
                native_id = index.add_generated(message, view.unified_msg_origin, row['seq'], data,
                    task_id=source.get('task_id', 'archived:'+row['message_id']),
                    request_sequence=request_order, conversation_id=source.get('conversation_id', ''),
                    parent_ids=tuple(ids.get(p, 'archived-unavailable:'+p) for p in parents))
            else:
                native_ids = index.add(view.unified_msg_origin, message, row['seq'], allow_gif=True)
                native_id = native_ids[0] if native_ids else None
            if native_id:
                resource = index.get(view.unified_msg_origin, native_id)
                # Upstream IDs are random per in-memory index. The archived
                # identity already includes scope and epoch; use a stable local
                # alias so reload/eviction cannot invalidate retained sources.
                stable_id='ca_'+hashlib.sha256(('qq-archive-v1|'+archive_id).encode()).hexdigest()[:24]
                if stable_id!=native_id:
                    if stable_id in index.resources:raise ValueError('归档图片标识冲突，拒绝替换来源')
                    index.resources[stable_id]=index.resources.pop(native_id)
                    index.sessions[view.unified_msg_origin]=[stable_id if i==native_id else i for i in index.sessions[view.unified_msg_origin]]
                    native_id=stable_id
                resource.source = ''
                resource.data = data
                # Preserve the real original source, not a synthetic platform ID.
                resource.entry = replace(resource.entry, image_id=native_id, message_id=row['message_id'])
                ids[archive_id] = native_id
                imported += 1
                plugin._recall_sequence = max(plugin._recall_sequence, row['seq'])
        index.prune()
        # Discard stale aliases, keeping one authoritative live ID per image.
        state['ids'] = {a: b for a, b in ids.items() if index.get(view.unified_msg_origin, b)}
        return {'imported': imported, 'epoch': snapshot['epoch'], 'mapping': dict(state['ids'])}
