"""Offline tests. No API key, network, microphone or extra test dependency."""
import asyncio
import base64
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

import asr
from audio import inspect_wav, wav_chunks


class FakeSocket:
    def __init__(self, final=True, error=False):
        self.sent = []
        self.events = asyncio.Queue()
        self.final = final
        self.error = error
        self.closed = False
        self.reader_cancelled = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def send(self, message):
        event = json.loads(message)
        self.sent.append(event)
        if event['type'] == 'session.update':
            await self.events.put({'type': 'session.updated'})
        elif event['type'] == 'input_audio_buffer.append' and self.error:
            await self.events.put({'type': 'error', 'error': {'message': 'test error'}})
        elif event['type'] == 'input_audio_buffer.commit' and self.final:
            await self.events.put({
                'type': 'conversation.item.input_audio_transcription.completed',
                'item_id': 'a', 'transcript': 'OpenPack の実験。',
            })

    async def recv(self):
        return json.dumps(await self.events.get())

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return await self.recv()
        except asyncio.CancelledError:
            self.reader_cancelled = True
            raise


class LocalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'sample.wav'
        self.output = io.StringIO()
        self.capture = redirect_stdout(self.output)
        self.capture.__enter__()
        self.addCleanup(self.capture.__exit__, None, None, None)

    def make_wav(self, channels=1, width=2, rate=24000, frames=6000):
        payload = bytes(range(256)) * ((frames * width * channels + 255) // 256)
        payload = payload[:frames * width * channels]
        with wave.open(str(self.path), 'wb') as recording:
            recording.setparams((channels, width, rate, 0, 'NONE', 'not compressed'))
            recording.writeframes(payload)
        return payload

    async def test_pcm_and_pacing_including_partial_chunk(self):
        payload = self.make_wav()
        clock = [0.0]
        delays = []
        async def sleep(delay):
            delays.append(delay)
            clock[0] += delay
        with patch('audio.time.monotonic', side_effect=lambda: clock[0]), patch('audio.asyncio.sleep', sleep):
            chunks = [chunk async for chunk in wav_chunks(self.path)]
        self.assertEqual(b''.join(chunks), payload)
        self.assertEqual([len(chunk) for chunk in chunks], [4800, 4800, 2400])
        for actual, expected in zip(delays, [0.1, 0.1, 0.05]):
            self.assertAlmostEqual(actual, expected)
        self.assertAlmostEqual(inspect_wav(self.path), 0.25)

    async def test_unsupported_formats_and_empty_file(self):
        for kwargs in ({'channels': 2}, {'width': 1}, {'rate': 44100}, {'frames': 0}):
            with self.subTest(kwargs=kwargs):
                self.make_wav(**kwargs)
                with self.assertRaises(ValueError):
                    inspect_wav(self.path)

    async def test_truncated_file(self):
        self.make_wav(frames=240)
        self.path.write_bytes(self.path.read_bytes()[:-100])
        with self.assertRaisesRegex(ValueError, 'truncated'):
            _ = [chunk async for chunk in wav_chunks(self.path)]

    async def test_offline_cli(self):
        self.make_wav(frames=2400)
        result = await asyncio.to_thread(subprocess.run,
            [sys.executable, '-B', 'app.py', '--audio-file', str(self.path), '--dry-run'],
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('chunks=1 bytes=4800', result.stdout)
        self.assertIn('no API or microphone used', result.stdout)

    async def test_pcm_encoding_and_single_commit(self):
        socket = FakeSocket()
        async def audio():
            yield b'\x00\x80\xff\x7f'
        await asr.send_audio(socket, audio(), file_mode=True)
        self.assertEqual(base64.b64decode(socket.sent[0]['audio']), b'\x00\x80\xff\x7f')
        self.assertEqual(socket.sent[1], {'type': 'input_audio_buffer.commit'})
        self.assertEqual(len(socket.sent), 2)

    async def test_live_client_vad_commits_after_silence(self):
        socket = FakeSocket(final=False)
        silence = bytes(4800)
        speech = (1000).to_bytes(2, 'little', signed=True) * 2400

        async def audio():
            for chunk in [silence] * 10 + [speech] * 2 + [silence] * 10:
                yield chunk

        await asr.send_audio(socket, audio())
        event_types = [event['type'] for event in socket.sent]
        self.assertEqual(event_types.count('input_audio_buffer.commit'), 1)
        # Long leading silence is reduced to the configured 300 ms pre-roll.
        self.assertEqual(event_types.count('input_audio_buffer.append'), 11)

    def test_live_session_disables_unsupported_server_vad(self):
        session = asr.session_update(file_mode=False)
        self.assertIsNone(session['session']['audio']['input']['turn_detection'])

    async def test_file_waits_for_final_and_closes(self):
        socket = FakeSocket()
        async def audio():
            yield bytes(4800)
        with patch('asr.connect', return_value=socket):
            await asr.transcribe(audio(), 'test-key', file_mode=True)
        self.assertIn('[RAW ASR]', self.output.getvalue())
        self.assertIn('OpenPack の実験。', self.output.getvalue())
        self.assertTrue(socket.closed)
        self.assertIsNone(socket.sent[0]['session']['audio']['input']['turn_detection'])

    async def test_final_timeout_cleans_up(self):
        socket = FakeSocket(final=False)
        async def audio():
            yield bytes(4800)
        with patch('asr.connect', return_value=socket):
            with self.assertRaises(TimeoutError):
                await asr.transcribe(audio(), 'test-key', file_mode=True, final_timeout=0.01)
        self.assertTrue(socket.closed)
        self.assertTrue(socket.reader_cancelled)

    async def test_api_error_cancels_audio_sender(self):
        socket = FakeSocket(error=True)
        cancelled = asyncio.Event()
        async def audio():
            try:
                yield (1000).to_bytes(2, 'little', signed=True) * 2400
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        with patch('asr.connect', return_value=socket):
            with self.assertRaisesRegex(RuntimeError, 'test error'):
                await asr.transcribe(audio(), 'test-key')
        self.assertTrue(cancelled.is_set())
        self.assertTrue(socket.closed)

    async def test_interleaved_transcripts_and_disconnect(self):
        async def events():
            for event in [
                {'type': 'input_audio_buffer.speech_stopped', 'item_id': 'a'},
                {'type': 'conversation.item.input_audio_transcription.delta', 'item_id': 'b', 'delta': 'Macro'},
                {'type': 'conversation.item.input_audio_transcription.completed', 'item_id': 'b', 'transcript': 'Macro-F1'},
                {'type': 'conversation.item.input_audio_transcription.completed', 'item_id': 'a', 'transcript': 'OpenPack'},
            ]:
                yield json.dumps(event)
        with self.assertRaisesRegex(RuntimeError, 'closed'):
            await asr.print_transcripts(events())
        output = self.output.getvalue()
        self.assertIn('item=b Macro-F1', output)
        self.assertIn('item=a OpenPack', output)
        self.assertEqual(output.count('[TIMING]'), 1)

    async def test_failed_transcription_is_not_ignored(self):
        with self.assertRaises(RuntimeError):
            asr.check_error({'type': 'conversation.item.input_audio_transcription.failed',
                             'error': {'message': 'failed'}})


if __name__ == '__main__':
    unittest.main()
