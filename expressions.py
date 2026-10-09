"""Auditable expression meanings; manual attribution, never voice identification."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3


class Expressions:
    def __init__(self, path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS expressions (
              phrase TEXT PRIMARY KEY, zh TEXT NOT NULL, usage_note TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'candidate', updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS evidence (
              id TEXT PRIMARY KEY, phrase TEXT NOT NULL, source_ref TEXT NOT NULL,
              source_kind TEXT NOT NULL, excerpt TEXT NOT NULL,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS profiles (
              name TEXT PRIMARY KEY, note TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS attributions (
              phrase TEXT NOT NULL, person TEXT NOT NULL, confirmation TEXT NOT NULL,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(phrase,person));
            CREATE TABLE IF NOT EXISTS revisions (
              id INTEGER PRIMARY KEY, phrase TEXT, before_json TEXT, after_json TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            ''')
        self.path.parent.chmod(0o700)
        self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=5);db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()

    def save(self,phrase,zh,usage_note,status='candidate'):
        if status not in {'confirmed','candidate','archived'}:raise ValueError('Invalid status')
        if not phrase.strip() or not zh.strip() or any(len(v)>500 or any(c in v for c in '\r\n<>') for v in (phrase,zh,usage_note)):
            raise ValueError('Invalid expression')
        data=dict(phrase=phrase.strip(),zh=zh.strip(),usage_note=usage_note.strip(),status=status)
        with self.connect() as db:
            old=db.execute('SELECT * FROM expressions WHERE phrase=?',(data['phrase'],)).fetchone()
            if old and all(old[k]==v for k,v in data.items()):return
            db.execute('''INSERT INTO expressions(phrase,zh,usage_note,status) VALUES (:phrase,:zh,:usage_note,:status)
              ON CONFLICT(phrase) DO UPDATE SET zh=excluded.zh,usage_note=excluded.usage_note,
              status=excluded.status,updated_at=CURRENT_TIMESTAMP''',data)
            db.execute('INSERT INTO revisions(phrase,before_json,after_json) VALUES (?,?,?)',
                       (data['phrase'],json.dumps(dict(old),ensure_ascii=False) if old else None,json.dumps(data,ensure_ascii=False)))

    def list(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute('''SELECT e.*,
              (SELECT count(*) FROM evidence v WHERE v.phrase=e.phrase) AS evidence_count
              FROM expressions e ORDER BY phrase''')]

    def observe(self,text,source_ref,source_kind='asr'):
        with self.connect() as db:
            for row in db.execute('SELECT phrase FROM expressions').fetchall():
                phrase=row['phrase'];position=text.find(phrase)
                if position<0:continue
                excerpt=text[max(0,position-35):position+len(phrase)+65]
                key=hashlib.sha256((source_ref+'\0'+phrase).encode()).hexdigest()
                db.execute('INSERT OR IGNORE INTO evidence(id,phrase,source_ref,source_kind,excerpt) VALUES (?,?,?,?,?)',
                           (key,phrase,source_ref,source_kind,excerpt))

    def request_profile(self,name):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO profiles(name,note) VALUES (?,?)',
                       (name,'等待用户确认具体表达的归属；不从音色、姓名提及或通用口头语推断个人习惯。'))

    def confirm_attribution(self,phrase,person,confirmation):
        if not confirmation.strip():raise ValueError('需要明确的用户归属确认')
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM expressions WHERE phrase=?',(phrase,)).fetchone():raise ValueError('Unknown expression')
            # Attribution is an explicit manual action; never called by observe().
            old=db.execute('SELECT * FROM attributions WHERE phrase=? AND person=?',(phrase,person)).fetchone()
            db.execute('INSERT OR REPLACE INTO attributions(phrase,person,confirmation) VALUES (?,?,?)',
                       (phrase,person,confirmation[:1000]))
            db.execute('INSERT INTO revisions(phrase,before_json,after_json) VALUES (?,?,?)',
                (phrase,json.dumps(dict(old),ensure_ascii=False) if old else None,
                 json.dumps({'kind':'manual_attribution','person':person,'confirmation':confirmation[:1000]},ensure_ascii=False)))

    def guidance(self,text):
        # Only matched, reviewed lexical meanings are sent, not past quotes/names.
        return [{k:row[k] for k in ('phrase','zh','usage_note')} for row in self.list()
                if row['status']=='confirmed' and row['phrase'] in text][:8]
