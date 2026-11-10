"""TTS helpers: long text is split safely and reassembled."""

import unittest

from eng import tts


class TestTTSChunking(unittest.TestCase):
    def test_short_text_stays_one_segment(self):
        self.assertEqual(tts._split_for_tts("Hello there."), ["Hello there."])

    def test_long_text_splits_under_limit(self):
        text = " ".join(["This is one practice sentence."] * 40)
        segments = tts._split_for_tts(text, limit=120)
        self.assertGreater(len(segments), 1)
        self.assertTrue(all(len(s) <= 120 for s in segments))
        self.assertEqual(sum(len(s.split()) for s in segments), len(text.split()))

    def test_very_long_sentence_is_split_on_words(self):
        text = "word " * 300
        segments = tts._split_for_tts(text.strip(), limit=100)
        self.assertGreater(len(segments), 1)
        self.assertTrue(all(len(s) <= 100 for s in segments))


if __name__ == "__main__":
    unittest.main()
