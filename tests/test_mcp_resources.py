"""Tests for the MCP resources surface — list + read with sandbox check."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def _write(mem, rel, content):
    p = mem / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


async def _mcp_call(env_vars: dict, fn):
    """Spin up the MCP server as a subprocess, run `fn(session)`, close."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=str(PLUGIN_ROOT / "bin" / "run-python.sh"),
        args=[str(PLUGIN_ROOT / "mcp" / "server.py")],
        env={**os.environ, **env_vars},
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        return await fn(session)


def test_resources_list_returns_indexed_files(initialised_vault):
    mem = initialised_vault
    _write(mem, "decisions/2026-05-21-foo.md",
           "---\ntitle: Foo\nstatus: accepted\n---\nBody.\n")
    _write(mem, "domain/term.md",
           "---\ntitle: Term\n---\nDefinition.\n")

    async def run(session):
        return await session.list_resources()

    result = asyncio.run(_mcp_call({}, run))
    uris = [str(r.uri) for r in result.resources]
    assert any("strata://decisions/2026-05-21-foo.md" in u for u in uris)
    assert any("strata://domain/term.md" in u for u in uris)


def test_resource_read_serves_body(initialised_vault):
    mem = initialised_vault
    _write(mem, "decisions/2026-05-21-foo.md",
           "---\ntitle: Foo\n---\n# Foo\nThis is the body.\n")

    async def run(session):
        return await session.read_resource(
            "strata://decisions/2026-05-21-foo.md"
        )

    result = asyncio.run(_mcp_call({}, run))
    text = result.contents[0].text
    assert "This is the body" in text


def test_resource_read_rejects_traversal(initialised_vault):
    async def run(session):
        return await session.read_resource(
            "strata://../../escape.md"
        )

    result = asyncio.run(_mcp_call({}, run))
    text = result.contents[0].text
    assert "error" in text.lower() or "not found" in text.lower() \
        or "refused" in text.lower()


def test_bootstrap_scan_tool_returns_candidates(initialised_vault, env):
    """The bootstrap_scan MCP tool wraps scripts/bootstrap-scan.py and
    returns its markdown report — keeps the skill UI clean by hiding
    the long python invocation."""
    pd = env["repo"]
    (pd / "docs").mkdir()
    (pd / "docs" / "design.md").write_text("# design\n")
    (pd / "ARCHITECTURE.md").write_text("# arch\n")

    async def run(session):
        return await session.call_tool(
            "bootstrap_scan",
            {"unprocessed": True, "verify": False},
        )

    result = asyncio.run(_mcp_call({}, run))
    text = result.content[0].text
    assert "Strata bootstrap candidates" in text
    assert "ARCHITECTURE.md" in text
    assert "docs/design.md" in text or "docs/" in text


# --- prompts surface -------------------------------------------------------

def test_prompts_list_advertises_the_three(initialised_vault):
    async def run(session):
        return await session.list_prompts()

    result = asyncio.run(_mcp_call({}, run))
    names = {p.name for p in result.prompts}
    assert {"recall-pack", "decision-brief", "pr-onboard"} <= names


def test_get_prompt_recall_pack_preloads_matching_note(initialised_vault):
    mem = initialised_vault
    _write(mem, "decisions/2026-05-21-rate-limit.md",
           "---\ntitle: Token bucket rate limiting\nstatus: accepted\n---\n"
           "We use a token bucket for rate limiting.\n")

    async def run(session):
        return await session.get_prompt("recall-pack",
                                        {"topic": "rate limiting"})

    result = asyncio.run(_mcp_call({}, run))
    msg = result.messages[0]
    assert msg.role == "user"
    text = msg.content.text
    # Assert on the note's PATH (only the recall output produces it) — the
    # topic string alone is echoed by the template, so it can't prove recall ran.
    assert "rate-limit" in text
    assert "recall error" not in text and "no relevant" not in text


def test_get_prompt_decision_brief_scopes_to_decisions(initialised_vault):
    mem = initialised_vault
    _write(mem, "decisions/2026-05-22-widget-eviction.md",
           "---\ntitle: Widget eviction\nstatus: accepted\n---\nEvict widgets.\n")
    _write(mem, "domain/2026-05-22-widget-glossary.md",
           "---\ntitle: Widget glossary\n---\nWidget definitions.\n")

    async def run(session):
        return await session.get_prompt("decision-brief",
                                        {"topic": "widget eviction"})

    result = asyncio.run(_mcp_call({}, run))
    text = result.messages[0].content.text
    assert "widget-eviction" in text          # the decision is surfaced
    assert "widget-glossary" not in text       # scope=decisions excludes domain


def test_get_prompt_pr_onboard_uses_branch_context(initialised_vault):
    async def run(session):
        return await session.get_prompt("pr-onboard", {})

    result = asyncio.run(_mcp_call({}, run))
    # env fixture is on branch feat/test-branch.
    assert "feat/test-branch" in result.description
    assert result.messages[0].role == "user"
    assert result.messages[0].content.text.strip()


def test_get_prompt_unknown_name_errors(initialised_vault):
    async def run(session):
        return await session.get_prompt("does-not-exist", {})

    import pytest
    with pytest.raises(BaseException) as ei:
        asyncio.run(_mcp_call({}, run))
    flat, stack = [], [ei.value]
    while stack:
        e = stack.pop()
        subs = getattr(e, "exceptions", None)
        if subs:
            stack.extend(subs)
        else:
            flat.append(str(e))
    assert any("unknown prompt" in m for m in flat)


def test_get_prompt_missing_required_arg_errors(initialised_vault):
    import pytest

    async def run(session):
        return await session.get_prompt("recall-pack", {})

    # The handler raises; the client's TaskGroup may wrap it in an
    # ExceptionGroup, so unwrap and assert the cause mentions the missing arg.
    with pytest.raises(BaseException) as ei:
        asyncio.run(_mcp_call({}, run))
    # Unwrap a possible ExceptionGroup (duck-typed on `.exceptions`).
    flat, stack = [], [ei.value]
    while stack:
        e = stack.pop()
        subs = getattr(e, "exceptions", None)
        if subs:
            stack.extend(subs)
        else:
            flat.append(str(e))
    assert any("topic" in m for m in flat)


def test_mcp_exposes_no_write_tools(initialised_vault):
    """Structural moat (SECURITY.md Guarantee #1): the MCP server exposes only
    READ tools. A write tool over MCP would let a prompt injection mutate shared
    memory silently. Locked here so 'no silent writes' can't regress as tools
    are added — a new read tool passes; anything write-shaped fails CI."""
    import re

    async def run(session):
        return await session.list_tools()

    result = asyncio.run(_mcp_call({}, run))
    names = [t.name for t in result.tools]
    assert names, "server should expose tools"
    write_verb = re.compile(
        r"(save|write|create|update|delete|remove|put|^set|_set|add|edit|"
        r"decide|forget|invalidat|supersed|promote|export|ingest|commit|store)",
        re.I)
    offenders = [n for n in names if write_verb.search(n)]
    assert not offenders, f"MCP must expose no write tools; found: {offenders}"
