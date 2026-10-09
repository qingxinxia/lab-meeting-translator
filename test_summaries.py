import base64
import asyncio
import unittest
from unittest.mock import patch, Mock
from fastapi import HTTPException
from starlette.requests import Request
from summaries import SummaryInput, SummaryResult, MaterialInput, summarize, analyze_material
import webapp


class SummaryTests(unittest.TestCase):
    def payload(self):
        return SummaryInput(topic='indoor',start=0,end=60,segments=[
            {'item_id':'a','source':'測位誤差は2メートル','translation':'定位误差为2米','version':2}])

    def result(self,ids=None):
        return SummaryResult(title='定位误差',discussion=['讨论定位误差'],conclusions=[],
            uncertainties=['没有逐字真值'],reference_notes=[],source_ids=ids or ['a'],correction_ids=[])

    def test_summary_preserves_no_conclusion_and_citations(self):
        with patch('summaries.response_json',return_value=self.result()) as call:
            out=summarize(self.payload(),Mock(guidance=lambda *a:''),'中文')
        self.assertEqual(out['conclusions'],[]);self.assertEqual(out['source_ids'],['a'])
        self.assertIn('NOT verified speech',call.call_args.args[0])

    def test_foreign_citation_is_rejected(self):
        with patch('summaries.response_json',return_value=self.result(['foreign'])):
            with self.assertRaises(ValueError):summarize(self.payload(),Mock(guidance=lambda *a:''),'中文')

    def test_invalid_windows_duplicate_ids_and_oversize_text(self):
        data=self.payload().model_dump()
        for end in [0,301]:
            with self.assertRaises(ValueError):SummaryInput(**dict(data,end=end))
        with self.assertRaises(ValueError):SummaryInput(**dict(data,segments=data['segments']*2))

    def test_material_requires_consent_and_valid_file(self):
        for filename,data,consent in [('x.pdf','https://bad',True),('x.exe','data:text/plain;base64,YQ==',True),
            ('x.pdf','data:application/pdf;base64,YQ==',True),('x.txt','data:text/plain;base64,YQ==',False),
            ('x.pptx','data:application/zip;base64,YQ==',True)]:
            with self.assertRaises(ValueError):analyze_material(MaterialInput(filename=filename,data=data,consent=consent))

    def test_text_material_uses_inline_file_without_upload_persistence(self):
        from evidence import SlideText
        result=SlideText(visible_text='RSSI',summary='信号强度',terms=['RSSI'],uncertainty='')
        with patch('summaries.response_json',return_value=result) as call:
            out=analyze_material(MaterialInput(filename='private.txt',data='data:text/plain;base64,'+base64.b64encode(b'RSSI').decode(),consent=True))
        self.assertEqual(out['terms'],['RSSI'])
        self.assertEqual(call.call_args.args[1][0]['filename'],'reference.txt')

    def test_routes_reject_cross_origin_and_unapproved_material(self):
        request=Request({'type':'http','headers':[(b'host',b'localhost')]})
        foreign=Request({'type':'http','headers':[(b'host',b'localhost'),(b'origin',b'https://other.test')]})
        with self.assertRaises(HTTPException) as error:asyncio.run(webapp.summary_endpoint(self.payload(),foreign))
        self.assertEqual(error.exception.status_code,403)
        with self.assertRaises(HTTPException) as error:
            asyncio.run(webapp.material_endpoint(MaterialInput(filename='a.txt',data='data:text/plain;base64,YQ=='),request))
        self.assertEqual(error.exception.status_code,400)
        with patch.object(webapp,'summarize',return_value=self.result().model_dump()):
            self.assertEqual(asyncio.run(webapp.summary_endpoint(self.payload(),request))['source_ids'],['a'])
