"""Compose the Strata dashboard markdown.

Used by:
  - refresh-index.py — writes the output to `<vault>/<repo>/INDEX.md` so
    Obsidian, any markdown viewer, or `cat` renders the dashboard for free
  - /strata:dashboard skill — emits the same content into the
    conversation when the user asks for vault state

One source of truth, two render surfaces. No web server, no port.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import lib_loader  # noqa: F401
from lib import first_heading, memory_dir


def _scope_counts() -> dict[str, int]:
    mem = memory_dir()
    out: dict[str, int] = {}
    for scope in ("decisions", "domain", "lessons", "procedural",
                  "propositions"):
        d = mem / scope
        if not d.exists():
            out[scope] = 0
            continue
        out[scope] = sum(
            1 for p in d.glob("*.md")
            if p.name not in ("README.md", "INDEX.md")
        )
    # pr-context counts across branches
    pr = mem / "pr-context"
    if pr.exists():
        n = 0
        for branch_dir in pr.iterdir():
            if branch_dir.is_dir():
                n += sum(
                    1 for p in branch_dir.glob("*.md")
                    if p.name not in ("README.md", "INDEX.md")
                )
        out["pr-context"] = n
    else:
        out["pr-context"] = 0
    return out


def _is_auto(path) -> bool:
    """True if a note is staged auto-capture (status: auto). Such notes belong
    only in the review queue, not in canonical 'recent activity' / 'latest'
    surfaces."""
    try:
        import frontmatter
        return str(frontmatter.load(path).metadata.get("status", "")).strip() \
            == "auto"
    except Exception:
        return False


def _recent_activity(days: int = 7, limit: int = 8) -> list[dict]:
    """Notes written or modified in the last `days`. Returns
    [{path, title, scope, mtime}] descending by mtime."""
    mem = memory_dir()
    cutoff = time.time() - days * 86400
    out: list[dict] = []
    for scope in ("decisions", "domain", "lessons", "procedural",
                  "propositions", "pr-context"):
        d = mem / scope
        if not d.exists():
            continue
        for p in d.rglob("*.md"):
            if p.name in ("README.md", "INDEX.md"):
                continue
            # Auto-notes (only in pr-context) belong in the review queue, not
            # in 'recent activity'. Only pay the frontmatter read where they live.
            if scope == "pr-context" and _is_auto(p):
                continue
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            if mtime < cutoff:
                continue
            rel = p.relative_to(mem).as_posix()
            out.append({
                "path": rel,
                "title": first_heading(p) or p.stem,
                "scope": scope,
                "mtime": mtime,
            })
    out.sort(key=lambda r: -r["mtime"])
    return out[:limit]


def _bullet_recent(rows: list[dict]) -> list[str]:
    if not rows:
        return ["_no activity in the last 7 days_"]
    lines = []
    now = time.time()
    for r in rows:
        delta = int((now - r["mtime"]) // 3600)
        when = f"{delta}h ago" if delta < 48 else f"{delta // 24}d ago"
        lines.append(f"- `{r['path']}` — {r['title']}  _({when})_")
    return lines


def _stale_decisions_bullets(threshold_days: int = 14) -> list[str]:
    try:
        import db
        rows = db.stale_decisions(threshold_days)
    except Exception:
        return []
    if not rows:
        return ["_none — good_"]
    return [
        f"- `{r['path']}` — {r['title']}  _({r['age_days']} days)_"
        for r in rows[:10]
    ]


def _hotspot_bullets() -> list[str]:
    try:
        import commit_graph
        hot = commit_graph.hotspots(days=90, top=10)
    except Exception:
        return []
    if not hot:
        return []
    return [f"- `{h['path']}` — {h['commits']} commits" for h in hot]


def _drifted_bullets() -> list[str]:
    try:
        import code_graph
        drifted = code_graph.find_drifted_notes()
    except Exception:
        return []
    if not drifted:
        return ["_none — good_"]
    out = []
    for d in drifted[:8]:
        line = f"- `{d['path']}` — {d['title']}"
        bits = []
        if d.get("unresolved"):
            bits.append(f"{len(d['unresolved'])} unresolved")
        if d.get("churn_signal"):
            bits.append(
                f"{d['churn_signal']['commits_since']} commits "
                f"since {d['churn_signal']['created']}"
            )
        if bits:
            line += f"  _({' · '.join(bits)})_"
        out.append(line)
    if len(drifted) > 8:
        out.append(f"_… and {len(drifted) - 8} more_")
    return out


def _adr_implementations_bullets() -> list[str]:
    mem = memory_dir()
    dec_dir = mem / "decisions"
    if not dec_dir.is_dir():
        return []
    slugs = [
        f.stem for f in dec_dir.glob("*.md")
        if f.name not in ("README.md", "INDEX.md")
    ]
    if not slugs:
        return []
    try:
        import commit_graph
        links = commit_graph.adr_implementations(slugs)
    except Exception:
        return []
    if not links:
        return []
    out = []
    for slug, commits in sorted(links.items()):
        c = commits[0]
        more = f" (+{len(commits) - 1})" if len(commits) > 1 else ""
        out.append(
            f"- `decisions/{slug}.md` ← `{c['sha']}` "
            f"({c['date'][:10]}){more}"
        )
    return out


def _code_graph_line() -> str | None:
    try:
        import code_graph
        s = code_graph.graph_age_relative_to_head()
        if s is None:
            return None
        marker = "🔴 STALE" if s.get("stale") else "🟢"
        return (
            f"{marker} graph.json — {s['graph_age_days']}d old, "
            f"{s['commits_since']} commit(s) since build"
        )
    except Exception:
        return None


def _pr_contexts() -> list[str]:
    mem = memory_dir()
    d = mem / "pr-context"
    if not d.exists():
        return []
    out = []
    for sub in sorted(p for p in d.iterdir() if p.is_dir()):
        notes = [n for n in sorted(sub.glob("*.md")) if not _is_auto(n)]
        if not notes:
            continue
        latest = notes[-1]
        rel = latest.relative_to(mem).as_posix()
        out.append(
            f"- **`{sub.name}`** — {len(notes)} note(s), latest: "
            f"[`{rel}`]({rel})"
        )
    return out


def _suggestions(scope_counts: dict, drifted: list[str],
                 stale: list[str]) -> list[str]:
    """Two-line action hint at the bottom. Concrete, not generic."""
    hints: list[str] = []
    if "_none — good_" not in stale and stale:
        hints.append(
            f"{len([s for s in stale if s.startswith('-')])} ADR(s) "
            f"in `proposed` past 14 days → review / accept / supersede"
        )
    if drifted and "_none — good_" not in drifted:
        hints.append(
            f"{len([d for d in drifted if d.startswith('-')])} note(s) "
            "drifted from code → `/strata:correct` or `/strata:invalidate`"
        )
    if scope_counts.get("decisions", 0) == 0:
        hints.append("vault has 0 decisions — capture one with `/strata:decide`")
    if not hints:
        return ["_vault looks healthy — no actions surfaced._"]
    return [f"- {h}" for h in hints]


def _awaiting_input_bullets() -> list[str]:
    """The notify/question/review queue: pending draft + lingering open
    propositions. Stale ADRs keep their own section, so they're not repeated
    here."""
    out: list[str] = []
    try:
        import draft_store
        d = draft_store.load_draft()
        if d:
            out.append(
                f"- 📝 review: pending session draft "
                f"**{d.get('topic', 'session draft')}** — "
                f"`/strata:save --apply-draft`")
    except Exception:
        pass
    try:
        import inbox
        for q in inbox.aging_questions():
            out.append(
                f"- ❓ decide: [{q['status']}] **{q['title']}** "
                f"({q['age_days']}d) — `{q['path']}`")
        # Auto-captured observations (status: auto) — surfaced, not asserted;
        # the human keeps (edit) or discards (/strata:forget).
        for a in inbox.auto_notes()[:8]:
            age = a.get("age_days", 0)
            stale = "  ⏳ stale — review or discard" if age >= 14 else ""
            out.append(
                f"- 🤖 auto-captured ({age}d, review): **{a['title']}** — "
                f"`{a['path']}`{stale}")
    except Exception:
        pass
    return out or ["_none — nothing awaiting input_"]


def _memory_usage_bullets() -> list[str]:
    """Recall-usage signals: is the vault used, which notes are dead weight.
    Reads the local usage ledger (best-effort) + the index."""
    try:
        import usage
        s = usage.summary()
    except Exception:
        return ["_usage telemetry unavailable_"]
    if s["recall_hits"] == 0:
        return ["_no recalls logged in the last "
                f"{int(s['since_days'])}d yet_"]
    out = [
        f"- {s['recall_hits']} recall hit(s) over {s['distinct_recalled']} "
        f"note(s) in {int(s['since_days'])}d"
        + (f"; {s['nudges_shown']} nudge(s) shown" if s["nudges_shown"] else ""),
    ]
    for e in s["top_recalled"][:5]:
        out.append(f"  - 🔁 `{e['path']}` — {e['hits']} hit(s)")
    # Dead-memory candidates: durable notes never recalled in the window.
    try:
        import time as _t

        import db
        import usage as _u
        recalled = _u.recalled_paths()
        cutoff = _t.time() - 30 * 86400
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT path FROM files WHERE scope IN "
                "('decisions', 'domain', 'lessons') AND mtime < ? "
                "ORDER BY mtime LIMIT 200",
                (cutoff,),
            ).fetchall()
        dead = [r["path"] for r in rows if r["path"] not in recalled]
        if dead:
            out.append(f"- {len(dead)} durable note(s) not recalled in 30d "
                       f"(dead-memory candidates) — e.g. `{dead[0]}`")
    except Exception:
        pass
    return out


def build_dashboard() -> str:
    """Compose the dashboard markdown. Same body for INDEX.md and skill."""
    mem = memory_dir()
    if not mem.exists():
        return "_no vault yet — run `/strata:init`._"

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    counts = _scope_counts()
    recent = _recent_activity()
    drifted = _drifted_bullets()
    stale = _stale_decisions_bullets()
    hot = _hotspot_bullets()
    impls = _adr_implementations_bullets()
    cg_line = _code_graph_line()
    pr_ctx = _pr_contexts()

    out: list[str] = []
    push = out.append

    push("# Strata dashboard")
    push("")
    push(f"_Generated {stamp}. This file is auto-regenerated on every "
         "vault write — `/strata:dashboard` emits the same content "
         "into the conversation._")
    push("")

    # Scope counts table, episodic/semantic/procedural framing
    push("## Scope counts")
    push("")
    push("| Type | Scope | Count |")
    push("|---|---|---|")
    push(f"| Episodic | `pr-context/` | {counts.get('pr-context', 0)} |")
    push(f"| Semantic | `domain/` | {counts.get('domain', 0)} |")
    push(f"| Semantic | `decisions/` | {counts.get('decisions', 0)} |")
    push(f"| Procedural | `procedural/` | {counts.get('procedural', 0)} |")
    push(f"| Lifecycle | `propositions/` | {counts.get('propositions', 0)} |")
    push(f"| Bridge | `lessons/` | {counts.get('lessons', 0)} |")
    push("")

    if cg_line:
        push(f"_{cg_line}_")
        push("")

    push("## Recent activity (last 7 days)")
    push("")
    out.extend(_bullet_recent(recent))
    push("")

    push("## 📥 Awaiting your input")
    push("")
    out.extend(_awaiting_input_bullets())
    push("")

    push("## Memory usage")
    push("")
    out.extend(_memory_usage_bullets())
    push("")

    push("## Stale-proposed ADRs (>14 days)")
    push("")
    out.extend(stale)
    push("")

    push("## Drifted notes")
    push("")
    out.extend(drifted)
    push("")

    if hot:
        push("## Hot files (last 90 days)")
        push("")
        out.extend(hot)
        push("")

    if impls:
        push("## ADR implementations")
        push("")
        push(f"_{len(impls)} ADR(s) referenced in recent commit messages._")
        push("")
        out.extend(impls)
        push("")

    if pr_ctx:
        push("## Active PR contexts")
        push("")
        out.extend(pr_ctx)
        push("")

    push("---")
    push("")
    push("## Suggested actions")
    push("")
    out.extend(_suggestions(counts, drifted, stale))
    push("")

    return "\n".join(out)


def main() -> int:
    import sys
    sys.stdout.write(build_dashboard())
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
