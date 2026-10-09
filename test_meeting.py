"""Deterministic offline protocol tests: no microphone or paid API requests."""
import asyncio
import base64
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import meeting
from topics import Glossaries

VOICE=(1000).to_bytes(2,'little',signed=True)*2400
QUIET=bytes(4800)


class FakeClient:
    def __init__(self, frames): self.frames=iter(frames); self.events=[]
    async def send_json(self,event): self.events.append(event)
    async def receive(self):
        await asyncio.sleep(0)
        frame=next(self.frames,None)
        return {'type':'websocket.receive','bytes':frame} if frame is not None else {'type':'websocket.receive','text':'{"type":"stop"}'}


class FakeASR:
    def __init__(self): self.events=asyncio.Queue();self.sent=[];self.count=0;self.closed=False
    async def __aenter__(self): return self
    async def __aexit__(self,*args): self.closed=True
    async def send(self,message):
        event=json.loads(message);self.sent.append(event)
        if event['type']=='session.update': await self.events.put({'type':'session.updated'})
        if event['type']=='input_audio_buffer.commit':
            self.count+=1; item=f'item-{self.count}'
            await self.events.put({'type':'input_audio_buffer.committed','item_id':item})
            await self.events.put({'type':'conversation.item.input_audio_transcription.completed','item_id':item,'transcript':f'測位誤差 {self.count} メートル'})
    async def recv(self):return json.dumps(await self.events.get())
    def __aiter__(self):return self
    async def __anext__(self):return await self.recv()


class MeetingTests(unittest.IsolatedAsyncioTestCase):
    def test_adaptive_boundaries_preserve_noise_weak_speech_and_tail(self):
        window=meeting.AudioWindow(adaptive=True);chunks=[]
        noise=(100).to_bytes(2,'little',signed=True)*2400
        frames=[noise]*40+[VOICE]*60+[noise]*20+[VOICE]*63+[noise]*31
        for frame in frames:
            chunk=window.push(frame)
            if chunk:chunks.append(chunk)
        tail=window.flush()
        if tail:chunks.append(tail)
        self.assertEqual(b''.join(chunks),b''.join(frames))
        self.assertTrue(all(5<=len(c)/48000<=15 for c in chunks[:-1]))

    def test_audio_mode_validated_and_experimental_segmentation_opt_in(self):
        self.assertFalse(meeting.MeetingSession(FakeClient([]),'中文').window.adaptive)
        self.assertTrue(meeting.MeetingSession(FakeClient([]),'中文',audio_mode='adaptive').window.adaptive)
        with self.assertRaises(ValueError):meeting.MeetingSession(FakeClient([]),'中文',audio_mode='invalid')

    def test_continuous_audio_has_no_dropped_samples(self):
        window=meeting.AudioWindow();data=[]
        for _ in range(237):
            chunk=window.push(VOICE)
            if chunk:data.append(chunk)
        data.append(window.flush())
        self.assertEqual(b''.join(data),VOICE*237)
        self.assertEqual([len(c)/48000 for c in data],[15,8.7])

    def test_silence_keeps_preroll_without_hallucination_commits(self):
        window=meeting.AudioWindow(discard_silence=True)
        for _ in range(1000):self.assertIsNone(window.push(QUIET))
        self.assertLessEqual(window.size,24000)
        window.push(VOICE);self.assertEqual(window.flush(),QUIET*5+VOICE)
        self.assertIsNone(window.flush())

    def test_default_preserves_weak_speech_and_quiet_tail(self):
        window=meeting.AudioWindow();out=[];weak=(20).to_bytes(2,'little',signed=True)*2400
        frames=[QUIET]*22+[VOICE]*12+[weak]*70+[QUIET]*83
        for frame in frames:
            chunk=window.push(frame)
            if chunk:out.append(chunk)
        tail=window.flush()
        if tail:out.append(tail)
        self.assertTrue(b''.join(out)==b''.join(frames),'Every input sample, including weak tail, must survive')

    async def test_stop_byte_count_mismatch_fails_loudly(self):
        client=FakeClient([])
        async def receive():return {'type':'websocket.receive','text':'{"type":"stop","sent_bytes":4800}'}
        client.receive=receive
        with self.assertRaisesRegex(ValueError,'尾帧校验'):
            await meeting.MeetingSession(client,'中文').read_audio(FakeASR())

    async def test_tail_ack_is_emitted_before_close(self):
        client=FakeClient([VOICE]*13);upstream=FakeASR()
        with patch.object(meeting,'OPENAI_API_KEY','test'),patch.object(meeting,'connect',return_value=upstream),patch.object(meeting,'translate_text',return_value='测试'):
            await meeting.MeetingSession(client,'中文').run()
        ack=next(e for e in client.events if e['type']=='audio.ack')
        self.assertEqual(ack['received_bytes'],len(VOICE)*13)
        self.assertEqual(client.events[-1]['type'],'closed')

    async def test_empty_tail_recovers_with_eight_seconds_of_actual_audio(self):
        class EmptyTailASR(FakeASR):
            async def send(self,message):
                await super().send(message)
                if json.loads(message)['type']=='input_audio_buffer.commit' and self.count==2:
                    queued=[]
                    while not self.events.empty():queued.append(self.events.get_nowait())
                    for e in queued:
                        if e.get('item_id')=='item-2' and e['type'].endswith('completed'):e['transcript']=''
                        await self.events.put(e)
        client=FakeClient([VOICE]*273);upstream=EmptyTailASR()
        with patch.object(meeting,'OPENAI_API_KEY','test'),patch.object(meeting,'connect',return_value=upstream),patch.object(meeting,'translate_text',return_value='尾部译文'),patch.object(meeting,'recover_with_context',return_value='前文と最後の発言') as recovery:
            await meeting.MeetingSession(client,'中文').run()
        self.assertEqual(len(recovery.call_args.args[0]),48000*8+4800*23)
        last=[e for e in client.events if e['type']=='source.final'][-1]
        self.assertTrue(last['recovered']);self.assertEqual(last['text'],'前文と最後の発言')
        self.assertEqual(client.events[-1]['type'],'closed')

    def test_quiet_pause_is_preserved(self):
        window=meeting.AudioWindow();out=[]
        frames=[VOICE]*5+[QUIET]*2+[VOICE]*4+[QUIET]*3
        for f in frames:
            chunk=window.push(f)
            if chunk:out.append(chunk)
        self.assertEqual(b''.join(out),b''.join(frames))

    def test_finals_arriving_out_of_order(self):
        items=meeting.OrderedItems()
        items.committed('a');items.committed('b')
        self.assertEqual(items.complete('b',{'id':'b'}),[])
        self.assertEqual(items.complete('a',{'id':'a'}),[{'id':'a'},{'id':'b'}])

    async def test_stop_drains_audio_and_translation(self):
        upstream=FakeASR();client=FakeClient([VOICE]*273)
        def translate(source,*args):return '定位误差：'+source
        with patch.object(meeting,'OPENAI_API_KEY','test'),patch.object(meeting,'connect',return_value=upstream),patch.object(meeting,'translate_text',side_effect=translate):
            await asyncio.wait_for(meeting.MeetingSession(client,'中文').run(),3)
        actual=b''.join(base64.b64decode(e['audio']) for e in upstream.sent if e['type']=='input_audio_buffer.append')
        self.assertEqual(actual,VOICE*273)
        self.assertEqual(upstream.count,2)
        self.assertEqual([e['item_id'] for e in client.events if e['type']=='translation.final'],['item-1','item-2'])
        self.assertEqual(client.events[-1]['type'],'closed');self.assertTrue(upstream.closed)

    async def test_translation_failure_does_not_erase_original(self):
        upstream=FakeASR();client=FakeClient([VOICE]*12)
        with patch.object(meeting,'OPENAI_API_KEY','test'),patch.object(meeting,'connect',return_value=upstream),patch.object(meeting,'translate_text',side_effect=RuntimeError('offline failure')):
            await asyncio.wait_for(meeting.MeetingSession(client,'中文').run(),3)
        self.assertEqual(len([e for e in client.events if e['type']=='source.final']),1)
        self.assertIn('offline failure',next(e['message'] for e in client.events if e['type']=='segment.error'))
        self.assertEqual(client.events[-1]['type'],'closed')

    async def test_bad_pcm_rejected(self):
        client=FakeClient([b'1']);session=meeting.MeetingSession(client,'中文')
        with self.assertRaises(ValueError):await session.read_audio(FakeASR())

    async def test_tiny_last_tail_padded_to_api_minimum(self):
        upstream=FakeASR();session=meeting.MeetingSession(FakeClient([]),'中文')
        tail=VOICE[:480];session.received_bytes=len(tail)
        await session.submit(upstream,tail)
        sent=b''.join(base64.b64decode(e['audio']) for e in upstream.sent if e['type']=='input_audio_buffer.append')
        self.assertEqual(len(sent),4800);self.assertEqual(sent[:len(tail)],tail)
        self.assertEqual(sent[len(tail):],bytes(4800-len(tail)))

    async def test_session_only_runs_transcription_and_translation(self):
        upstream=FakeASR();client=FakeClient([VOICE]*15)
        with patch.object(meeting,'OPENAI_API_KEY','test'),patch.object(meeting,'connect',return_value=upstream),patch.object(meeting,'translate_text',return_value='定位误差'):
            await asyncio.wait_for(meeting.MeetingSession(client,'中文').run(),3)
        self.assertFalse(any(e['type'].startswith('speaker.') for e in client.events))
        self.assertTrue(any(e['type']=='translation.final' for e in client.events))
        self.assertEqual(client.events[-1]['type'],'closed')


class TopicTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=Glossaries(self.temp.name)

    def test_four_independent_persistent_databases(self):
        self.assertEqual(len(list(Path(self.temp.name).glob('*.sqlite3'))),4)
        self.db.save('indoor','TESTXYZ',ja='テスト',zh='测试术语')
        again=Glossaries(self.temp.name)
        self.assertTrue(any(t['term']=='TESTXYZ' for t in again.list('indoor')))
        self.assertFalse(any(t['term']=='TESTXYZ' for t in again.list('animals')))

    def test_candidates_not_used_until_confirmed(self):
        self.db.observe('indoor','XYZABC を使います。ビーコンの測位誤差。')
        self.assertTrue(any(t['term']=='XYZABC' and t['status']=='candidate' for t in self.db.list('indoor')))
        self.assertFalse(any(t['term']=='XYZABC' for t in self.db.guidance('indoor')))
        self.db.save('indoor','XYZABC',zh='待验证缩写',status='confirmed')
        self.assertTrue(any(t['term']=='XYZABC' for t in self.db.guidance('indoor')))

    def test_updates_archived_and_audited(self):
        self.db.save('indoor','RSSI',zh='修订术语')
        self.db.save('indoor','RSSI',status='archived')
        self.assertFalse(any(t['term']=='RSSI' for t in self.db.guidance('indoor')))
        with self.db.connect('indoor') as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM revisions').fetchone()[0],2)

    def test_invalid_topic_or_multiline_terms_rejected(self):
        with self.assertRaises(ValueError):self.db.list('../outside')
        with self.assertRaises(ValueError):self.db.save('indoor','bad\nterm')

    def test_prompt_changes_with_topic_without_language_lock(self):
        config=meeting.asr_configuration('biology',self.db)['session']['audio']['input']['transcription']
        self.assertIn('biolog',config['prompt'])
        self.assertIn('PCR',config['keywords']);self.assertNotIn('RSSI',config['keywords'])
        self.assertEqual(config['languages'],['ja','en'])
        self.assertNotIn('language',config)
        self.assertEqual(config['delay'],'low')

    def test_translation_request_contains_context_and_confirmed_terms(self):
        captured={}
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps({'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'定位误差为两米。'}]}]}).encode()
        def fake(request,**kwargs):captured.update(json.loads(request.data));return Response()
        self.db.observe('indoor','XYZABC')
        with patch.object(meeting,'urlopen',side_effect=fake):
            result=meeting.translate_text('測位誤差は二メートルです。','中文',[{'source':'localization error'}],'indoor',self.db)
        self.assertEqual(result,'定位误差为两米。');self.assertFalse(captured['store'])
        data=json.loads(captured['input'])
        self.assertEqual(data['previous_turns'][0]['source'],'localization error')
        self.assertFalse(any(t['term']=='XYZABC' for t in data['confirmed_glossary']))


if __name__=='__main__':unittest.main()
