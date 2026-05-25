"""Structural tests for plugin-shipped subagents.

We don't run the agents end-to-end here — that needs the full Claude Code
runtime. We do verify the manifest is well-formed: the frontmatter has
the fields Claude Code expects, the name uses the strata: scope, and
the tool list is restricted to what the worker actually needs.
"""
from __future__ import annotations

from pathlib import Path

import frontmatter

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = PLUGIN_ROOT / "agents"


def test_agents_dir_exists():
    assert AGENTS_DIR.is_dir(), "plugin must ship an agents/ directory"


def test_bootstrap_worker_present():
    p = AGENTS_DIR / "bootstrap-worker.md"
    assert p.is_file(), "bootstrap-worker.md must exist"


def test_bootstrap_worker_frontmatter_complete():
    p = AGENTS_DIR / "bootstrap-worker.md"
    post = frontmatter.load(p)
    md = post.metadata
    # Required fields per Claude Code subagent schema
    for field in ("name", "description", "model", "tools"):
        assert field in md, f"missing required field: {field}"


def test_bootstrap_worker_name_scoped():
    p = AGENTS_DIR / "bootstrap-worker.md"
    post = frontmatter.load(p)
    name = post.metadata["name"]
    assert name == "strata:bootstrap-worker", (
        f"agent name must be 'strata:bootstrap-worker', got {name!r}"
    )


def test_bootstrap_worker_tools_restricted():
    """The worker should NOT have access to Agent (no recursive spawning),
    WebSearch / WebFetch (no network), or Edit (writes go through scripts
    or Write whole-file). Read+Write+Bash+Glob+Grep is the working set."""
    p = AGENTS_DIR / "bootstrap-worker.md"
    post = frontmatter.load(p)
    tools = post.metadata["tools"]
    # tools is a comma-separated string in YAML; normalise
    if isinstance(tools, str):
        tool_set = {t.strip() for t in tools.split(",")}
    else:
        tool_set = set(tools)

    forbidden = {"Agent", "WebSearch", "WebFetch", "Edit", "NotebookEdit"}
    overlap = tool_set & forbidden
    assert not overlap, f"worker has forbidden tools: {overlap}"

    # Must have at least these
    required = {"Read", "Bash"}
    missing = required - tool_set
    assert not missing, f"worker missing required tools: {missing}"


def test_bootstrap_worker_model_pinned():
    """We pin Sonnet — Haiku risks misclassification on borderline
    domain/decide calls. If we ever want to override, do it explicitly."""
    p = AGENTS_DIR / "bootstrap-worker.md"
    post = frontmatter.load(p)
    model = post.metadata["model"]
    assert "sonnet" in model.lower(), (
        f"worker should run on Sonnet for classification quality, got {model!r}"
    )


def test_bootstrap_worker_body_documents_procedure():
    """The body of the agent file is the system prompt. It must spell
    out the four classifications and the one-line return format, or the
    parent can't aggregate results correctly."""
    p = AGENTS_DIR / "bootstrap-worker.md"
    post = frontmatter.load(p)
    body = post.content
    for marker in ("domain", "decide", "save", "skip", "DOMAIN", "ERROR"):
        assert marker in body, f"worker prompt missing reference to: {marker}"
