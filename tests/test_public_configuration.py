"""Public documentation must not embed a real account-provider tenant or credentials."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FILES = (
    ".env.example",
    "README.md",
    "js/accounts.js",
    "server/accounts.py",
)


class PublicConfigurationTests(unittest.TestCase):
    def test_public_files_have_no_real_supabase_project_reference(self):
        project_url = re.compile(r"https://([a-z0-9-]+)\.supabase\.co", re.IGNORECASE)
        allowed_examples = {"your-project-ref", "project-ref"}
        for relative in PUBLIC_FILES:
            with self.subTest(file=relative):
                content = (ROOT / relative).read_text(encoding="utf-8")
                refs = {match.group(1).lower() for match in project_url.finditer(content)}
                self.assertFalse(refs - allowed_examples, "Remove tenant-specific URLs from public files")

    def test_account_provider_requires_explicit_configuration(self):
        server = (ROOT / "server/accounts.py").read_text(encoding="utf-8")
        self.assertNotIn("DEFAULT_PROJECT", server)
        self.assertIn('os.getenv("SUPABASE_URL", "")', server)
        self.assertIn("if not project or not publishable", server)


if __name__ == "__main__":
    unittest.main()
