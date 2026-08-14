#!/usr/bin/env python3
"""Tests for scripts/inspect_env.py -- stdlib unittest only.

The secret scanner is the security-sensitive surface here: a false negative
leaves a real credential unflagged, and a false positive (or worse, echoing
back the matched text) would undermine the "never displays the value" claim
this feature is built on. Both directions are tested.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import inspect_env  # noqa: E402


class TestSecretScanner(unittest.TestCase):
    def _names(self, text):
        return {f["pattern"] for f in inspect_env.scan_secrets(text, "test.md")}

    def test_catches_anthropic_key(self):
        self.assertIn("Anthropic API Key",
                      self._names('key = "sk-ant-abcdefghijklmnopqrstuvwx"'))

    def test_catches_aws_access_key(self):
        self.assertIn("AWS Access Key", self._names("AWS_KEY=AKIAABCDEFGHIJKLMNOP"))

    def test_catches_github_token(self):
        self.assertIn("GitHub Token", self._names("ghp_" + "a" * 36))

    def test_catches_gitlab_token(self):
        self.assertIn("GitLab Token", self._names("glpat-" + "a" * 20))

    def test_catches_slack_token(self):
        self.assertIn("Slack Token", self._names("xoxb-1234567890-abcdefghij"))

    def test_catches_private_key_block(self):
        self.assertIn("Private Key Block", self._names("-----BEGIN RSA PRIVATE KEY-----"))

    def test_catches_generic_secret_assignment(self):
        self.assertIn("Generic secret assignment",
                      self._names('api_key: "abcdefghijklmnop1234"'))

    def test_no_false_positive_on_ordinary_prose(self):
        prose = (
            "This project uses an API key stored in the environment. "
            "The deploy token is rotated monthly by the CI pipeline. "
            "See the auth docs for how secrets are managed."
        )
        self.assertEqual(self._names(prose), set())

    def test_no_false_positive_on_short_values(self):
        # Short enough that it shouldn't match the generic 16+ char pattern.
        self.assertEqual(self._names('token: "abc123"'), set())

    def test_never_returns_the_matched_text(self):
        """The contract this feature is built on: only location + pattern
        name are returned, never a slice of the matched string."""
        secret = "sk-ant-thisIsAFakeSecretValue123456"
        findings = inspect_env.scan_secrets(f'key = "{secret}"', "test.md")
        self.assertTrue(findings)
        for f in findings:
            self.assertEqual(set(f.keys()), {"location", "line", "pattern"})
            for v in f.values():
                self.assertNotIn(secret, str(v))

    def test_line_number_is_correct(self):
        text = "line one\nline two\nAKIAABCDEFGHIJKLMNOP\nline four"
        findings = inspect_env.scan_secrets(text, "test.md")
        self.assertEqual(findings[0]["line"], 3)

    def test_real_memory_files_produce_no_false_positives(self):
        """Regression check against this repo's own actual memory files, if
        any exist on the machine running the tests. Skips cleanly in CI or
        on a machine with no ~/.claude/projects history."""
        root = Path.home() / ".claude" / "projects"
        if not root.is_dir():
            self.skipTest("no ~/.claude/projects on this machine")
        d = inspect_env.collect_memories(root)
        flagged = d["secret_flags"]
        if flagged:
            self.fail(f"{len(flagged)} secret-like pattern(s) found in real memory "
                     f"files -- review manually (locations only, no values): {flagged}")


class TestRedact(unittest.TestCase):
    def test_secret_hinted_key_is_redacted(self):
        out = inspect_env.redact("sk-ant-realvalue", name="api_key")
        self.assertNotIn("realvalue", out)
        self.assertTrue(out.startswith("<set,"))

    def test_long_value_is_redacted_regardless_of_key_name(self):
        out = inspect_env.redact("x" * 60, name="unrelated_field")
        self.assertNotIn("x" * 60, out)

    def test_short_non_secret_value_passes_through(self):
        self.assertEqual(inspect_env.redact("staging", name="environment"), "staging")


class TestMemoryParsing(unittest.TestCase):
    def test_frontmatter_and_links_extracted(self, tmp_path=None):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "note.md"
            p.write_text(
                "---\nname: note\ndescription: a test memory\n---\n"
                "Body text referencing [[other-note]] and [[missing-note]].",
                encoding="utf-8",
            )
            parsed = inspect_env.parse_memory(p)
            self.assertEqual(parsed["name"], "note")
            self.assertEqual(parsed["description"], "a test memory")
            self.assertEqual(set(parsed["links"]), {"other-note", "missing-note"})

    def test_dangling_links_detected_across_a_project(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            mem = root / "proj1" / "memory"
            mem.mkdir(parents=True)
            (mem / "a.md").write_text("---\nname: a\n---\nlinks to [[b]] and [[nonexistent]]",
                                      encoding="utf-8")
            (mem / "b.md").write_text("---\nname: b\n---\nnothing special", encoding="utf-8")
            result = inspect_env.collect_memories(root)
            self.assertEqual(result["total"], 2)
            targets = {o["to"] for o in result["dangling_links"]}
            self.assertIn("nonexistent", targets)
            self.assertNotIn("b", targets)  # b.md exists, so a->b is not dangling


if __name__ == "__main__":
    unittest.main()
