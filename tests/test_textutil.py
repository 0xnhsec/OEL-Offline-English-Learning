"""Unit tests for the text engine (offline, no network, stdlib only)."""

import unittest

from eng import textutil as t


class TestSentenceSplit(unittest.TestCase):
    def test_abbreviations_do_not_split(self):
        text = "Mr. Smith went home. He is here. She called Dr. Who today."
        sents = t.split_sentences(text)
        self.assertEqual(sents, [
            "Mr. Smith went home.",
            "He is here.",
            "She called Dr. Who today.",
        ])

    def test_paragraph_breaks_survive(self):
        sents = t.split_sentences("First paragraph ends here.\n\nSecond one starts here.")
        self.assertEqual(len(sents), 2)
        self.assertTrue(sents[1].startswith("Second"))

    def test_quotes_and_brackets(self):
        sents = t.split_sentences('"Stop!" he said. (Really?) Fine.')
        self.assertEqual(len(sents), 3)


class TestChunking(unittest.TestCase):
    def test_two_sentences_per_chunk(self):
        text = "One two three. Four five six. Seven eight nine. Ten eleven twelve."
        chunks = t.chunk_text(text, max_sentences=2, max_words=100)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(len(chunks[0]["sentences"]), 2)

    def test_word_limit_splits_chunks(self):
        words = " ".join(f"w{i}" for i in range(40))
        chunks = t.chunk_text(words + ".", max_sentences=6, max_words=20)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(c["words"] <= 45 for c in chunks))

    def test_long_sentence_is_broken(self):
        sentence = ", ".join(["clause number one is here"] * 12) + "."
        chunks = t.chunk_text(sentence, max_sentences=2, max_words=30)
        self.assertGreater(len(chunks), 1)

    def test_export_uses_blank_lines(self):
        chunks = t.chunk_text("A b. C d.", max_sentences=1, max_words=50)
        self.assertIn("\n\n", t.chunks_to_text(chunks))

    def test_cleans_rich_text(self):
        cleaned = t.clean_text("Hello\u2014world\r\n\u00a0ok")
        self.assertNotIn("\r", cleaned)
        self.assertNotIn("\u2014", cleaned)


class TestAlignment(unittest.TestCase):
    def test_exact_match(self):
        res = t.align("the cat sat", "the cat sat")
        self.assertEqual(res["stats"]["accuracy"], 1.0)
        self.assertEqual(res["stats"]["missed"], 0)

    def test_missing_and_extra_words(self):
        res = t.align("i want to be a good speaker", "i want be good speaker today")
        s = res["stats"]
        self.assertEqual(s["missed"], 2)      # to, a
        self.assertEqual(s["extra"], 1)       # today
        self.assertEqual(s["ok"], 5)

    def test_punctuation_and_case_ignored(self):
        res = t.align("Hello, world!", "hello world")
        self.assertEqual(res["stats"]["accuracy"], 1.0)

    def test_wrong_word_is_paired(self):
        res = t.align("interested in bugs", "interesting with bugs")
        wrong = [p for p in res["pairs"] if p["status"] == "wrong"]
        self.assertEqual({p["ref"] for p in wrong}, {"interested", "in"})
        self.assertEqual(wrong[0]["hyp"], "interesting")

    def test_empty_hypothesis(self):
        res = t.align("one two three", "")
        self.assertEqual(res["stats"]["heard_words"], 0)
        self.assertEqual(res["stats"]["missed"], 3)


class TestThirdPerson(unittest.TestCase):
    def test_regular(self):
        self.assertEqual(t.third_person("study"), "studies")
        self.assertEqual(t.third_person("watch"), "watches")
        self.assertEqual(t.third_person("go"), "goes")
        self.assertEqual(t.third_person("work"), "works")
        self.assertEqual(t.third_person("have"), "has")
        self.assertEqual(t.third_person("do"), "does")

    def test_base_from_s(self):
        self.assertEqual(t._base_from_s("studies"), "study")
        self.assertEqual(t._base_from_s("watches"), "watch")
        self.assertEqual(t._base_from_s("knows"), "know")
        self.assertEqual(t._base_from_s("goes"), "go")


class TestGrammarRules(unittest.TestCase):
    def check(self, text, expected, rule_id=None):
        res = t.find_grammar_issues(text, limit=12)
        self.assertEqual(res["corrected"], expected,
                         f"got: {res['corrected']}\nissues: {[m['id'] for m in res['matches']]}")
        if rule_id:
            self.assertIn(rule_id, [m["id"] for m in res["matches"]])

    def test_capital_i_and_agreement(self):
        self.check("i am agree with him", "I agree with him", "cap-i")

    def test_subject_verb_agreement(self):
        self.check("she go to campus every day", "She goes to campus every day", "sva-3rd")

    def test_have_to_has(self):
        self.check("he have a car", "He has a car", "sva-3rd")

    def test_negation_base_form(self):
        self.check("they don't knows the rule", "They don't know the rule", "neg-base")

    def test_did_plus_past(self):
        self.check("i didn't went there", "I didn't go there", "did-past")

    def test_uncountable(self):
        self.check("i need some informations", "I need some information", "uncountable")

    def test_preposition_after_adjective(self):
        self.check("he is good on math", "He is good on math")   # 'good' must not be forced
        self.check("she is married with him", "She is married to him", "adj-prep")

    def test_discuss_about(self):
        self.check("we discuss about it", "We discuss it", "about-after-verb")

    def test_correct_text_untouched(self):
        text = "She doesn't know the answer. The data is correct."
        self.check(text, text)

    def test_aux_agreement(self):
        self.check("they doesn't understand", "They don't understand", "aux-agreement")

    def test_number_of(self):
        self.check("The number of students are increasing.",
                   "The number of students is increasing.", "the-number")

    def test_mechanics_reported_once(self):
        res = t.find_grammar_issues("this is fine", limit=5)
        self.assertIn("missing-final", [m["id"] for m in res["matches"]])

    def test_fix_block_shape(self):
        res = t.find_grammar_issues("i am agree", limit=5)
        blocks = t.to_fix_blocks(res["matches"])
        self.assertTrue(blocks)
        for block in blocks:
            self.assertIn("->", block["fix"])
            self.assertTrue(block["why"])
            self.assertTrue(block["try"])


if __name__ == "__main__":
    unittest.main()
