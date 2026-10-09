import base64
import tempfile
import unittest
from unittest.mock import patch
from evidence import ReviewInput,Review,Change,review_segments,analyze_slide
from topics import Glossaries


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.db=Glossaries(temp.name)
        self.data={'topic':'indoor','target':'zh','segments':[{'item_id':'a','source':'測位誤差は2メートルです。','translation':'速度测量是2米。','version':2}],
                   'evidence':{'kind':'note','text':'測位是定位，不是速度测量'}}

    def test_note_revises_translation_without_changing_original(self):
        result=Review(summary='术语误译',changes=[Change(item_id='a',action='revise_translation',translation='定位误差为2米。',reason='日语測位与定位对应')])
        with patch('evidence.response_json',return_value=result):out=review_segments(ReviewInput(**self.data),self.db,'中文')
        self.assertEqual(out['changes'][0]['source'],self.data['segments'][0]['source'])
        self.assertEqual(out['changes'][0]['kind'],'assisted');self.assertEqual(out['changes'][0]['version'],2)

    def test_unknown_model_item_is_rejected(self):
        result=Review(summary='bad',changes=[Change(item_id='foreign',action='revise_translation',translation='错误',reason='bad')])
        with patch('evidence.response_json',return_value=result):
            with self.assertRaises(ValueError):review_segments(ReviewInput(**self.data),self.db,'中文')

    def test_exact_quote_is_user_text_not_model_invented_source(self):
        self.data['evidence']={'kind':'exact_quote','text':'測位誤差は3メートルです。'}
        with patch('meeting.translate_text',return_value='定位误差为3米。'):
            out=review_segments(ReviewInput(**self.data),self.db,'中文')
        self.assertEqual(out['changes'][0]['source'],self.data['evidence']['text'])
        self.assertEqual(out['changes'][0]['kind'],'user_confirmed')

    def test_exact_quote_cannot_overwrite_multiple_segments(self):
        self.data['segments']*=2;self.data['evidence']['kind']='exact_quote'
        with self.assertRaises(ValueError):review_segments(ReviewInput(**self.data),self.db,'中文')

    def test_slide_rejects_remote_url_wrong_magic_and_invalid_base64(self):
        for image in ['https://example.com/a.png','data:image/png;base64,%%',
                      'data:image/png;base64,'+base64.b64encode(b'not a png').decode()]:
            with self.assertRaises(ValueError):analyze_slide(image)


if __name__=='__main__':unittest.main()
