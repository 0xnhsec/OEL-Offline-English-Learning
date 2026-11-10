"""Local accounts: register, login, progress, leaderboard."""

import tempfile
import unittest
from pathlib import Path

from eng import accounts


class TestAccounts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = accounts.USERS_PATH
        accounts.USERS_PATH = Path(self.tmp.name) / "users.json"

    def tearDown(self):
        accounts.USERS_PATH = self._old
        self.tmp.cleanup()

    def test_default_user_login(self):
        result = accounts.login("User1", "WeAreHackerone")
        self.assertIn("token", result)
        self.assertEqual(result["user"]["username"], "User1")
        self.assertNotIn("hash", result["user"])

    def test_wrong_password(self):
        with self.assertRaises(ValueError):
            accounts.login("User1", "wrong")

    def test_register_and_login(self):
        created = accounts.register("newuser", "New User", "secret123")
        self.assertEqual(created["user"]["name"], "New User")
        again = accounts.login("NewUser", "secret123")
        self.assertEqual(again["user"]["username"], "newuser")
        self.assertIn("token", again)

    def test_duplicate_username(self):
        accounts.register("taken", "Taken", "secret123")
        with self.assertRaises(ValueError):
            accounts.register("TAKEN", "Other", "secret123")

    def test_short_password(self):
        with self.assertRaises(ValueError):
            accounts.register("shorty", "Short", "123")

    def test_progress_keeps_best(self):
        result = accounts.register("player", "Player", "secret123")
        token = result["token"]
        first = accounts.record_progress(token, "Set A", 3, 10)
        self.assertEqual(first["points"], 3)
        second = accounts.record_progress(token, "Set A", 2, 10)
        self.assertEqual(second["points"], 3)   # never downgrade
        third = accounts.record_progress(token, "Set A", 7, 10)
        self.assertEqual(third["points"], 7)
        self.assertEqual(third["sets"], 1)

    def test_leaderboard_order(self):
        low = accounts.register("lowscore", "Low", "secret123")["token"]
        high = accounts.register("highscore", "High", "secret123")["token"]
        accounts.record_progress(low, "Set", 2, 10)
        accounts.record_progress(high, "Set", 9, 10)
        board = accounts.leaderboard()
        self.assertEqual(board["entries"][0]["name"], "High")
        ranks = [row["rank"] for row in board["entries"]]
        self.assertEqual(ranks, sorted(ranks))

    def test_token_logout(self):
        token = accounts.login("User1", "WeAreHackerone")["token"]
        self.assertIsNotNone(accounts.user_for_token(token))
        accounts.logout(token)
        self.assertIsNone(accounts.user_for_token(token))


if __name__ == "__main__":
    unittest.main()
