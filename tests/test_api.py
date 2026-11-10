"""API smoke tests with FastAPI TestClient (fully offline: local rule engine)."""

import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    TestClient = None

import server
from eng import accounts


SAMPLE = """The number of students are increasing every year.
i am agree with the decision because he have a lot of informations.
"""


@unittest.skipIf(TestClient is None, "fastapi.testclient unavailable")
class TestAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(server.app)
        cls._tmp = tempfile.TemporaryDirectory()
        cls._users_path = accounts.USERS_PATH
        accounts.USERS_PATH = Path(cls._tmp.name) / "users.json"

    @classmethod
    def tearDownClass(cls):
        accounts.USERS_PATH = cls._users_path
        cls._tmp.cleanup()

    def test_health(self):
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["ok"])
        self.assertIn("tts", body)
        self.assertIn("asr", body)
        self.assertIn("ai", body)

    def test_parse_text_into_chunks(self):
        res = self.client.post("/api/parse", json={"text": SAMPLE, "filename": "a.txt",
                                                   "maxSentences": 1, "maxWords": 40})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertGreaterEqual(len(body["chunks"]), 2)
        self.assertEqual(body["stats"]["words"], len(body["text"].split()))

    def test_parse_keeps_short_text_in_one_chunk(self):
        res = self.client.post("/api/parse", json={"text": SAMPLE, "filename": "a.txt",
                                                   "maxSentences": 3, "maxWords": 60})
        self.assertEqual(len(res.json()["chunks"]), 1)

    def test_parse_whole_text_single_chunk(self):
        res = self.client.post("/api/parse", json={"text": SAMPLE, "filename": "a.txt",
                                                   "whole": True})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(len(body["chunks"]), 1)
        self.assertEqual(body["chunks"][0]["words"], body["stats"]["words"])

    def test_upload_file(self):
        res = self.client.post(
            "/api/upload?max_sentences=1&max_words=30",
            files={"file": ("note.txt", SAMPLE.encode(), "text/plain")},
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["filename"], "note.txt")

    def test_parse_rejects_empty(self):
        res = self.client.post("/api/parse", json={"text": "   "})
        self.assertEqual(res.status_code, 400)

    def test_compare_alignment(self):
        res = self.client.post("/api/compare", json={
            "reference": "I am interested in finding bugs",
            "hypothesis": "i am interesting with finding bug",
        })
        self.assertEqual(res.status_code, 200)
        stats = res.json()["stats"]
        self.assertEqual(stats["ref_words"], 6)
        self.assertLess(stats["accuracy"], 1.0)

    def test_analyze_offline_fallback(self):
        res = self.client.post("/api/analyze", json={
            "kind": "grammar", "text": "i am agree with him",
        })
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["engine"], "rule")
        self.assertIn("Fix:", body["reply"])

    def test_analyze_transcript_with_reference(self):
        res = self.client.post("/api/analyze", json={
            "kind": "transcript",
            "reference": "I want to become a good speaker",
            "text": "i want to become good speaker",
        })
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertIn("pengenalan suara", body["reply"])

    def test_settings_roundtrip(self):
        res = self.client.get("/api/settings")
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("apiKey", res.json())   # no cloud key anywhere
        self.assertNotIn("model", res.json())    # no cloud model anywhere

        res = self.client.post("/api/settings", json={"rate": 0.9, "ttsEngine": "auto"})
        self.assertEqual(res.status_code, 200)
        self.assertAlmostEqual(float(res.json()["rate"]), 0.9)
        res = self.client.post("/api/settings", json={"rate": 1.0})
        self.assertAlmostEqual(float(res.json()["rate"]), 1.0)

    def test_index_served(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("English", res.text)

    def test_learn_page_served(self):
        res = self.client.get("/learn")
        self.assertEqual(res.status_code, 200)
        self.assertIn("Learn 101", res.text)

    def test_modules_list(self):
        res = self.client.get("/api/modules")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertGreaterEqual(len(body["modules"]), 9)
        self.assertGreaterEqual(body["total"], 200)

    def test_module_detail(self):
        res = self.client.get("/api/modules/module-06-subject-verb-agreement")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["count"], 25)
        self.assertIn("answer", body["questions"][0])

    def test_auth_login_me_progress(self):
        res = self.client.post("/api/auth/login", json={
            "username": "User1", "password": "WeAreHackerone",
        })
        self.assertEqual(res.status_code, 200)
        token = res.json()["token"]

        me = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["user"]["username"], "User1")

        progress = self.client.post("/api/progress", headers={"Authorization": f"Bearer {token}"},
                                    json={"set": "Module 6: Subject-Verb Agreement",
                                          "correct": 4, "total": 25})
        self.assertEqual(progress.status_code, 200)
        self.assertEqual(progress.json()["user"]["points"], 4)

        board = self.client.get("/api/leaderboard")
        self.assertEqual(board.status_code, 200)
        self.assertGreaterEqual(board.json()["total"], 1)

    def test_auth_bad_login(self):
        res = self.client.post("/api/auth/login", json={"username": "User1", "password": "nope"})
        self.assertEqual(res.status_code, 401)

    def test_progress_requires_token(self):
        res = self.client.post("/api/progress", json={"set": "x", "correct": 1, "total": 2})
        self.assertEqual(res.status_code, 401)


if __name__ == "__main__":
    unittest.main()
