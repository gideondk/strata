---
title: FAQ
description: "Answers to the questions people ask after the first hour with Strata."
---

## What is a "vault"?

A folder on your computer that holds Strata's notes. Default location is `~/StrataVault`. Inside it, one subfolder per project (named after your git remote, or the directory if there's no remote). Inside each project folder, one subfolder per scope: `decisions/`, `domain/`, `procedural/`, `pr-context/`, `lessons/`, `propositions/`. Plain markdown files, nothing exotic.

## What is "the codebase memory"?

Just the notes in your vault for the current project. When you ask Claude something, Strata searches those notes and feeds the relevant ones into the conversation. Claude uses them to ground its answer.

## Does Strata send my code anywhere?

No. Strata writes markdown to your disk, reads it locally with SQLite full-text search and an on-device embedding model. It has no network code. No telemetry, no analytics, no cloud sync.

If you want the vault to sync between your machines, you choose how: Obsidian Sync, Syncthing, iCloud, Dropbox, a git repo — Strata doesn't care.

## Do I need to know Markdown?

You read it; Claude writes it. The format is simple (headers, bullets, code blocks) and Strata generates well-formed files. If you open one in Obsidian or a text editor, you'll recognise the structure immediately.

## Do I need to know what an ADR is?

ADR = Architecture Decision Record. A short note that says: "we decided X over Y because Z." Strata creates them when you say "let's go with Postgres" or similar. You don't need to memorise the format; Claude fills in the template.

## Will Claude actually use the notes?

Yes, automatically. When your question overlaps a topic in the vault, Strata's MCP tools surface relevant notes and Claude reads them as part of its answer. You don't issue a recall command. You just ask the question.

If you want to see what Claude consulted, ask: "what notes did you use for that answer?"

## What if my team uses Cursor or another editor?

Strata is currently a Claude Code plugin. The vault files are plain markdown, so other tools can read them, but only Claude Code gets the auto-recall and the slash commands. A Cursor plugin would be a separate piece of work; the vault format would carry over.

## What if I want to delete the vault?

`rm -rf ~/StrataVault` (or wherever you put it). The plugin has no other state on your system besides a small search index at `~/.claude/plugins/data/strata*`, which you can also delete.

## What if I make a mistake in a note?

Four options, depending on what's wrong:

- **Correct** — fix a paragraph, leave the rest. `/strata:correct <path>`
- **Invalidate** — the whole note is stale; keep the history visible. `/strata:invalidate <path>`
- **Supersede** — a new decision replaces an old one. `/strata:decide --supersedes <old>`
- **Forget** — the note should never have been written. `/strata:forget <path>`

Every operation leaves an audit trail. See [Correcting the vault](/guide/correcting/).

## What if I already have planning docs?

Run `/strata:bootstrap` once. It walks your `docs/`, `.planning/`, or wherever you keep markdown, groups sibling files (PLAN + CONTEXT + SPEC for the same initiative), dispatches each group to a worker that decides what's a decision vs. a domain note vs. a retrospective, and writes the results into the vault. Idempotent; safe to re-run.

## Do I need Python installed?

Yes, Python 3.10 or newer. The plugin auto-creates a virtual environment on first run and installs two small dependencies (`mcp` and `python-frontmatter`). Nothing global, no system packages touched.

If you're on macOS and `python3` is 3.9, `brew install python@3.13` is enough.

## What's "Graphify"?

A separate tool that builds a graph of your code (functions, classes, who calls whom). Strata uses it for verified `code_refs` on notes and drift detection (notice when a note mentions code that no longer exists). Optional. Without Graphify, Strata still works fine; you just lose those two features.

## Is this open source?

Yes, under the 0BSD license — the most permissive software license. Use it, modify it, ship it commercially, fork it, no attribution required. The license file is in the repo root.

## How do I uninstall?

```text
/plugin uninstall strata@strata
/plugin marketplace remove strata
```

Optionally delete the vault, the search index at `~/.claude/plugins/data/strata*`, and the `.venv/` inside the plugin source. The plugin has no other state on your system.
