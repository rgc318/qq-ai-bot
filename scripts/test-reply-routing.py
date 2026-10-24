"""Deterministic policy regressions, without network or QQ messages."""
import asyncio
import importlib.util
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace,ModuleType
import time

path=Path(__file__).resolve().parents[1]/"extensions"
sys.path.insert(0,str(path))
# Exercise the real routing module without loading AstrBot's plugin entrypoint.
package=ModuleType('astrbot_plugin_qq_persona_models')
package.__path__=[str(path/'astrbot_plugin_qq_persona_models')]
sys.modules[package.__name__]=package
module=__import__('astrbot_plugin_qq_persona_models.reply_routing',fromlist=['ReplyRouter'])

class ReplyRoutingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now=1000.0
        self.calls=[]
        self.verdict={"route":"followup","confidence":0.96,"anchor_id":"ai-1"}
        async def judge(payload):
            self.calls.append(payload)
            return self.verdict
        self.router=module.ReplyRouter({"enabled":True,"allowed_groups":["group"],"aliases":["小鱼"],"followup_window_seconds":180,"user_min_interval_seconds":2,"judge_timeout_seconds":0.02},judge,clock=lambda:self.now)

    def anchor(self):
        self.router.note_ai("group","活动文案已完成",request="写活动文案",sender="A")

    async def test_cross_member_followup_does_not_wait_for_quiet(self):
        self.anchor()
        ctx=self.router.context("group")
        for i in range(50):
            ctx.messages.append({"role":"user","sender":"C","text":"旁边有人继续说话"})
        result=await self.router.decide("group","B","给我也整一份",message_id="one")
        self.assertEqual(result["route"],"fast")
        self.assertEqual(self.calls[-1]["last_ai_activity"]["request"],"写活动文案")
        self.assertEqual(len(self.calls[-1]["recent_messages"]),24)

    async def test_explicit_wake_does_not_call_judge(self):
        result=await self.router.decide("group","A","介绍一下",explicit=True)
        self.assertEqual(result["route"],"direct")
        self.assertFalse(self.calls)

    async def test_standalone_name_and_honorific_wake_without_judge_or_anchor(self):
        self.router.settings['aliases']=['小鱼','ChatGPT','GPT','龙娘']
        for text in ['ChatGPT大人','ChatGPT','GPT老师！','龙娘姐姐？','小鱼在吗']:
            self.now+=3
            result=await self.router.decide('group','A',text)
            self.assertEqual(result['route'],'fast',text)
            self.assertEqual(result['reason'],'standalone_bot_name_call')
            self.assertIsNone(result['reference'])
        self.assertFalse(self.calls)

    async def test_name_discussion_and_quotation_are_not_direct_wake(self):
        self.router.settings['aliases']=['ChatGPT']
        self.verdict={'route':'ambient','confidence':0.99}
        for text in ['我刚才问了ChatGPT','他说“ChatGPT大人”','ChatGPT大人这个称呼真搞笑','别叫ChatGPT大人了']:
            result=await self.router.decide('group','A',text)
            self.assertEqual(result['route'],'ambient',text)

    async def test_name_call_respects_other_target_and_burst_limit(self):
        result=await self.router.decide('group','A','小鱼姐姐',targets_other=True)
        self.assertEqual(result['route'],'ambient')
        self.assertEqual((await self.router.decide('group','A','小鱼姐姐'))['route'],'fast')
        self.assertEqual((await self.router.decide('group','A','小鱼姐姐'))['reason'],'per_user_burst_limit')
        self.assertFalse(self.calls)

    async def test_name_call_switch_can_restore_semantic_only_behavior(self):
        self.router.settings['direct_name_call']=False
        self.verdict={'route':'ambient','confidence':0.99}
        result=await self.router.decide('group','A','小鱼姐姐')
        self.assertEqual(result['route'],'ambient')
        self.assertEqual(len(self.calls),1)

    async def test_bot_recipient_without_task_still_gets_response(self):
        self.router.settings['aliases']=['ChatGPT']
        await self.router.decide('group','A','ChatGPT大人')
        self.now+=3
        self.verdict={'route':'ambient','recipient':'bot','silence_requested':False,'confidence':0.98,'reason':'是在叫AI但没有具体任务'}
        result=await self.router.decide('group','A','wake up')
        self.assertEqual(result['route'],'fast')
        self.assertEqual(result['reason'],'semantic_addressed')
        self.assertTrue(self.calls[-1]['recent_addressing_evidence'])
        self.assertTrue(self.router.context('group').messages[-1]['directed_to_bot'])

    async def test_partial_cross_member_conversation_is_available_to_judge(self):
        self.router.settings['aliases']=['龙娘']
        await self.router.decide('group','A','龙娘')
        self.now+=3
        self.verdict={'route':'addressed','recipient':'bot','silence_requested':False,'confidence':0.98}
        await self.router.decide('group','A','我们周日活动想找地方',name='甲')
        await self.router.decide('group','B','我只能下午去',name='乙')
        result=await self.router.decide('group','C','也算我一个，帮我们一起安排',name='丙')
        self.assertEqual(result['route'],'fast')
        rows=self.calls[-1]['recent_messages']
        self.assertEqual({row['sender'] for row in rows if row['role']=='user'},{'A','B','C'})
        self.assertIn('我们周日活动想找地方',[row['text'] for row in rows])

    async def test_explicit_silence_and_human_recipient_override_route(self):
        for extra in ({'recipient':'human','silence_requested':False},{'recipient':'bot','silence_requested':True}):
            self.verdict={'route':'addressed','confidence':0.99,**extra}
            self.assertEqual((await self.router.decide('group','A','小鱼先别回答'))['route'],'ambient')

    async def test_answer_to_ai_question_is_not_discarded_as_ack(self):
        self.router.note_ai('group','按周日下午安排可以吗？',sender='A')
        self.verdict={'route':'addressed','recipient':'bot','silence_requested':False,'confidence':0.99}
        result=await self.router.decide('group','A','好的')
        self.assertEqual(result['route'],'fast')
        self.assertTrue(self.calls)

    async def test_another_member_can_answer_ai_group_question(self):
        self.router.note_ai('group','大家周日下午去图书馆可以吗？',sender='A')
        self.verdict={'route':'addressed','recipient':'bot','silence_requested':False,'confidence':0.99}
        result=await self.router.decide('group','B','好的')
        self.assertEqual(result['route'],'fast')
        self.assertTrue(self.calls)

    async def test_snapshot_restores_early_conversation_without_ai_answer(self):
        await self.router.decide('group','A','小鱼姐姐')
        saved=self.router.snapshot(wall_time=10000)
        restored=module.ReplyRouter(self.router.settings,self.router.judge,clock=lambda:5000)
        restored.restore(saved,wall_time=10003)
        self.assertIsNone(restored.context('group').last_ai)
        self.assertEqual(restored.context('group').messages[-1]['text'],'小鱼姐姐')
        self.assertEqual(5000-restored.context('group').messages[-1]['time'],3)

    async def test_standalone_meme_request_can_be_judged_without_anchor(self):
        self.verdict={'route':'addressed','confidence':0.96}
        result=await self.router.decide('group','A','发个开心的表情包')
        self.assertEqual(result['route'],'fast')
        self.assertIsNone(self.calls[-1]['last_ai_activity'])

    async def test_meme_discussion_is_not_automatic_permission(self):
        self.verdict={'route':'ambient','confidence':0.97}
        result=await self.router.decide('group','A','他说让我发个开心的表情包，真搞笑')
        self.assertEqual(result['route'],'ambient')

    async def test_unanswered_request_is_per_sender_expires_and_is_consumed(self):
        await self.router.decide('group','A','给我也整一份')
        self.assertEqual(self.router.unanswered_request('group','B'),'')
        self.assertEqual(self.router.unanswered_request('group','A'),'给我也整一份')
        self.assertEqual(self.router.unanswered_request('group','A'),'')
        await self.router.decide('group','A','再短一点')
        self.now+=301
        self.assertEqual(self.router.unanswered_request('group','A'),'')

    async def test_answered_or_other_target_request_is_not_replayed(self):
        await self.router.decide('group','A','再短一点')
        self.router.note_ai('group','好的',sender='A')
        self.assertEqual(self.router.unanswered_request('group','A'),'')
        await self.router.decide('group','A','给我也整一份',targets_other=True)
        self.assertEqual(self.router.unanswered_request('group','A'),'')

    async def test_snapshot_recovers_age_and_unanswered_request_after_reload(self):
        self.anchor()
        self.router.context('group').scope='group:qq:group|大肥鱼'
        await self.router.decide('group','B','给我也整一份',targets_other=True)
        await self.router.decide('group','C','没上下文的话')
        saved=self.router.snapshot(wall_time=10000)
        other=module.ReplyRouter(self.router.settings,self.router.judge,clock=lambda:5000)
        other.restore(saved,wall_time=10020)
        ctx=other.context('group')
        self.assertEqual(5000-ctx.last_ai['time'],20)
        self.assertEqual(ctx.scope,'group:qq:group|大肥鱼')
        self.assertEqual(other.unanswered_request('group','C'),'没上下文的话')
        self.assertEqual(other.unanswered_request('group','B'),'')

    async def test_snapshot_cannot_revive_expired_or_unallowed_group(self):
        self.anchor()
        saved=self.router.snapshot(wall_time=10000)
        other=module.ReplyRouter(self.router.settings,self.router.judge,clock=lambda:5000)
        other.restore(saved,wall_time=10181)
        self.assertFalse(other.groups)
        saved['groups']['other']=saved['groups'].pop('group')
        other.restore(saved,wall_time=10001)
        self.assertFalse(other.groups)

    async def test_native_history_recovery_respects_persona_and_age(self):
        recover=__import__('astrbot_plugin_qq_persona_models.context_recovery',fromlist=['hydrate_history'])
        conv=SimpleNamespace(persona_id='大肥鱼',updated_at=time.time()-50,history='[{"role":"user","content":"发个表情包"},{"role":"assistant","content":[{"type":"text","text":"已经发出开心表情"}]}]')
        async def current(*a):return 'cid'
        async def conversation(*a):return conv
        context=SimpleNamespace(conversation_manager=SimpleNamespace(get_curr_conversation_id=current,get_conversation=conversation),get_registered_star=lambda name:None)
        event=SimpleNamespace(get_group_id=lambda:'group',unified_msg_origin='qq:GroupMessage:group',get_extra=lambda k:None)
        self.assertFalse(await recover.hydrate_history(context,self.router,event,'龙娘'))
        self.router.groups.clear()
        self.assertTrue(await recover.hydrate_history(context,self.router,event,'大肥鱼'))
        self.assertIn('开心表情',self.router.context('group').last_ai['reply'])
        self.assertGreaterEqual(self.now-self.router.context('group').last_ai['time'],49)
        self.router.groups.clear()
        conv.updated_at=time.time()-181
        self.assertFalse(await recover.hydrate_history(context,self.router,event,'大肥鱼'))

    async def test_no_anchor_does_not_guess(self):
        result=await self.router.decide("group","B","给我也整一份")
        self.assertEqual(result["route"],"ambient")
        self.assertFalse(self.calls)

    async def test_expired_anchor_not_renewed_by_chatter(self):
        self.anchor()
        self.now+=181
        result=await self.router.decide("group","B","给我也整一份")
        self.assertEqual(result["reason"],"no_recent_ai_task_or_address")

    async def test_pending_task_has_shorter_expiry(self):
        self.router.note_ai("group","",request="写文案",pending=True)
        self.now+=121
        result=await self.router.decide("group","B","给我也整一份")
        self.assertEqual(result["route"],"ambient")

    async def test_extended_window_accepts_clear_late_followup(self):
        self.router.settings['followup_window_seconds']=1800
        self.anchor()
        self.now+=900
        result=await self.router.decide('group','B','刚才的活动文案也给我写一份，改成周日')
        self.assertEqual(result['route'],'fast')
        self.assertEqual(self.calls[-1]['last_ai_activity']['age_seconds'],900)

    async def test_extended_window_still_expires(self):
        self.router.settings['followup_window_seconds']=1800
        self.anchor()
        self.now+=1801
        result=await self.router.decide('group','B','给我也整一份')
        self.assertEqual(result['route'],'ambient')
        self.assertFalse(self.calls)

    async def test_pending_task_does_not_inherit_extended_sent_window(self):
        self.router.settings['followup_window_seconds']=1800
        self.router.note_ai('group','',request='写文案',pending=True)
        self.now+=121
        self.assertEqual((await self.router.decide('group','B','给我也整一份'))['route'],'ambient')

    async def test_other_person_mention_is_not_hijacked(self):
        self.anchor()
        result=await self.router.decide("group","B","给我也整一份",targets_other=True)
        self.assertEqual(result["route"],"ambient")
        self.assertFalse(self.calls)

    async def test_group_scope_is_retained(self):
        result=await self.router.decide("other","B","小鱼，帮我看看")
        self.assertEqual(result["route"],"ignored")
        self.assertFalse(self.router.groups)

    async def test_same_message_is_not_replied_twice(self):
        self.anchor()
        first=await self.router.decide("group","B","给我也整一份",message_id="same")
        second=await self.router.decide("group","B","给我也整一份",message_id="same")
        self.assertEqual(first["route"],"fast")
        self.assertEqual(second["route"],"duplicate")
        self.assertEqual(len(self.calls),1)

    async def test_per_user_burst_limit_does_not_block_other_members(self):
        self.anchor()
        self.assertEqual((await self.router.decide("group","B","给我也写一份"))["route"],"fast")
        self.assertEqual((await self.router.decide("group","B","给我也写一份"))["route"],"ambient")
        self.assertEqual((await self.router.decide("group","C","给我也写一份"))["route"],"fast")

    async def test_invalid_confidence_and_anchor_are_rejected(self):
        self.anchor()
        for verdict in ({"route":"followup","confidence":0.4,"anchor_id":"ai-1"},{"route":"followup","confidence":0.99,"anchor_id":"invented"},{"route":"followup","confidence":2,"anchor_id":"ai-1"}):
            self.verdict=verdict
            self.assertEqual((await self.router.decide("group","B","再短点"))["route"],"ambient")

    async def test_nickname_inside_sentence_can_be_addressed(self):
        self.verdict={"route":"addressed","confidence":0.98}
        result=await self.router.decide("group","B","能帮我看看吗，小鱼")
        self.assertEqual(result["route"],"fast")

    async def test_acknowledgments_are_not_fast_requests(self):
        self.anchor()
        for text in ("谢谢！","哈哈哈","👍","确实","收到"):
            self.assertEqual((await self.router.decide("group","B",text))["route"],"ambient")
        self.assertFalse(self.calls)

    async def test_judge_failure_does_not_wake_bot(self):
        self.anchor()
        async def broken(payload):
            raise ValueError("invalid JSON")
        self.router.judge=broken
        result=await self.router.decide("group","B","再短点")
        self.assertEqual(result["route"],"ambient")

    async def test_judge_timeout_is_bounded(self):
        self.anchor()
        async def slow(payload):
            await asyncio.sleep(1)
        self.router.judge=slow
        result=await self.router.decide("group","B","再短点")
        self.assertEqual(result["route"],"ambient")
        self.assertEqual(result["reason"],"judge_unavailable")
        self.assertTrue(result['judged'])

    async def test_judge_failure_backoff_does_not_block_explicit_mention(self):
        self.anchor()
        async def broken(payload):
            self.calls.append(payload)
            raise RuntimeError('offline')
        self.router.judge=broken
        first=await self.router.decide('group','A','再短点')
        second=await self.router.decide('group','B','给我也整一份')
        direct=await self.router.decide('group','B','介绍一下',explicit=True)
        self.assertEqual(first['reason'],'judge_unavailable')
        self.assertEqual(second['reason'],'judge_backoff')
        self.assertEqual(direct['route'],'direct')
        self.assertEqual(len(self.calls),1)
        self.now+=16
        await self.router.decide('group','B','给我也整一份')
        self.assertEqual(len(self.calls),2)

    async def test_classifier_context_has_separate_budget(self):
        self.anchor()
        self.router.settings.update(judge_recent_messages=12,judge_recent_chars=2400)
        for i in range(24):
            self.router.context('group').messages.append({'role':'user','text':'长消息'*300})
        await self.router.decide('group','B','给我也整一份')
        rows=self.calls[-1]['recent_messages']
        self.assertLessEqual(len(rows),12)
        self.assertLessEqual(sum(len(row['text']) for row in rows),2400)
        self.assertEqual(rows[-1]['text'],'给我也整一份')

    async def test_background_chatter_cannot_occupy_request_lanes(self):
        self.anchor()
        self.router.settings["judge_timeout_seconds"]=1
        release=asyncio.Event()
        async def judge(payload):
            if "份" in payload["latest_message"]["text"]:
                return {"route":"followup","confidence":0.98,"anchor_id":"ai-1"}
            await release.wait()
            return {"route":"ambient","confidence":0.99}
        self.router.judge=judge
        pending=[asyncio.create_task(self.router.decide("group",sender,"今晚真热闹")) for sender in ("C","D")]
        try:
            await asyncio.sleep(0.01)
            answer=await self.router.decide("group","B","给我也整一份")
            self.assertEqual(answer["route"],"fast")
        finally:
            release.set()
            await asyncio.gather(*pending)


class DialogueContinuityTests(unittest.IsolatedAsyncioTestCase):
    setUp=ReplyRoutingTests.setUp

    async def start_exchange(self):
        self.verdict={'route':'ambient','recipient':'human','silence_requested':False,'confidence':0.99}
        await self.router.decide('group','A','重新生成一下',explicit=True,message_id='original')
        self.router.note_ai('group','',request='重新生成一下',sender='A',pending=True)

    async def test_identity_after_three_minutes_without_other_speakers(self):
        await self.start_exchange()
        self.now+=183
        result=await self.router.decide('group','A','你是谁',message_id='identity')
        self.assertEqual(result['reason'],'same_speaker_dialogue')
        self.assertEqual(result['judge_seconds'],0)
        self.assertIsNone(result['reference'])
        self.assertFalse(self.calls)

    async def test_continuous_followups_keep_receiver_without_tasks(self):
        await self.start_exchange()
        for text in ('那你现在用的是哪个模型？','你还在吗','醒醒'):
            self.now+=30
            result=await self.router.decide('group','A',text)
            self.assertEqual(result['reason'],'same_speaker_dialogue')
        self.assertFalse(self.calls)

    async def test_pending_context_retained_for_same_speaker_only(self):
        await self.start_exchange()
        self.router.settings['followup_window_seconds']=1800
        self.now+=183
        self.verdict={'route':'addressed','recipient':'bot','silence_requested':False,'confidence':0.99}
        result=await self.router.decide('group','A','现在使用哪个模型呢？')
        self.assertEqual(result['route'],'fast')
        payload=self.calls[-1]
        self.assertTrue(payload['dialogue_continuity']['established'])
        self.assertEqual(payload['last_ai_activity']['status'],'pending')
        self.assertEqual(payload['last_ai_activity']['age_seconds'],183)
        self.assertEqual(result['judge_recent_messages'],2)

    async def test_other_member_interruption_still_uses_classifier(self):
        await self.start_exchange()
        self.router.context('group').messages.append({'role':'user','sender':'B','text':'有人找我吗','time':self.now+1})
        self.now+=30
        result=await self.router.decide('group','A','你是谁')
        self.assertEqual(result['route'],'ambient')
        self.assertFalse(self.calls[-1]['dialogue_continuity']['established'])
        self.assertEqual(result['intervening_speakers'],1)

    async def test_known_other_target_wins_over_continuity(self):
        await self.start_exchange()
        self.now+=30
        result=await self.router.decide('group','A','你是谁',targets_other=True)
        self.assertEqual(result['reason'],'explicitly_targets_another_person')
        self.assertFalse(self.calls)

    async def test_plain_named_human_and_following_you_are_not_hijacked(self):
        await self.start_exchange()
        self.now+=30
        first=await self.router.decide('group','A','小张，你是哪个班的？')
        self.now+=3
        second=await self.router.decide('group','A','你是谁')
        self.assertEqual((first['route'],second['route']),('ambient','ambient'))
        self.assertEqual(self.calls[-1]['dialogue_continuity']['unclassified_turns'],1)
        self.assertEqual(len(self.calls),2)

    async def test_silence_request_is_not_locally_woken(self):
        await self.start_exchange()
        self.verdict={'route':'ambient','recipient':'bot','silence_requested':True,'confidence':0.99}
        self.now+=30
        result=await self.router.decide('group','A','你先别回复我了')
        self.assertEqual(result['route'],'ambient')
        self.assertEqual(len(self.calls),1)

    async def test_quote_and_group_plural_need_semantic_judgment(self):
        for text in ('“你是谁”是他问小张的原话','你们晚上吃什么'):
            self.setUp()
            await self.start_exchange()
            self.now+=30
            result=await self.router.decide('group','A',text)
            self.assertEqual(result['route'],'ambient')
            self.assertEqual(len(self.calls),1)

    async def test_continuity_expires_and_can_be_disabled(self):
        await self.start_exchange()
        self.now+=601
        self.assertEqual((await self.router.decide('group','A','你是谁'))['route'],'ambient')
        self.setUp()
        await self.start_exchange()
        self.router.settings['dialogue_continuity_enabled']=False
        self.now+=30
        self.assertEqual((await self.router.decide('group','A','你是谁'))['route'],'ambient')
        self.assertEqual(len(self.calls),1)

    async def test_new_speaker_does_not_inherit_exclusive_receiver(self):
        await self.start_exchange()
        self.now+=30
        result=await self.router.decide('group','B','你是谁')
        self.assertEqual(result['route'],'ambient')
        self.assertFalse(self.calls[-1]['dialogue_continuity']['established'])

    async def test_progress_preserves_request_and_is_available_to_judge(self):
        await self.start_exchange()
        anchor=dict(self.router.context('group').last_ai)
        self.now+=500
        self.router.note_progress('group','我来把柴犬拟成人形。',sender='A',kind='image_notice')
        self.router.note_progress('group','[图片已下发：执行状态摘要]',sender='A',kind='image_tool_status')
        self.assertEqual(self.router.context('group').last_ai,anchor)
        self.now+=200
        self.verdict={'route':'addressed','recipient':'bot','silence_requested':False,'confidence':0.99}
        await self.router.decide('group','A','现在使用哪个模型呢？')
        payload=self.calls[-1]
        self.assertTrue(payload['dialogue_continuity']['established'])
        self.assertEqual(payload['dialogue_continuity']['age_seconds'],200)
        self.assertEqual([r['kind'] for r in payload['recent_messages'] if r.get('kind')],['image_notice','image_tool_status'])

    async def test_progress_does_not_erase_intervening_people(self):
        await self.start_exchange()
        self.router.context('group').messages.append({'role':'user','sender':'B','text':'我在和你说话','time':self.now+1})
        self.now+=10
        self.router.note_progress('group','图片已发送',sender='A',kind='image_tool_status')
        result=await self.router.decide('group','A','你是谁')
        self.assertEqual(result['route'],'ambient')

    async def test_restored_dialogue_does_not_resurrect_pending_task(self):
        await self.start_exchange()
        self.router.settings['followup_window_seconds']=1800
        saved=self.router.snapshot(wall_time=10000)
        restored=module.ReplyRouter(self.router.settings,self.router.judge,clock=lambda:5000)
        restored.restore(saved,wall_time=10183)
        self.assertIsNone(restored.context('group').last_ai)
        result=await restored.decide('group','A','你是谁')
        self.assertEqual(result['reason'],'same_speaker_dialogue')
        self.assertFalse(self.calls)

if __name__=="__main__":
    unittest.main(verbosity=2)
