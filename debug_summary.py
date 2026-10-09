"""Real API smoke test using synthetic text only; no microphone or meeting files."""
import base64
import json
from summaries import SummaryInput,MaterialInput,summarize,analyze_material
from topics import Glossaries


def main():
    text='SYNTHETIC TEST ONLY. Indoor positioning. Median localization error: 2 meters. RSSI: -65 dBm.'
    material=analyze_material(MaterialInput(filename='synthetic.txt',consent=True,
        data='data:text/plain;base64,'+base64.b64encode(text.encode()).decode()))
    print(json.dumps({'material':material},ensure_ascii=False))
    payload=SummaryInput(topic='indoor',start=0,end=60,segments=[
        {'item_id':'test-ja','source':'室内測位の誤差の中央値は2メートルです。部屋ごとの差を調べたいです。','translation':'室内定位误差的中位数是2米，想调查房间之间的差异。','version':2},
        {'item_id':'test-en','source':'We have not decided which configuration to use.','translation':'尚未决定使用哪一种配置。','version':2}],
        reference='Synthetic slide reference: RSSI is -65 dBm. This value was not spoken.')
    result=summarize(payload,Glossaries(),'中文')
    print(json.dumps({'summary':result},ensure_ascii=False))
    assert result['source_ids'] and result['discussion']


if __name__=='__main__':main()
