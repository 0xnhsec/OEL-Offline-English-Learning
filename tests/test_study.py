"""Practice-set parser: questions, options, answer key."""

import unittest

from eng import study

SAMPLE = """
ESSENTIAL ENGLISH GRAMMAR - PRACTICE SET 1
Choose the best answer (A-D).

1. [Subject-verb agreement | easy]
The number of students in the class ___ increasing every year.
   A. is
   B. are
   C. were
   D. have been

2. [FANBOYS | medium]
She did not submit the report, ___ did she answer my email.
   A. or
   B. nor
   C. and
   D. so

3. [TOEFL-style error identification | hard]
The teacher, (A) along with her students, (B) are (C) preparing for the (D) exam.
Which part must be changed?
   A. A: along with
   B. B: her students
   C. C: are
   D. D: exam

==================================================
ANSWER KEY (jangan dilihat sebelum menjawab)
==================================================

1. A
   Why : 'The number of' = singular. HEAD subjek adalah 'number'.
   Trap: 'students' (plural) terlihat tepat sebelum verb.

2. B
   Why : Pada neither...nor, verb cocok dengan subjek TERDEKAT.
   Trap: Orang cenderung pilih 'is'.

3. C
   Why : 'Along with her students' hanyalah interrupter.
   Trap: 'students' plural berada tepat di sebelah verb.
"""


class TestStudyParser(unittest.TestCase):
    def setUp(self):
        self.data = study.parse_practice_set(SAMPLE)

    def test_title(self):
        self.assertIn("PRACTICE SET 1", self.data["title"])

    def test_question_count(self):
        self.assertEqual(self.data["count"], 3)

    def test_question_shape(self):
        q = self.data["questions"][0]
        self.assertEqual(q["n"], 1)
        self.assertEqual(q["topic"], "Subject-verb agreement")
        self.assertEqual(q["difficulty"], "easy")
        self.assertIn("The number of students", q["text"])
        self.assertEqual(q["options"]["A"], "is")
        self.assertEqual(q["options"]["D"], "have been")

    def test_answer_key_merged(self):
        q = self.data["questions"][1]
        self.assertEqual(q["answer"], "B")
        self.assertIn("neither...nor", q["why"])
        self.assertIn("pilih 'is'", q["trap"])
        self.assertTrue(q["answered"])

    def test_multiline_stem(self):
        q = self.data["questions"][2]
        self.assertIn("Which part must be changed?", q["text"])
        self.assertEqual(q["answer"], "C")

    def test_no_key_still_parses(self):
        data = study.parse_practice_set(SAMPLE.split("ANSWER KEY")[0])
        self.assertEqual(data["count"], 3)
        self.assertFalse(data["hasKey"])
        self.assertEqual(data["questions"][0]["answer"], "")


class TestStudyJsonParser(unittest.TestCase):
    SAMPLE = """
    {
      "title": "Essential English Grammar - Practice Set 1",
      "language": "en",
      "total": 2,
      "questions": [
        {
          "id": 1,
          "topic": "Subject-verb agreement",
          "difficulty": "easy",
          "question": "The number of students in the class ___ increasing every year.",
          "options": {"A": "is", "B": "are", "C": "were", "D": "have been"},
          "answer": "A",
          "trap": "'students' plural tepat sebelum verb.",
          "explanation": "'The number of' = singular."
        },
        {
          "id": 2,
          "topic": "FANBOYS",
          "difficulty": "medium",
          "question": "She did not submit the report, ___ did she answer my email.",
          "options": ["or", "nor", "and", "so"],
          "answer": "b",
          "trap": "Pilihan 'or' terasa natural.",
          "explanation": "'Nor' setelah klausa negatif."
        }
      ]
    }
    """

    def setUp(self):
        self.data = study.parse_json_set(self.SAMPLE)

    def test_title_and_count(self):
        self.assertEqual(self.data["title"], "Essential English Grammar - Practice Set 1")
        self.assertEqual(self.data["count"], 2)

    def test_fields_mapped(self):
        q = self.data["questions"][0]
        self.assertEqual(q["n"], 1)
        self.assertEqual(q["topic"], "Subject-verb agreement")
        self.assertEqual(q["difficulty"], "easy")
        self.assertEqual(q["options"]["B"], "are")
        self.assertEqual(q["answer"], "A")
        self.assertIn("The number of", q["why"])
        self.assertIn("plural", q["trap"])

    def test_list_options_and_lowercase_answer(self):
        q = self.data["questions"][1]
        self.assertEqual(q["options"]["B"], "nor")
        self.assertEqual(q["answer"], "B")

    def test_bare_array(self):
        data = study.parse_json_set('[{"question": "Hi ___?", "options": ["a", "b"], "answer": "A"}]')
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["questions"][0]["options"]["B"], "b")


if __name__ == "__main__":
    unittest.main()
