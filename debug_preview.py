"""OFFLINE UI harness, port 8766. Synthetic ASR/translation; never calls OpenAI.

Tests the real browser AudioWorklet, PCM transport and UI rendering. Does NOT
measure recognition or translation accuracy. Uses an isolated temporary glossary.
"""
import tempfile
from pathlib import Path
from unittest.mock import patch
import uvicorn
from fastapi.responses import HTMLResponse

import meeting
import webapp
from test_meeting import FakeASR
from topics import Glossaries
from evidence import SlideText


def main():
    class LayoutASR(FakeASR):
        """UI-only: four short mock turns, not an acoustic segmentation test."""
        def __init__(self):
            super().__init__();self.audio_frames=0
        async def send(self,message):
            import json
            event=json.loads(message)
            if event['type']=='input_audio_buffer.append':
                self.audio_frames+=1
                if self.audio_frames%20==0:
                    await self.events.put({'type':'conversation.item.input_audio_transcription.delta',
                        'item_id':f'item-{self.count+1}','delta':'【模拟】測位誤差について議論します。'})
            await super().send(message)

    class LayoutWindow(meeting.AudioWindow):
        def push(self,pcm,transcript=''):
            ready=super().push(pcm,transcript)
            return ready or (self.flush() if self.size>=48000*5 else None)

    def fake_summary(payload,*args):
        return {'title':'【离线模拟】室内定位讨论','discussion':['比较不同设置下的定位误差。'],
                'conclusions':[],'uncertainties':['模拟数据，没有验证实际发言。'],
                'reference_notes':[payload.reference] if payload.reference else [],
                'source_ids':[s.item_id for s in payload.segments],
                'correction_ids':[payload.segments[0].item_id] if payload.reference else []}
    def fake_review(payload,*args):
        return {'summary':'离线模拟纠错，仅验证界面状态和撤销。','changes':[
            {'item_id':s.item_id,'version':s.version,'source':payload.evidence.text if payload.evidence.kind=='exact_quote' else s.source,
             'translation':'【离线纠错】定位误差为两米。','reason':'离线测试依据','evidence':payload.evidence.text,
             'kind':'user_confirmed' if payload.evidence.kind=='exact_quote' else 'assisted'} for s in payload.segments]}
    html=(webapp.STATIC_DIR/'index.html').read_text()
    html=html.replace('LiveBridge</span>','离线界面测试</span>')
    html=html.replace('开始会议翻译</h1>','离线界面测试</h1>')
    html=html.replace('以日语理解为主，英语提供完整记录与上下文。自动识别日英切换，默认翻译为中文。',
                      '此端口使用模拟识别和模拟翻译，不访问 OpenAI，不代表准确率。请使用模块自检的合成音频。')
    html=html.replace('id="joinBtn" type="button"','id="joinBtn" type="button" disabled')
    async def offline_index():return HTMLResponse(html)
    for route in webapp.app.routes:
        if getattr(route,'path','')=='/':route.endpoint=offline_index;route.dependant.call=offline_index
    with tempfile.TemporaryDirectory(prefix='meeting-ui-test-') as directory:
        webapp.glossaries=Glossaries(Path(directory))
        with patch.object(meeting,'AudioWindow',LayoutWindow),patch.object(meeting,'connect',side_effect=lambda *a,**k:LayoutASR()),patch.object(meeting,'OPENAI_API_KEY','offline-placeholder'),patch.object(meeting,'translate_text',side_effect=lambda text,*a:f'【离线模拟译文】定位误差：{text}'),patch.object(webapp,'review_segments',side_effect=fake_review),patch.object(webapp,'analyze_slide',return_value={'visible_text':'Indoor positioning. Localization error: 2m.','summary':'离线图片测试','terms':['RSSI'],'uncertainty':'模拟提取，不代表识别准确率'}):
            material=SlideText(visible_text='Indoor positioning. Localization error: 2m.',summary='离线文件测试',terms=['RSSI'],uncertainty='模拟内容，不代表图像理解准确率')
            # Exercise real upload validation and HEIC decoding; mock only model output.
            with patch.object(webapp,'summarize',side_effect=fake_summary),patch('evidence.response_json',return_value=material),patch('summaries.response_json',return_value=material):
                uvicorn.run(webapp.app,host='127.0.0.1',port=8766)


if __name__=='__main__':main()
