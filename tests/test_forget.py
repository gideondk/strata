"""Tests for forget: move-to-trash + audit log."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FORGET = HERE.parent / "scripts" / "forget.py"


def _run(*args, env=None):
    return subprocess.run(
        [sys.executable, str(FORGET), *args],
        capture_output=True, text=True, check=False,
        env=env,
    )


def _write(mem, rel, content):
    p = mem / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def test_forget_moves_file_and_writes_audit(initialised_vault):
    import os
    mem = initialised_vault
    target = _write(mem, "decisions/2026-05-20-bad.md",
                    "---\ntitle: Bad\n---\nsensitive content\n")
    r = _run(
        "--path", "decisions/2026-05-20-bad.md",
        "--reason", "test forget",
        env=os.environ.copy(),
    )
    assert r.returncode == 0, r.stderr
    assert not target.exists()

    trash = list((mem / ".trash").glob("*decisions__2026-05-20-bad.md"))
    assert len(trash) == 1

    audit_log = mem / ".audit.log"
    assert audit_log.exists()
    line = audit_log.read_text().strip()
    entry = json.loads(line)
    assert entry["action"] == "forget"
    assert entry["src"] == "decisions/2026-05-20-bad.md"
    assert entry["reason"] == "test forget"
    assert "sha256" in entry
    assert entry["size"] > 0


def test_forget_dry_run_does_not_move(initialised_vault):
    import os
    mem = initialised_vault
    target = _write(mem, "decisions/2026-05-20-keep.md",
                    "---\ntitle: Keep\n---\n")
    r = _run(
        "--path", "decisions/2026-05-20-keep.md",
        "--reason", "preview",
        "--dry-run",
        env=os.environ.copy(),
    )
    assert r.returncode == 0
    assert target.exists()
    assert not (mem / ".audit.log").exists()


def test_forget_refuses_traversal(initialised_vault):
    import os
    r = _run(
        "--path", "../../../etc/passwd",
        "--reason", "evil",
        env=os.environ.copy(),
    )
    assert r.returncode == 2
    assert "traversal" in r.stderr or "absolute" in r.stderr or "escapes" in r.stderr


def test_forget_refuses_symlink(initialised_vault, tmp_path):
    import os
    mem = initialised_vault
    secret = tmp_path / "outside.md"
    secret.write_text("OUTSIDE")
    link_path = mem / "decisions" / "linked.md"
    link_path.parent.mkdir(parents=True, exist_ok=True)
    link_path.symlink_to(secret)
    r = _run(
        "--path", "decisions/linked.md",
        "--reason", "test",
        env=os.environ.copy(),
    )
    assert r.returncode == 2
    assert "symlink" in r.stderr


def test_forget_requires_reason(initialised_vault):
    import os
    mem = initialised_vault
    _write(mem, "decisions/2026-05-20-x.md", "---\ntitle: X\n---\n")
    r = _run(
        "--path", "decisions/2026-05-20-x.md",
        "--reason", "   ",  # whitespace only
        env=os.environ.copy(),
    )
    assert r.returncode == 2


def test_forget_appends_to_audit(initialised_vault):
    """Two forgets → two audit lines."""
    import os
    mem = initialised_vault
    _write(mem, "decisions/2026-05-20-a.md", "---\ntitle: A\n---\n")
    _write(mem, "decisions/2026-05-20-b.md", "---\ntitle: B\n---\n")
    for name in ("a", "b"):
        r = _run(
            "--path", f"decisions/2026-05-20-{name}.md",
            "--reason", f"forget {name}",
            env=os.environ.copy(),
        )
        assert r.returncode == 0, r.stderr
    lines = (mem / ".audit.log").read_text().strip().splitlines()
    assert len(lines) == 2
    entries = [json.loads(line) for line in lines]
    assert entries[0]["src"].endswith("a.md")
    assert entries[1]["src"].endswith("b.md")
