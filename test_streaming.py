"""Offline tests for streaming, pause boundaries, latest-only previews and drain."""
import asyncio
import base64
import json
import threading
import unittest
from unittest.mock import patch, Mock

import meeting
from test_meeting import FakeASR, FakeClient, VOICE, QUIET


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_memory_write_failure_does_not_drop_translation_or_audio(self):
        client=FakeClient([VOICE]*24);upstream=FakeASR()
        glossary=Mock();glossary.guidance.return_value=[]
        glossary.observe.side_effect=OSError('database unavailable')
        with patch.object(meeting,'OPENAI_API_KEY','test'),patch.object(meeting,'connect',return_value=upstream),patch.object(meeting,'translate_text',return_value='测试译文'):
            await asyncio.wait_for(meeting.MeetingSession(client,'中文',glossary=glossary).run(),3)
        self.assertTrue(any(e['type']=='memory.warning' for e in client.events))
        self.assertTrue(any(e['type']=='translation.final' for e in client.events))
        self.assertEqual(client.events[-1]['type'],'closed')

    async def test_pcm_is_sent_before_commit_without_duplicates_or_dropped_tail(self):
        upstream = FakeASR()
        class Client(FakeClient):
            async def receive(self):
                if len(upstream.sent)==1:
                    self_outer.assertEqual(upstream.sent[0]['type'],'input_audio_buffer.append')
                    self_outer.assertEqual(upstream.count,0)
                return await super().receive()
        self_outer = self
        frames = [VOICE]*24 + [VOICE[:480]]
        session = meeting.MeetingSession(Client(frames),'中文')
        await session.read_audio(upstream)
        sent = b''.join(base64.b64decode(e['audio']) for e in upstream.sent if e['type'].endswith('.append'))
        self.assertEqual(sent,b''.join(frames))
        self.assertEqual(upstream.count,1)
        self.assertEqual(session.received_bytes,session.sent_bytes)

    def test_sentence_hint_short_pause_and_unfinished_longer_pause(self):
        for text,quiet_count in [('測位誤差は二メートルです。',4),('We use Wi-Fi,',10),('We asked Dr.',10)]:
            window=meeting.AudioWindow(live=True)
            for _ in range(30): self.assertIsNone(window.push(VOICE,text))
            for _ in range(quiet_count-1): self.assertIsNone(window.push(QUIET,text))
            self.assertEqual(window.push(QUIET,text),VOICE*30+QUIET*quiet_count)

    def test_long_continuous_turn_is_bounded_but_never_discarded(self):
        window=meeting.AudioWindow(live=True)
        result=[]
        for frame in [VOICE]*511:
            ready=window.push(frame,'unfinished')
            if ready: result.append(ready)
        result.append(window.flush())
        self.assertEqual([len(p)/48000 for p in result],[25,25,1.1])
        self.assertEqual(b''.join(result),VOICE*511)

    def test_live_config_and_recovery_config_are_distinct(self):
        live=meeting.asr_configuration()['session']['audio']['input']
        recovery=meeting.asr_configuration(live=False)['session']['audio']['input']
        self.assertEqual(live['transcription']['model'],'gpt-live-transcribe')
        self.assertEqual(live['transcription']['languages'],['ja','en'])
        self.assertIsNone(live['turn_detection'])
        self.assertEqual(recovery['transcription']['model'],'gpt-transcribe')
        self.assertNotIn('delay',recovery['transcription'])

    async def test_delta_before_commit_is_displayed_then_reconciled(self):
        upstream=FakeASR(); client=FakeClient([])
        session=meeting.MeetingSession(client,'中文')
        session.received_bytes=4800
        await session.submit(upstream,VOICE)
        upstream.events=asyncio.Queue()
        for event in [
            {'type':'conversation.item.input_audio_transcription.delta','item_id':'a','delta':'We use'},
            {'type':'input_audio_buffer.committed','item_id':'a'},
            {'type':'conversation.item.input_audio_transcription.completed','item_id':'a','transcript':'We use Wi-Fi.'},
        ]: await upstream.events.put(event)
        task=asyncio.create_task(session.read_asr(upstream))
        try:
            await asyncio.wait_for(session.drained.wait(),1)
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
        self.assertEqual(client.events[0]['type'],'source.delta')
        final=next(e for e in client.events if e['type']=='source.final')
        self.assertEqual(final['sequence'],0)
        self.assertEqual(final['text'],'We use Wi-Fi.')
        self.assertEqual(session.partial_sources,{})

    async def test_preview_coalesces_changes_and_is_not_repeated_without_new_text(self):
        client=FakeClient([]);session=meeting.MeetingSession(client,'中文')
        session.partial_sources['a']='We';session.partial_revisions['a']=1
        with patch.object(meeting,'translate_text',return_value='我们') as translate:
            task=asyncio.create_task(session.translate_preview())
            try:
                await asyncio.sleep(.15)
                for revision in range(2,10):
                    session.partial_sources['a']=f'We use {revision}'
                    session.partial_revisions['a']=revision
                await asyncio.sleep(1.05)
                self.assertEqual(translate.call_count,2)
                self.assertEqual(translate.call_args.args[0],'We use 9')
                self.assertEqual([e['revision'] for e in client.events],[1,9])
                await asyncio.sleep(1)
                self.assertEqual(translate.call_count,2)
            finally:
                task.cancel();await asyncio.gather(task,return_exceptions=True)

    async def test_late_preview_cannot_overwrite_final(self):
        client=FakeClient([]);session=meeting.MeetingSession(client,'中文')
        session.partial_sources['a']='We';session.partial_revisions['a']=1
        started=threading.Event();release=threading.Event()
        def translate(*args):
            started.set();release.wait(timeout=2);return '旧的预览'
        with patch.object(meeting,'translate_text',side_effect=translate):
            task=asyncio.create_task(session.translate_preview())
            try:
                await asyncio.to_thread(started.wait,1)
                session.completed_ids.add('a');session.partial_sources.clear()
                release.set();await asyncio.sleep(.1)
                self.assertEqual(client.events,[])
            finally:
                release.set();task.cancel();await asyncio.gather(task,return_exceptions=True)
