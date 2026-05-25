"""Path-sandbox tests: absolute, traversal, symlink, escape."""
from __future__ import annotations

import pytest


def _write(mem, rel, content):
    p = mem / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


class TestSafeResolve:
    def test_relative_inside_root_ok(self, env):
        from lib import safe_resolve
        root = env["vault"] / "myrepo"
        root.mkdir(parents=True, exist_ok=True)
        (root / "decisions").mkdir()
        (root / "decisions" / "a.md").write_text("x")
        out = safe_resolve("decisions/a.md", root)
        assert out.name == "a.md"

    def test_absolute_rejected(self, env):
        from lib import UnsafePathError, safe_resolve
        with pytest.raises(UnsafePathError):
            safe_resolve("/etc/passwd", env["vault"] / "myrepo")

    def test_traversal_rejected(self, env):
        from lib import UnsafePathError, safe_resolve
        root = env["vault"] / "myrepo"
        root.mkdir(parents=True, exist_ok=True)
        with pytest.raises(UnsafePathError):
            safe_resolve("../../../etc/passwd", root)

    def test_traversal_via_segment_rejected(self, env):
        from lib import UnsafePathError, safe_resolve
        root = env["vault"] / "myrepo"
        root.mkdir(parents=True, exist_ok=True)
        with pytest.raises(UnsafePathError):
            safe_resolve("decisions/../../escape.md", root)

    def test_symlink_rejected(self, env, tmp_path):
        from lib import UnsafePathError, safe_resolve
        root = env["vault"] / "myrepo"
        root.mkdir(parents=True, exist_ok=True)
        secret = tmp_path / "secret.md"
        secret.write_text("SECRET")
        # Place a symlink inside the vault pointing OUT of it
        link = root / "decisions"
        link.mkdir()
        (link / "evil.md").symlink_to(secret)
        with pytest.raises(UnsafePathError, match="symlink"):
            safe_resolve("decisions/evil.md", root)

    def test_empty_rejected(self, env):
        from lib import UnsafePathError, safe_resolve
        with pytest.raises(UnsafePathError):
            safe_resolve("", env["vault"] / "myrepo")


class TestMemoryGetSandbox:
    def test_traversal_returns_none(self, initialised_vault):
        import db
        assert db.get_file("../escape.md") is None
        assert db.get_file("/etc/passwd") is None

    def test_symlink_returns_none(self, initialised_vault, tmp_path):
        import db
        secret = tmp_path / "outside.md"
        secret.write_text("OUTSIDE")
        link_path = initialised_vault / "decisions" / "linked.md"
        link_path.parent.mkdir(parents=True, exist_ok=True)
        link_path.symlink_to(secret)
        assert db.get_file("decisions/linked.md") is None

    def test_real_file_works(self, initialised_vault):
        import db
        _write(initialised_vault, "decisions/2026-05-21-foo.md",
               "---\ntitle: Foo\n---\n# Foo\nBody.\n")
        got = db.get_file("decisions/2026-05-21-foo.md")
        assert got is not None
        assert got["title"] == "Foo"


class TestIndexerSkipsSymlinks:
    def test_symlinked_md_not_indexed(self, initialised_vault, tmp_path):
        import db
        secret = tmp_path / "out.md"
        secret.write_text("---\ntitle: Out\n---\nshould-not-be-indexed\n")
        link = initialised_vault / "decisions" / "linked.md"
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(secret)
        # Plus a real file to confirm reindex works
        _write(initialised_vault, "decisions/2026-05-21-real.md",
               "---\ntitle: Real\n---\nreal body\n")
        db.reindex(force=True)
        rows, total = db.search(["should-not-be-indexed"])
        assert rows == []
        assert total == 0
        rows2, _ = db.search(["real"])
        assert any("2026-05-21-real" in r["path"] for r in rows2)
