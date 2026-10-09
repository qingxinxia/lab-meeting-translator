"""Four independent, persistent SQLite glossaries. Only confirmed terms guide APIs."""
import json
from pathlib import Path
import re
import sqlite3
import uuid
from contextlib import contextmanager
from expressions import Expressions

ROOT = Path(__file__).parent / "data" / "glossaries"
PROFILES = {
    "indoor": {"name": "室内定位", "context": "indoor positioning and localization", "terms": [
        ("indoor positioning", "室内測位", "室内定位", ["indoor localization", "屋内測位"]),
        ("localization error", "測位誤差", "定位误差", []),
        ("fingerprinting", "フィンガープリンティング", "指纹定位", ["電波指紋"]),
        ("beacon", "ビーコン", "信标", []), ("BLE", "Bluetooth Low Energy", "低功耗蓝牙", []),
        ("UWB", "超広帯域", "超宽带", ["ultra-wideband"]),
        ("RSSI", "受信信号強度", "接收信号强度", []), ("CSI", "チャネル状態情報", "信道状态信息", []),
        ("multipath", "マルチパス", "多径", []), ("NLOS", "非見通し", "非视距", []),
        ("time of flight", "飛行時間", "飞行时间", ["ToF"]),
        ("TDoA", "到達時間差", "到达时间差", []), ("angle of arrival", "到来角", "到达角", ["AoA"]),
        ("PDR", "歩行者自律航法", "行人航位推算", []), ("SLAM", "自己位置推定と環境地図作成", "同步定位与建图", []),
        ("Kalman filter", "カルマンフィルタ", "卡尔曼滤波", []),
        ("particle filter", "パーティクルフィルタ", "粒子滤波", []),
    ]},
    "animals": {"name": "动物", "context": "animal behavior, ecology and animal research", "terms": [
        ("ethology", "動物行動学", "动物行为学", []), ("ethogram", "エソグラム", "行为谱", []),
        ("foraging", "採餌", "觅食", []), ("locomotion", "移動運動", "运动行为", []),
        ("habituation", "馴化", "习惯化", []), ("enrichment", "環境エンリッチメント", "环境丰富化", []),
        ("circadian rhythm", "概日リズム", "昼夜节律", []), ("phenotype", "表現型", "表型", []),
        ("telemetry", "テレメトリー", "遥测", []), ("home range", "行動圏", "活动范围", []),
        ("welfare", "動物福祉", "动物福利", []), ("gait", "歩容", "步态", []),
    ]},
    "biology": {"name": "生物实验", "context": "molecular biology and biological laboratory experiments", "terms": [
        ("PCR", "ポリメラーゼ連鎖反応", "聚合酶链式反应", []),
        ("qPCR", "定量PCR", "定量PCR", []), ("Western blot", "ウェスタンブロット", "蛋白质免疫印迹", []),
        ("cell culture", "細胞培養", "细胞培养", []), ("transfection", "トランスフェクション", "转染", []),
        ("knockout", "ノックアウト", "基因敲除", []), ("knockdown", "ノックダウン", "基因敲低", []),
        ("CRISPR", "クリスパー", "CRISPR基因编辑", []), ("flow cytometry", "フローサイトメトリー", "流式细胞术", []),
        ("ELISA", "酵素結合免疫吸着測定法", "酶联免疫吸附测定", []),
        ("replicate", "反復", "重复实验", []), ("negative control", "陰性対照", "阴性对照", []),
        ("antibody", "抗体", "抗体", []), ("centrifugation", "遠心分離", "离心", []),
    ]},
    "har": {"name": "HAR", "context": "human activity recognition, wearable sensors and time-series learning", "terms": [
        ("HAR", "人間行動認識", "人体活动识别", ["human activity recognition"]),
        ("IMU", "慣性計測装置", "惯性测量单元", []), ("OpenPack", "オープンパック", "OpenPack数据集", ["open pack"]),
        ("HarBench", "ハーベンチ", "HarBench基准", []),
        ("LOSO", "被験者単位交差検証", "留一被试交叉验证", ["leave-one-subject-out"]),
        ("Macro-F1", "マクロF1", "宏平均F1", ["macro f1"]),
        ("SupCon", "教師あり対照学習", "监督对比学习", []), ("InfoNCE", "InfoNCE", "InfoNCE损失", []),
        ("domain adaptation", "ドメイン適応", "领域适应", []),
        ("contrastive learning", "対照学習", "对比学习", []),
        ("fine-tuning", "ファインチューニング", "微调", []),
        ("sliding window", "スライディングウィンドウ", "滑动窗口", []),
    ]},
}


class Glossaries:
    def __init__(self, root=ROOT):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.expressions = Expressions(self.root/'memory'/'expressions.sqlite3')
        for key, profile in PROFILES.items():
            with self.connect(key) as db:
                db.executescript("""
                CREATE TABLE IF NOT EXISTS terms (
                  term TEXT PRIMARY KEY COLLATE NOCASE, ja TEXT NOT NULL DEFAULT '', zh TEXT NOT NULL DEFAULT '',
                  aliases TEXT NOT NULL DEFAULT '[]', notes TEXT NOT NULL DEFAULT '',
                  status TEXT NOT NULL DEFAULT 'confirmed', uses INTEGER NOT NULL DEFAULT 0,
                  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS revisions (
                  id INTEGER PRIMARY KEY, term TEXT, before_json TEXT, after_json TEXT,
                  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS corrections (
                  id INTEGER PRIMARY KEY, original TEXT, corrected TEXT, translation TEXT,
                  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                CREATE TABLE IF NOT EXISTS term_evidence (
                  term TEXT NOT NULL COLLATE NOCASE, source_ref TEXT NOT NULL,
                  source_kind TEXT NOT NULL, excerpt TEXT NOT NULL,
                  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  PRIMARY KEY(term,source_ref));
                """)
                db.executemany("INSERT OR IGNORE INTO terms(term,ja,zh,aliases) VALUES (?,?,?,?)",
                               [(en, ja, zh, json.dumps(aliases, ensure_ascii=False)) for en, ja, zh, aliases in profile["terms"]])

    @contextmanager
    def connect(self, topic):
        if topic not in PROFILES: raise ValueError("Unknown meeting topic")
        db = sqlite3.connect(self.root / f"{topic}.sqlite3", timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def list(self, topic, confirmed=False):
        with self.connect(topic) as db:
            where = " WHERE status='confirmed'" if confirmed else ""
            rows = db.execute("SELECT * FROM terms" + where + " ORDER BY uses DESC, term").fetchall()
            return [{**dict(row), "aliases": json.loads(row["aliases"])} for row in rows]

    def save(self, topic, term, ja="", zh="", aliases=None, notes="", status="confirmed"):
        term = term.strip(); aliases = aliases or []
        values = [term, ja, zh, notes, *aliases]
        if not term or len(term)>120 or len(aliases)>20 or any(not isinstance(v,str) or len(v)>500 or any(c in v for c in '\r\n<>') for v in values):
            raise ValueError("术语不能为空；不允许换行或尖括号，单项不超过 500 字")
        if status not in {"confirmed", "candidate", "archived"}: raise ValueError("Invalid term status")
        after = {"term":term,"ja":ja.strip(),"zh":zh.strip(),"aliases":aliases,"notes":notes,"status":status}
        with self.connect(topic) as db:
            old = db.execute("SELECT * FROM terms WHERE term=?",(term,)).fetchone()
            db.execute("""INSERT INTO terms(term,ja,zh,aliases,notes,status) VALUES (?,?,?,?,?,?)
              ON CONFLICT(term) DO UPDATE SET ja=excluded.ja,zh=excluded.zh,aliases=excluded.aliases,
              notes=excluded.notes,status=excluded.status,updated_at=CURRENT_TIMESTAMP""",
              (term,after["ja"],after["zh"],json.dumps(aliases,ensure_ascii=False),notes,status))
            db.execute("INSERT INTO revisions(term,before_json,after_json) VALUES (?,?,?)",
                       (term,json.dumps(dict(old),ensure_ascii=False) if old else None,json.dumps(after,ensure_ascii=False)))
        return after

    def observe(self, topic, text, source_ref=None, source_kind='asr'):
        """Count known terms; conservatively propose acronyms/katakana, never auto-trust ASR."""
        source_ref=source_ref or 'observation:'+uuid.uuid4().hex
        folded = text.casefold(); known = set()
        with self.connect(topic) as db:
            for row in self.list(topic):
                forms=[row["term"],row["ja"],row["zh"],*row["aliases"]]; known.update(s.casefold() for s in forms if s)
                matches=[s for s in forms if s and s.casefold() in folded]
                if matches:
                    pos=folded.index(matches[0].casefold())
                    evidence=db.execute('INSERT OR IGNORE INTO term_evidence(term,source_ref,source_kind,excerpt) VALUES (?,?,?,?)',
                        (row['term'],source_ref,source_kind,text[max(0,pos-30):pos+len(matches[0])+70]))
                    if evidence.rowcount:db.execute("UPDATE terms SET uses=uses+1 WHERE term=?",(row["term"],))
            for term in set(re.findall(r"\b[A-Z][A-Z0-9-]{1,15}\b|[ァ-ヶー]{4,24}",text)):
                if term.casefold() not in known:
                    db.execute("INSERT OR IGNORE INTO terms(term,status,uses) VALUES (?,'candidate',1)",(term,))
                    pos=text.find(term)
                    db.execute('INSERT OR IGNORE INTO term_evidence(term,source_ref,source_kind,excerpt) VALUES (?,?,?,?)',
                        (term,source_ref,source_kind,text[max(0,pos-30):pos+len(term)+70]))
        self.expressions.observe(text,source_ref,source_kind)

    def guidance(self, topic, context=""):
        rows = self.list(topic, confirmed=True)
        rows.sort(key=lambda r: (not any(v and v.casefold() in context.casefold() for v in [r["term"],r["ja"],*r["aliases"]]), -r["uses"]))
        return rows[:80]

    def correct(self, topic, original, corrected, translation):
        if max(len(original),len(corrected),len(translation))>8000: raise ValueError("Correction too long")
        with self.connect(topic) as db:
            db.execute("INSERT INTO corrections(original,corrected,translation) VALUES (?,?,?)",(original,corrected,translation))
