"""Reviewed local curation, with SQLite backups. No audio/API/network access.

Only literal, unambiguous vocabulary receives a lexical mapping. ASR occurrence
and personal attribution are separate from that mapping's reviewed meaning.
"""
import json
import argparse
import hashlib
from pathlib import Path
import sqlite3
import tempfile

from topics import Glossaries, ROOT

# observed spelling, English form, Chinese rendering, applicable topic libraries
VOCABULARY = [
    ('アクセスポイント','access point','无线接入点',['indoor']),
    ('センサー','sensor','传感器',['indoor','animals','har']),
    ('ベクトル','vector','向量',['indoor','har']),
    ('スカラー','scalar','标量',['indoor']),
    ('キャリブレーション','calibration','校准',['indoor','har']),
    ('フロアプラン','floor plan','楼层平面图',['indoor']),
    ('ナビゲーション','navigation','导航',['indoor']),
    ('マッピング','mapping','映射；建图（依语境）',['indoor']),
    ('センサデータ','sensor data','传感器数据',['indoor','animals','har']),
    ('ウェアラブルデバイス','wearable device','可穿戴设备',['indoor','animals','har']),
    ('バイオロギングデバイス','biologging device','生物记录设备',['animals','indoor']),
    ('アノテーション','annotation','标注',['indoor','animals','biology','har']),
    ('ラベリング','labeling','标注；打标签',['indoor','animals','har']),
    ('データセット','dataset','数据集',['indoor','animals','biology','har']),
    ('アンラベルドデータ','unlabeled data','无标签数据',['indoor','har']),
    ('エンベディング','embedding','嵌入表示',['indoor','har']),
    ('アブレーション','ablation','消融；消融实验（模型评估语境）',['indoor','har']),
    ('ベースライン','baseline','基线方法',['indoor','animals','biology','har']),
    ('セグメンテーション','segmentation','分割；分段（依语境）',['indoor','animals','har']),
    ('テンポラルセグメンテーション','temporal segmentation','时间分段',['indoor','animals','har']),
    ('タイムシリーズ','time series','时间序列',['indoor','animals','har']),
    ('モダリティ','modality','模态',['indoor','animals','har']),
    ('ゼロショット','zero-shot','零样本',['indoor','har']),
    ('パラメータ','parameter','参数',['indoor','biology','har']),
    ('トレーナブルパラメータ','trainable parameter','可训练参数',['indoor','har']),
    ('エンコーダー','encoder','编码器',['biology','har']),
    ('ベンチマーク','benchmark','基准；基准测试',['har']),
    ('サンプリング','sampling','采样',['har','animals']),
    ('シミュレーテッドデータ','simulated data','模拟数据',['har']),
    ('リアルデータ','real data','真实数据',['har']),
    ('ドメイン','domain','领域；数据域（依语境）',['har']),
    ('トレーニングバッチ','training batch','训练批次',['har']),
    ('ノベルティ','novelty','创新性；新颖性',['indoor','har']),
    ('モデルサイズ','model size','模型大小',['animals','biology','har']),
    ('アーキテクチャ','architecture','架构',['animals','har']),
    ('トレードオフ','trade-off','权衡',['animals','har']),
    ('ファインチューニング','fine-tuning','微调',['biology','har']),
    ('ロジット','logit','模型归一化前的分数；二分类中可指对数几率',['biology','har']),
    ('コンフュージョンマトリックス','confusion matrix','混淆矩阵',['biology','har']),
    ('バリデーション','validation','验证',['biology','har']),
    ('バリデーションデータ','validation data','验证数据',['biology','har']),
    ('チェックポイント','checkpoint','检查点',['biology','har']),
    ('テクニカルコントリビューション','technical contribution','技术贡献',['biology','har']),
    ('ハムスター','hamster','仓鼠',['biology','animals']),
]

EXPRESSIONS = [
    ('ちょっと','稍微；一下；有点','可表示缓和、犹豫或委婉保留意见，不能总译成数量很少；没有宾语时不补造内容。'),
    ('今のところ','目前；现阶段','保留暂定范围，不将当前观察译为最终结论。'),
    ('とりあえず','先；暂且','通常引出临时处理或下一步，不表示问题已解决。'),
    ('あれだね','那个……；是这样啊','指代不明时保留含糊，不能擅自补成技术名词或确定结论。'),
    ('どうするか','怎么处理；如何设置','属于待讨论的问题，不能译成已决定的方案。'),
    ('考えていきたい','想继续考虑；希望进一步探讨','保留意向和未定状态，不译成已确认执行。'),
    ('わからない','不清楚；还不知道','保留否定和不确定性，不能因惯用表达而改成知道或同意。'),
]

UNCERTAIN = {
    'SSI':'不能自动合并为 RSSI，需用户或原声确认缩写。',
    'ビスパー':'可能是专名或识别错误；未确认前不能自动替换为 Whisper。',
    'リスパン':'原词不明，禁止自动补成产品或模型名。',
    'オーブパック':'不能仅凭近似发音自动归为 OpenPack。',
    'バイオリンデバイス':'可能是误识别，不能自动改为生物记录设备。',
    'シミュレー':'疑似词中截断，不能自动补全。',
    'シームデータ':'原词不明，不能自动等同模拟数据。',
    'ソストラベル':'疑似误识别，未核对前不自动改为 soft label。',
}


def backup(root):
    parent=root.parent/'backups';parent.mkdir(exist_ok=True)
    target=Path(tempfile.mkdtemp(prefix='before-memory-curation-',dir=parent))
    for path in root.rglob('*.sqlite3'):
        destination=target/path.relative_to(root);destination.parent.mkdir(parents=True,exist_ok=True)
        source=sqlite3.connect(f'file:{path}?mode=ro',uri=True)
        output=sqlite3.connect(destination)
        try:source.backup(output)
        finally:output.close();source.close()
        destination.chmod(0o600)
    return target


def curate(root=ROOT, reports=None, profile_name=None):
    root=Path(root);saved=backup(root);db=Glossaries(root)
    original={topic:db.list(topic) for topic in ('indoor','animals','biology','har')}
    observations={}
    for topic,rows in original.items():
        for row in rows:
            if row['uses']>0:
                observations.setdefault(row['term'],[]).append((topic,row))
    changed=[]
    for form,english,zh,targets in VOCABULARY:
        evidence=observations.get(form,[])
        if not evidence:continue  # No invented claim of past occurrence.
        for topic in targets:
            rows=db.list(topic)
            row=next((r for r in rows if r['term']==form),None)
            canonical=next((r for r in rows if r['status']=='confirmed' and english.casefold() in
                [s.casefold() for s in [r['term'],*r['aliases']]]),None)
            if canonical:
                target_term=canonical['term']
                if row and row['status']=='candidate':
                    db.save(topic,form,ja=form,zh=zh,aliases=[english],status='archived',
                        notes=f'重复拼写已归入 {target_term}；原候选计数保留，未删除。')
            elif not row or row['status']=='candidate':
                target_term=form
                note='已整理标准词义；历史出现证据为未核对的机器候选计数，不代表原话或发言归属已确认。'
                if topic not in [t for t,_ in evidence]:note+=' 从其他专题按术语适用范围共享，不代表本专题会议中出现。'
                db.save(topic,form,ja=form,zh=zh,aliases=[english],notes=note,status='confirmed')
                changed.append((topic,form))
            else:
                target_term=row['term']  # Do not overwrite confirmed/archived user edits.
            with db.connect(topic) as connection:
                for source_topic,old in evidence:
                    connection.execute('INSERT OR IGNORE INTO term_evidence(term,source_ref,source_kind,excerpt) VALUES (?,?,?,?)',
                        (target_term,f'legacy:{source_topic}:{form}','legacy_counter_unverified',
                         f'{source_topic} 候选 {form}，历史计数 {old["uses"]}；旧系统没有保存该词的逐段上下文。'))
    for topic,rows in original.items():
        for row in rows:
            if row['term'] in UNCERTAIN and row['status']=='candidate':
                note=UNCERTAIN[row['term']]
                if note not in row['notes']:
                    db.save(topic,row['term'],ja=row['ja'],zh=row['zh'],aliases=row['aliases'],
                            notes=(row['notes']+' '+note).strip(),status='candidate')
    # Only the saved real-meeting ASR report, never synthetic/public fixtures.
    report=Path(reports) if reports else None
    if report and report.exists():
        data=json.loads(report.read_text())
        report_id=hashlib.sha256(report.read_bytes()).hexdigest()[:20]
        finals=[e for e in data['full_recording']['events'] if e['type'].endswith('.completed')]
        all_text=' '.join(e.get('transcript','') for e in finals)
        for phrase,zh,note in EXPRESSIONS:
            if phrase in all_text and not any(r['phrase']==phrase for r in db.expressions.list()):
                db.expressions.save(phrase,zh,note,'confirmed')
        for e in finals:
            db.expressions.observe(e.get('transcript',''),f'local-report:{report_id}:{e["item_id"]}',
                                   'asr_unverified_same_recording')
    if profile_name:db.expressions.request_profile(profile_name)
    return {'backup':str(saved),'curated_term_entries':len(changed),
            'counts':{topic:{state:sum(r['status']==state for r in db.list(topic))
                for state in ('confirmed','candidate','archived')} for topic in original},
            'expressions':db.expressions.list(),'attribution':'个人表达须用户确认，没有自动归属任何发言。'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record-report',type=Path,help='Explicitly selected, consented local transcription report')
    parser.add_argument('--profile-name',help='Optional manual expression profile, stored only in the local database')
    args=parser.parse_args()
    if args.record_report and not args.record_report.is_file():parser.error('Transcription report not found')
    print(json.dumps(curate(reports=args.record_report,profile_name=args.profile_name),ensure_ascii=False,indent=2))
