"""Bounded evidence for an established conversation; no model calls or I/O."""
import re


_SECOND_PERSON = re.compile(r'^(?:(?:那|那么|所以|可是|但是|不过|对了|话说)[，,\s]*)?(?:你(?!们)|您)[^\n]{0,158}$')
_VOCATIVE = re.compile(r'^(?:在吗|还在吗|在不在|醒醒|还好吗|还没好吗|怎么不理我)[，。！？!?~～\s]*$')
_SILENCE = re.compile(r'(?:别|不要|不用|不必|无需|停止).{0,8}(?:回(?:复|答)?|说话|接话|理我)|闭嘴|保持安静')


def continuity_evidence(history, sender, now, settings):
    """Require a known AI-directed turn and inspect every intervening user row.

    Assistant progress can keep that same exchange fresh, but cannot erase a
    human handoff or another speaker. Untimed, recovered history is not enough
    to authorize a local reply. The caller excludes the current incoming row.
    """
    empty = {'established': False, 'other_speaker_count': 0,
             'human_handoff': False, 'unclassified_turns': 0}
    if not settings.get('dialogue_continuity_enabled', True):
        return empty
    window = max(0, min(1800, float(settings.get('dialogue_continuity_window_seconds', 600))))
    if not window:
        return empty
    seed = next((i for i in range(len(history)-1, -1, -1)
                 if history[i].get('role') == 'user' and history[i].get('sender') == sender
                 and history[i].get('directed_to_bot') and not history[i].get('targets_other')
                 and isinstance(history[i].get('time'), (int, float))), None)
    if seed is None:
        return empty
    origin = history[seed]
    tail = history[seed+1:]
    users = [row for row in tail if row.get('role') == 'user']
    others = {row.get('sender') or 'unknown' for row in users if row.get('sender') != sender}
    handoff = any(row.get('targets_other') for row in users)
    unclassified = sum(row.get('sender') == sender and not row.get('directed_to_bot') for row in users)
    activity = [origin['time']] + [row['time'] for row in tail
        if row.get('role') == 'assistant' and row.get('requested_by') == sender
        and isinstance(row.get('time'), (int, float))]
    age = now - max(activity)
    return {'established': 0 <= age <= window and not others and not handoff and not unclassified,
            'origin_age_seconds': round(max(0, now-origin['time']), 1),
            'age_seconds': round(max(0, age), 1), 'window_seconds': window,
            'other_speaker_count': len(others), 'human_handoff': handoff,
            'unclassified_turns': unclassified}


def is_unambiguous_continuation(text, evidence):
    """Only receiver-clear second-person speech bypasses the classifier.

    Named humans, quotations, group-wide 'you all', silence requests and any
    intervening unclassified user turn still need ordinary semantic judgment.
    """
    return bool(evidence.get('established') and not evidence.get('unclassified_turns')
                and not _SILENCE.search(text)
                and (_SECOND_PERSON.fullmatch(text) or _VOCATIVE.fullmatch(text)))
