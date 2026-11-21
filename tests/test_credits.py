import unittest
from pathlib import Path

from streamstudy.credits import ABOUT_TEXT, IMPLEMENTATION_MODEL, MODEL_ID

ROOT = Path(__file__).resolve().parent.parent


class CreditsTest(unittest.TestCase):
    def test_names_the_model(self):
        self.assertEqual(IMPLEMENTATION_MODEL, "DeepSeek V4.1 Flash")
        self.assertEqual(MODEL_ID, "deepseek-ai/DeepSeek-V4.1-Flash")
        self.assertIn("DeepSeek V4.1 Flash", ABOUT_TEXT)

    def test_states_the_roles(self):
        self.assertIn("Human-prompted", ABOUT_TEXT)
        self.assertIn("LLM-implemented", ABOUT_TEXT)
        self.assertIn("LM Studio Bionic", ABOUT_TEXT)

    def test_experimental_warning(self):
        self.assertIn("experimental", ABOUT_TEXT.lower())
        self.assertIn("Not for flood safety", ABOUT_TEXT)

    def test_repo_documents_attribution(self):
        readme = (ROOT / "README.md").read_text()
        credits = (ROOT / "CREDITS.md").read_text()
        for document in (readme, credits):
            self.assertIn("DeepSeek V4.1 Flash", document)
        self.assertIn("Human-prompted, LLM-implemented", readme)


if __name__ == "__main__":
    unittest.main()
