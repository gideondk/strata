---
title: What is Strata?
description: "Plain-English intro for anyone landing here for the first time. No jargon, no setup, just what the thing does and who it's for."
---

Strata gives Claude Code a memory that survives between sessions.

## The problem in one paragraph

When you work with Claude Code, every conversation starts from zero. Claude doesn't remember the decisions your team made last week. It doesn't know the domain terms your codebase uses. It doesn't know that you tried approach X two months ago and it failed. You end up re-explaining the same context every session, or you get confidently wrong answers because Claude is guessing.

## What Strata does

Strata is a Claude Code plugin that keeps a small set of markdown files on your computer, organised by what kind of knowledge they hold. When you ask Claude something that touches durable knowledge, Strata quietly looks through those files and surfaces the relevant ones. Claude answers using your team's actual decisions and conventions, not a fresh guess.

The files live in a folder you choose (default `~/StrataVault`). They're plain markdown with structured headers. Open them in Obsidian, VS Code, or any text editor. Nothing leaves your machine.

## Who it's for

You'll get value from Strata if:

- You work in Claude Code regularly on the same codebase
- Your team makes architectural decisions you want Claude to remember
- You have domain terms (vocabulary specific to your project) that Claude keeps getting wrong
- You write planning docs and want them migrated into a queryable form
- You care about local-first tools (no SaaS, no telemetry, no copying your code to someone else's server)

You probably won't need it if:

- You only use Claude Code for quick one-off scripts
- Your codebase is small enough that explaining context each time is fine
- You're happy letting another tool index and embed your work elsewhere

## How it stays out of the way

Most of the time you don't run any commands. Claude detects when a question touches durable knowledge and consults the vault on its own. You'll see a one-line acknowledgement and the answer.

When you want to capture something explicitly, three commands cover the common cases:

- `/strata:save` — capture working notes for the current branch
- `/strata:decide` — record a chosen approach with reasoning
- `/strata:propose` — track an open question

Everything else (correcting notes, migrating old docs, exporting back into the repo) has its own command but auto-invokes on intent. You rarely have to remember anything.

## What you'll see when you install it

1. Run `/plugin marketplace add https://github.com/gideondk/strata` then `/plugin install strata@strata` in Claude Code.
2. The plugin prompts for a vault folder (just press enter for the default).
3. Run `/strata:init` once in your repo. Five seconds, zero questions.
4. Work normally. The first time you make a decision worth keeping, ask Claude to save it. Or wait for Strata's gentle nudge after 30 minutes of unsaved work on a branch.

## What this guide covers

The next pages explain the model (why three kinds of memory, not one), the slash commands, and how Strata talks to Claude under the hood. Pick whatever order you like; they're independent.

For five-minute setup with no theory, jump to [Getting started](../getting-started/).
