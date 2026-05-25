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
