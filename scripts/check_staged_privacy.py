"""Check exactly the staged Git blobs. Never print secret values or matching lines."""
import os
from pathlib import Path
import re
import subprocess
import sys

BLOCKED_DIRS={'data','debug_artifacts','uploads','exports','recordings','backups','.venv','venv','__pycache__','node_modules'}
BLOCKED_SUFFIXES={'.wav','.mp3','.m4a','.aiff','.aif','.pcm','.webm','.mp4','.heic','.heif','.pem','.key','.log'}
PATTERNS={
    'API/token-like secret':re.compile(rb'(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})'),
    'private key':re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    'literal credential':re.compile(rb'''(?i)(?:api[_-]?key|access[_-]?token|secret|password)\s*[=:]\s*['"][A-Za-z0-9_./+=-]{20,}['"]'''),
    'personal filesystem path':re.compile(rb'(?:/(?:Users|home)/|[A-Z]:\\Users\\)[^\s/\\"\']+'),
    'credential in URL':re.compile(rb'https?://[^\s/:]+:[^\s/@]+@'),
}


def blocked_path(name):
    path=Path(name)
    if any(part in BLOCKED_DIRS for part in path.parts):return True
    if path.name.startswith('.env') and path.name!='.env.example':return True
    return (path.suffix.lower() in BLOCKED_SUFFIXES or '.sqlite' in path.name.lower()
            or path.name.endswith(('_REPORT.md','.db','CHECKPOINT.md'))
            or path.name.startswith(('credentials','secrets')))


def findings(name,data,secrets=()):
    results=[]
    if blocked_path(name):results.append('private/generated file must not be staged')
    for label,pattern in PATTERNS.items():
        for match in pattern.finditer(data):
            results.append(f'{label} at line {data[:match.start()].count(bytes([10]))+1}')
    if any(value and value in data for value in secrets):
        results.append('matches a configured local secret (value redacted)')
    if name=='.env.example' and data.strip()!=b'OPENAI_API_KEY=':
        results.append('environment template must contain only an empty API key')
    return results


def configured_secrets(root):
    values=dict(os.environ)
    # Read only to compare; neither names nor values are printed or sent anywhere.
    for path in root.glob('.env*'):
        if not path.is_file() or path.name=='.env.example':continue
        for line in path.read_text(errors='replace').splitlines():
            key,sep,value=line.removeprefix('export ').partition('=')
            if sep:values[key.strip()]=value.strip().strip('\"\'')
    return [value.encode() for key,value in values.items()
            if re.search(r'(KEY|TOKEN|SECRET|PASSWORD)$',key,re.I) and len(value)>=12]


def git(*args):
    return subprocess.check_output(['git',*args])


def main():
    root=Path(git('rev-parse','--show-toplevel').decode().strip())
    names=[name.decode() for name in git('diff','--cached','--name-only','--diff-filter=ACMR','-z').split(b'\0') if name]
    secrets=configured_secrets(root);problems=0
    for name in names:
        issues=findings(name,git('show',f':{name}'),secrets)
        for issue in issues:
            print(f'BLOCKED: {name}: {issue}')
            problems+=1
    if problems:
        print(f'FAIL: {problems} findings; no secret values printed.');return 1
    print(f'PASS: checked {len(names)} staged files; no configured secrets or blocked data detected.')
    return 0


if __name__=='__main__':
    sys.exit(main())
