#!/usr/bin/env python3
"""Tests for scripts/server.py -- specifically the path-traversal guard.

Everything the memory-edit server writes to disk goes through
safe_memory_path() first. It was manually verified with curl during
development (traversal and out-of-tree paths both 400'd); this locks that
behavior in so a future refactor can't quietly loosen it.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import server  # noqa: E402


class TestSafeMemoryPath(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        (self.root / "proj1" / "memory").mkdir(parents=True)
        (self.root / "proj1" / "memory" / "note.md").write_text("hi", encoding="utf-8")
        # Patch the module-level root rather than the real home directory.
        self._orig_root = server.MEMORY_ROOT
        server.MEMORY_ROOT = self.root
        self.addCleanup(lambda: setattr(server, "MEMORY_ROOT", self._orig_root))

    def test_accepts_valid_memory_path(self):
        p = server.safe_memory_path(str(self.root / "proj1" / "memory" / "note.md"))
        self.assertEqual(p.name, "note.md")

    def test_rejects_non_md_extension(self):
        with self.assertRaises(ValueError):
            server.safe_memory_path(str(self.root / "proj1" / "memory" / "note.txt"))

    def test_rejects_traversal_outside_root(self):
        with self.assertRaises(ValueError):
            server.safe_memory_path(str(self.root / "proj1" / "memory" / ".." / ".." / ".." / "etc" / "passwd.md"))

    def test_rejects_absolute_path_outside_root_entirely(self):
        with self.assertRaises(ValueError):
            server.safe_memory_path("/etc/passwd.md")

    def test_rejects_path_inside_project_but_outside_memory_dir(self):
        (self.root / "proj1" / "notmemory.md").write_text("x", encoding="utf-8")
        with self.assertRaises(ValueError):
            server.safe_memory_path(str(self.root / "proj1" / "notmemory.md"))

    def test_rejects_project_root_itself(self):
        with self.assertRaises(ValueError):
            server.safe_memory_path(str(self.root / "proj1.md"))

    def test_symlink_escape_is_rejected(self):
        # A symlink inside memory/ pointing outside the root must not let a
        # write escape, since resolve() follows it before the containment check.
        target = Path(self._tmp.name).parent / "outside.md"
        target.write_text("secret", encoding="utf-8")
        link = self.root / "proj1" / "memory" / "escape.md"
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("symlinks not supported in this environment")
        with self.assertRaises(ValueError):
            server.safe_memory_path(str(link))


if __name__ == "__main__":
    unittest.main()
