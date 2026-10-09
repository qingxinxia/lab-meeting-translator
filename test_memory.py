"""Local database curation and prompt-boundary tests; no API requests."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from topics import Glossaries
from curate_meeting_memory import curate
import meeting


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'glossaries';self.db=Glossaries(self.root)

    def test_observation_is_idempotent_and_candidates_remain_untrusted(self):
        for _ in range(2):self.db.observe('indoor','ビーコンと XYZABC を使います。',source_ref='meeting:one:item1')
        rows={r['term']:r for r in self.db.list('indoor')}
        self.assertEqual(rows['beacon']['uses'],1)
        self.assertEqual(rows['XYZABC']['uses'],1)
        self.assertEqual(rows['XYZABC']['status'],'candidate')
        with self.db.connect('indoor') as db:
            self.assertEqual(db.execute('select count(*) from term_evidence').fetchone()[0],2)
        self.assertFalse(any(r['term']=='XYZABC' for r in self.db.guidance('indoor')))

    def test_expression_context_is_local_and_attribution_never_automatic(self):
        memory=self.db.expressions
        memory.save('とりあえず','暂且','不要当成最终方案','confirmed')
        memory.request_profile('示例教师')
        for _ in range(2):memory.observe('とりあえず試します。','meeting:one:item1')
        self.assertEqual(memory.list()[0]['evidence_count'],1)
        with memory.connect() as db:
            self.assertEqual(db.execute('select count(*) from attributions').fetchone()[0],0)
        with self.assertRaises(ValueError):memory.confirm_attribution('とりあえず','示例教师','')
        memory.confirm_attribution('とりあえず','示例教师','用户明确确认这段表达属于示例教师')
        hints=memory.guidance('とりあえず試します。')
        self.assertEqual(len(hints),1)
        self.assertNotIn('示例教师',json.dumps(hints,ensure_ascii=False))
        self.assertNotIn('source_ref',hints[0])
        self.assertEqual(memory.guidance('別の話です。'),[])
        memory.save('とりあえず','暂且','不要当成最终方案','archived')
        self.assertEqual(memory.guidance('とりあえず'),[])

    def test_curation_backs_up_keeps_ambiguous_candidates_and_preserves_user_edits(self):
        self.db.observe('indoor','アクセスポイントと SSI とバイオロギングデバイス',source_ref='old:a')
        self.db.save('har','サンプリング',zh='用户自己的译法',status='confirmed')
        missing=Path(self.tmp.name)/'no-recording.json'
        result=curate(self.root,reports=missing)
        self.assertEqual(len(list(Path(result['backup']).glob('*.sqlite3'))),4)
        rows={r['term']:r for r in self.db.list('indoor')}
        self.assertEqual(rows['アクセスポイント']['zh'],'无线接入点')
        self.assertEqual(rows['SSI']['status'],'candidate')
        self.assertEqual(rows['SSI']['aliases'],[])
        self.assertTrue(any(r['term']=='バイオロギングデバイス' for r in self.db.list('animals',True)))
        self.assertEqual(next(r for r in self.db.list('har') if r['term']=='サンプリング')['zh'],'用户自己的译法')
        self.assertEqual(curate(self.root,reports=missing)['curated_term_entries'],0)
        with self.db.expressions.connect() as db:
            self.assertEqual(db.execute('select count(*) from attributions').fetchone()[0],0)

    def test_translation_uses_only_matched_reviewed_meanings_not_past_quotes(self):
        self.db.expressions.save('ちょっと','稍微；一下','保留委婉和犹豫','confirmed')
        self.db.expressions.save('未确认口语','未知','不能用于翻译','candidate')
        captured={}
        class Response:
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self):return json.dumps({'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'考虑一下。'}]}]}).encode()
        def request(req,**kwargs):captured.update(json.loads(req.data));return Response()
        with patch.object(meeting,'urlopen',side_effect=request):
            meeting.translate_text('ちょっと考えます。','中文',[],'indoor',self.db)
        hints=json.loads(captured['input'])['expression_hints']
        self.assertEqual([r['phrase'] for r in hints],['ちょっと'])
        keywords=meeting.asr_configuration('indoor',self.db)['session']['audio']['input']['transcription']['keywords']
        self.assertNotIn('ちょっと',keywords)


if __name__=='__main__':unittest.main()
