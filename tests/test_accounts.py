"""Local accounts: register, login, progress, leaderboard."""

import tempfile
import unittest
from pathlib import Path

from eng import accounts


class TestAccounts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = accounts.USERS_PATH
        self._old_avatars = accounts.AVATAR_DIR
        accounts.USERS_PATH = Path(self.tmp.name) / "users.json"
        accounts.AVATAR_DIR = Path(self.tmp.name) / "avatars"

    def tearDown(self):
        accounts.USERS_PATH = self._old
        accounts.AVATAR_DIR = self._old_avatars
        self.tmp.cleanup()

    def test_default_user_login(self):
        result = accounts.login("user", "user")
        self.assertIn("token", result)
        self.assertEqual(result["user"]["username"], "user")
        self.assertNotIn("hash", result["user"])

    def test_wrong_password(self):
        with self.assertRaises(ValueError):
            accounts.login("user", "wrong")

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
        names = [row["name"] for row in board["entries"]]
        self.assertEqual(names[0], "Noshiro")        # legend dipin di rank 1
        self.assertEqual(names[1], "High")
        ranks = [row["rank"] for row in board["entries"]]
        self.assertEqual(ranks, sorted(ranks))

    def test_legend_entry_locked(self):
        board = accounts.leaderboard()
        legend = board["entries"][0]
        self.assertTrue(legend["featured"])
        self.assertEqual(legend["avatar"], "/static/assets/ayang.png")
        self.assertEqual(legend["bio"]["Name"], "Ayanagi Noshiro (noun)")
        self.assertEqual(legend["bio"]["Gender"], "She")
        self.assertEqual(legend["bio"]["Address"], "Akita, Japan.")
        with self.assertRaises(ValueError):
            accounts.login("noshiro", "noshiro")

    def test_avatar_upload_and_clear(self):
        token = accounts.login("user", "user")["token"]
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
        user = accounts.set_avatar(token, png)
        self.assertTrue(user["avatar"].startswith("/avatars/user.png"))
        self.assertTrue((accounts.AVATAR_DIR / "user.png").is_file())
        cleared = accounts.clear_avatar(token)
        self.assertEqual(cleared["avatar"], "")
        self.assertFalse((accounts.AVATAR_DIR / "user.png").is_file())
        with self.assertRaises(ValueError):
            accounts.set_avatar(token, b"not-an-image")

    def test_token_logout(self):
        token = accounts.login("user", "user")["token"]
        self.assertIsNotNone(accounts.user_for_token(token))
        accounts.logout(token)
        self.assertIsNone(accounts.user_for_token(token))


if __name__ == "__main__":
    unittest.main()
