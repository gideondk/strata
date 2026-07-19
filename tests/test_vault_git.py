"""The optional git-backed vault: config resolution, local auto-commit, and
the user-invoked sync guard. All local — no test touches a network remote."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
GIT_SYNC = PLUGIN_ROOT / "scripts" / "git-sync.py"
_STRATA_BIN = PLUGIN_ROOT / "bin" / "strata"


def _lib():
    import lib
    return lib


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True)


def _init_vault_repo(vault):
    _git(vault, "init")
    _git(vault, "config", "user.email", "t@strata.local")
    _git(vault, "config", "user.name", "Test User")


# -- config resolution ------------------------------------------------------


def test_sync_mode_defaults_manual(env, monkeypatch):
    monkeypatch.delenv("STRATA_VAULT_SYNC", raising=False)
    assert _lib().vault_sync_mode() == "manual"


def test_sync_mode_git_via_env_is_case_insensitive(env, monkeypatch):
    monkeypatch.setenv("STRATA_VAULT_SYNC", "GIT")
    assert _lib().vault_sync_mode() == "git"


def test_sync_mode_unknown_value_falls_back_to_manual(env, monkeypatch):
    monkeypatch.setenv("STRATA_VAULT_SYNC", "svn")
    assert _lib().vault_sync_mode() == "manual"


def test_git_remote_reads_env(env, monkeypatch):
    monkeypatch.setenv("STRATA_GIT_REMOTE", "origin")
    assert _lib().git_remote() == "origin"


# -- scaffolding ------------------------------------------------------------


def test_scaffold_creates_ignore_and_attrs(env):
    lib = _lib()
    created = set(lib.scaffold_vault_git_files())
    assert created == {".gitignore", ".gitattributes"}
    gi = (env["vault"] / ".gitignore").read_text()
    assert "INDEX.md" in gi
    assert ".bootstrap-state.json" in gi
    ga = (env["vault"] / ".gitattributes").read_text()
    assert "*.jsonl merge=union" in ga
    # The actual audit log forget appends to is `.audit.log` — no .jsonl
    # suffix, so it needs its own union-merge line or the "audit logs never
    # conflict" guarantee is false for the one file it exists for.
    assert ".audit.log merge=union" in ga


def test_scaffold_is_idempotent(env):
    lib = _lib()
    lib.scaffold_vault_git_files()
    assert lib.scaffold_vault_git_files() == []


# -- local auto-commit ------------------------------------------------------


def test_autocommit_is_noop_in_manual_mode(env, monkeypatch):
    monkeypatch.delenv("STRATA_VAULT_SYNC", raising=False)
    lib = _lib()
    _init_vault_repo(env["vault"])
    f = env["vault"] / "myrepo" / "note.md"
    f.parent.mkdir(parents=True)
    f.write_text("hi\n")
    assert lib.vault_git_autocommit([f], "strata: test") is False


def test_autocommit_is_noop_when_vault_not_git(env, monkeypatch):
    monkeypatch.setenv("STRATA_VAULT_SYNC", "git")
    lib = _lib()
    f = env["vault"] / "note.md"
    f.write_text("hi\n")
    assert lib.vault_git_autocommit([f], "strata: test") is False


def test_autocommit_commits_in_git_mode(env, monkeypatch):
    monkeypatch.setenv("STRATA_VAULT_SYNC", "git")
    lib = _lib()
    _init_vault_repo(env["vault"])
    f = env["vault"] / "myrepo" / "note.md"
    f.parent.mkdir(parents=True)
    f.write_text("body\n")
    assert lib.vault_git_autocommit([f], 'strata: decide "x"') is True
    log = _git(env["vault"], "log", "--oneline")
    assert 'strata: decide "x"' in log.stdout
    st = _git(env["vault"], "status", "--porcelain")
    assert "note.md" not in st.stdout  # committed, working tree clean


def test_autocommit_refuses_path_outside_vault(env, monkeypatch, tmp_path):
    monkeypatch.setenv("STRATA_VAULT_SYNC", "git")
    lib = _lib()
    _init_vault_repo(env["vault"])
    outside = tmp_path / "elsewhere.md"
    outside.write_text("x\n")
    assert lib.vault_git_autocommit([outside], "strata: nope") is False


def test_autocommit_stages_deletion_on_move(env, monkeypatch):
    """forget() moves a file; the commit must stage the source deletion too."""
    monkeypatch.setenv("STRATA_VAULT_SYNC", "git")
    lib = _lib()
    _init_vault_repo(env["vault"])
    src = env["vault"] / "myrepo" / "note.md"
    src.parent.mkdir(parents=True)
    src.write_text("body\n")
    lib.vault_git_autocommit([src], "strata: create")
    dest = env["vault"] / "myrepo" / ".trash" / "moved.md"
    dest.parent.mkdir(parents=True)
    src.rename(dest)
    assert lib.vault_git_autocommit([src, dest], "strata: forget note.md") is True
    st = _git(env["vault"], "status", "--porcelain")
    assert st.stdout.strip() == ""  # move fully committed


# -- sync guard (subprocess; never reaches a network remote) ----------------


def _run_sync(*args):
    return subprocess.run(
        [sys.executable, str(GIT_SYNC), *args],
        capture_output=True, text=True, env=os.environ.copy(),
    )


def test_sync_errors_when_vault_not_git_repo(env, monkeypatch):
    monkeypatch.setenv("STRATA_VAULT_SYNC", "git")
    proc = _run_sync()
    assert proc.returncode == 2
    assert "not a git repo" in (proc.stderr + proc.stdout)


def test_sync_with_no_remote_commits_locally_and_exits_zero(env, monkeypatch):
    monkeypatch.setenv("STRATA_VAULT_SYNC", "git")
    _init_vault_repo(env["vault"])
    (env["vault"] / "seed.md").write_text("seed\n")
    _git(env["vault"], "add", "-A")
    _git(env["vault"], "commit", "-qm", "seed")
    proc = _run_sync()
    assert proc.returncode == 0
    assert "committing locally only" in (proc.stderr + proc.stdout)


def test_sync_first_push_to_empty_remote(env, monkeypatch, tmp_path):
    """A brand-new bare remote has no branch to pull — the first sync must
    fall through to `push -u`, not die on 'couldn't find remote ref'."""
    monkeypatch.setenv("STRATA_VAULT_SYNC", "git")
    monkeypatch.setenv("STRATA_GIT_REMOTE", "origin")
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    _init_vault_repo(env["vault"])
    (env["vault"] / "seed.md").write_text("seed\n")
    _git(env["vault"], "add", "-A")
    _git(env["vault"], "commit", "-qm", "seed")
    _git(env["vault"], "remote", "add", "origin", str(remote))
    proc = _run_sync()
    assert proc.returncode == 0, proc.stderr
    assert "first push" in (proc.stderr + proc.stdout)
    log = subprocess.run(["git", "--git-dir", str(remote), "log", "--oneline"],
                         capture_output=True, text=True)
    assert "seed" in log.stdout  # commit actually reached the remote


# -- end-to-end: real writer scripts auto-commit ------------------------------
# The lib-level tests above pin the helper; these pin the *wiring* — a writer
# script that forgets to call vault_git_autocommit leaves the tree dirty and
# fails here. This is the test that would have caught the domain/archive gaps.


def _run_script(name, *args, stdin=""):
    return subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "scripts" / name), *args],
        input=stdin, capture_output=True, text=True, env=os.environ.copy(),
    )


def test_save_note_autocommits_in_git_mode(env, monkeypatch):
    monkeypatch.setenv("STRATA_VAULT_SYNC", "git")
    _init_vault_repo(env["vault"])
    proc = _run_script("save-note.py", "--topic", "e2e commit check",
                       stdin="Body of the note.\n")
    assert proc.returncode == 0, proc.stderr
    log = _git(env["vault"], "log", "--oneline")
    assert 'strata: save "e2e commit check"' in log.stdout
    st = _git(env["vault"], "status", "--porcelain")
    dirty_md = [line for line in st.stdout.splitlines()
                if line.strip().endswith(".md")
                and "INDEX.md" not in line and "README.md" not in line]
    assert dirty_md == [], f"note left uncommitted: {dirty_md}"


def test_domain_scope_writes_and_autocommits(env, monkeypatch):
    monkeypatch.setenv("STRATA_VAULT_SYNC", "git")
    _init_vault_repo(env["vault"])
    proc = _run_script("save-note.py", "--scope", "domain",
                       "--topic", "Tenant",
                       stdin="# Tenant\n\n## Definition\n\nA paying org.\n")
    assert proc.returncode == 0, proc.stderr
    note = env["vault"] / "myrepo" / "domain" / "tenant.md"
    assert note.exists()
    text = note.read_text()
    assert "title: Tenant" in text
    assert "kind: domain" in text
    log = _git(env["vault"], "log", "--oneline")
    assert 'strata: domain "Tenant"' in log.stdout


def test_domain_scope_refuses_clobber_without_overwrite(env):
    proc = _run_script("save-note.py", "--scope", "domain",
                       "--topic", "Tenant", stdin="v1\n")
    assert proc.returncode == 0, proc.stderr
    proc2 = _run_script("save-note.py", "--scope", "domain",
                        "--topic", "Tenant", stdin="v2\n")
    assert proc2.returncode == 2
    assert "already exists" in proc2.stderr
    note = env["vault"] / "myrepo" / "domain" / "tenant.md"
    assert "v1" in note.read_text()  # original untouched


# -- adversarial-review regressions ------------------------------------------


def test_autocommit_warns_visibly_when_identity_missing(env, monkeypatch):
    """No git identity → commit fails; the failure must reach stderr, not
    vanish — the user otherwise believes the vault is versioned forever."""
    monkeypatch.setenv("STRATA_VAULT_SYNC", "git")
    # Blind git to the developer's real identity: no global/system config,
    # and useConfigOnly turns off user@host auto-detection.
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    lib = _lib()
    _git(env["vault"], "init")
    _git(env["vault"], "config", "user.useConfigOnly", "true")
    f = env["vault"] / "myrepo" / "note.md"
    f.parent.mkdir(parents=True)
    f.write_text("body\n")
    import io
    err = io.StringIO()
    monkeypatch.setattr(sys, "stderr", err)
    assert lib.vault_git_autocommit([f], "strata: x") is False
    assert "NOT committed" in err.getvalue()


def test_init_git_fails_loudly_without_identity(env, monkeypatch, tmp_path):
    """`strata init --git` on an identity-less machine must exit non-zero
    with the fix, not report a healthy setup."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(fake_home / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    # Force identity resolution to fail regardless of host auto-detection.
    (fake_home / "gitconfig").write_text("[user]\n\tuseConfigOnly = true\n")
    proc = _run_script("init-memory.py", "--git")
    assert proc.returncode == 2
    assert "committer identity" in (proc.stderr + proc.stdout)


def test_init_git_refuses_home_directory(env, monkeypatch, tmp_path):
    """vault_path resolving to $HOME must be refused before any git command
    — `git add -A` over a home directory is unrecoverable by design."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("STRATA_VAULT_PATH", str(fake_home))
    proc = _run_script("init-memory.py", "--git")
    assert proc.returncode == 2
    assert "refusing" in (proc.stderr + proc.stdout).lower()
    assert not (fake_home / ".git").exists()


def test_vault_git_pins_english_locale(env, monkeypatch):
    """git-sync branches on English message strings ("couldn't find remote
    ref"); _vault_git must pin LC_ALL=C so a user locale can't break them."""
    captured = {}
    lib = _lib()
    real_run = subprocess.run

    def spy(cmd, **kw):
        captured["env"] = kw.get("env")
        return real_run(cmd, **kw)

    monkeypatch.setattr(subprocess, "run", spy)
    lib._vault_git("--version")
    assert captured["env"] is not None
    assert captured["env"].get("LC_ALL") == "C"


def test_consolidate_commits_the_source_deletion(env, monkeypatch):
    """consolidate --apply must leave a git-mode vault clean: the promoted
    lesson AND the deleted pr-context source belong to the same commit."""
    monkeypatch.setenv("STRATA_VAULT_SYNC", "git")
    _init_vault_repo(env["vault"])
    _lib().scaffold_vault_git_files()  # what `strata init --git` provides
    branch_dir = env["vault"] / "myrepo" / "pr-context" / "feat-old"
    branch_dir.mkdir(parents=True)
    src = branch_dir / "2026-01-01-1200--gd--handoff.md"
    src.write_text("---\nkind: handoff\nsource_file: docs/x.md\n---\n\nBody.\n")
    _git(env["vault"], "add", "-A")
    _git(env["vault"], "commit", "-qm", "seed")
    # Age the branch dir past the 60-day default.
    old = 200 * 86400
    import time as _t
    os.utime(branch_dir, (_t.time() - old, _t.time() - old))
    proc = _run_script("consolidate.py", "--apply")
    assert proc.returncode == 0, proc.stderr
    assert not src.exists()
    st = _git(env["vault"], "status", "--porcelain")
    dirty = [line for line in st.stdout.splitlines()
             if "INDEX.md" not in line]
    assert dirty == [], f"consolidate left the vault dirty: {dirty}"


def test_strata_domain_rejects_contradictory_scope():
    proc = subprocess.run(
        [str(_STRATA_BIN), "domain", "--scope", "lessons", "--topic", "X"],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 2
    assert "implied" in proc.stderr


def test_run_python_survives_newline_in_settings_value(tmp_path, monkeypatch):
    """A settings.json value containing a newline must not abort the wrapper
    (the old eval-based fallback died on an unterminated quote)."""
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    (fake_home / ".claude" / "settings.json").write_text(json.dumps({
        "pluginConfigs": {"strata@strata": {"options": {
            "vault_path": "weird\npath",
            "vault_sync": "git",
        }}}
    }))
    env_ = os.environ.copy()
    env_["HOME"] = str(fake_home)
    for var in ("STRATA_VAULT_PATH", "STRATA_VAULT_SYNC",
                "STRATA_GIT_REMOTE", "STRATA_REPO_NAME",
                "CLAUDE_PLUGIN_OPTION_VAULT_PATH",
                "CLAUDE_PLUGIN_OPTION_VAULT_SYNC"):
        env_.pop(var, None)
    proc = subprocess.run(
        [str(PLUGIN_ROOT / "bin" / "run-python.sh"), "-c",
         "import os; print(os.environ.get('STRATA_VAULT_SYNC',''))"],
        capture_output=True, text=True, env=env_, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    # The rider option was still picked up in the same parse.
    assert "git" in proc.stdout


def test_domain_overwrite_preserves_created_date(env):
    _run_script("save-note.py", "--scope", "domain", "--topic", "Tenant",
                stdin="v1\n")
    note = env["vault"] / "myrepo" / "domain" / "tenant.md"
    # Backdate `created` to prove overwrite reads it rather than restamping.
    note.write_text(re.sub(r"^created: .*$", "created: 2020-01-01",
                           note.read_text(), count=1, flags=re.M))
    proc = _run_script("save-note.py", "--scope", "domain", "--topic",
                       "Tenant", "--overwrite", stdin="v2\n")
    assert proc.returncode == 0, proc.stderr
    text = note.read_text()
    assert "created: 2020-01-01" in text
    assert "v2" in text
