import unittest
from pathlib import Path
from scripts.check_staged_privacy import blocked_path, findings


class PrivacyTests(unittest.TestCase):
    def test_sensitive_paths_rejected(self):
        for name in ('.env','.env.local','data/glossaries/indoor.sqlite3','debug_artifacts/a.json',
                     'meeting.wav','photo.HEIC','LIVE_DEBUG_REPORT.md','credentials.json'):
            self.assertTrue(blocked_path(name),name)
        self.assertFalse(blocked_path('.env.example'))
        self.assertFalse(blocked_path('meeting.py'))

    def test_values_are_detected_without_exposure(self):
        secret=b'sk-'+b'z'*35
        result=findings('example.py',b'const value = "'+secret+b'"',[secret])
        self.assertGreaterEqual(len(result),2)
        self.assertNotIn(secret.decode(),str(result))
        self.assertFalse(findings('.env.example',b'OPENAI_API_KEY=\n'))
        self.assertTrue(findings('.env.example',b'OPENAI_API_KEY=not-empty\n'))

    def test_personal_paths_detected(self):
        for prefix in (b'/' + b'Users/', b'/' + b'home/', b'C:' + bytes([92]) + b'Users' + bytes([92])):
            self.assertTrue(findings('example.py',prefix+b'example_user'))

    def test_scanner_does_not_flag_its_own_patterns(self):
        root=Path(__file__).resolve().parent
        self.assertFalse(findings('scripts/check_staged_privacy.py',
                                  (root/'scripts/check_staged_privacy.py').read_bytes()))


if __name__=='__main__':unittest.main()
