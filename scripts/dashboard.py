"""Compose the Strata dashboard markdown.

Used by:
  - refresh-index.py — writes the output to `<vault>/<repo>/INDEX.md` so
    Obsidian, any markdown viewer, or `cat` renders the dashboard for free
  - /strata:dashboard skill — emits the same content into the
    conversation when the user asks for vault state

One source of truth, two render surfaces. No web server, no port.
"""
from __future__ import annotations

import html
import json
import time
from datetime import datetime, timezone
from string import Template

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

    out: list[str] = []
    if s["recall_hits"]:
        out.append(
            f"- {s['recall_hits']} recall hit(s) over {s['distinct_recalled']} "
            f"note(s) in {int(s['since_days'])}d"
            + (f"; {s['nudges_shown']} nudge(s) shown"
               if s["nudges_shown"] else ""))
        for e in s["top_recalled"][:5]:
            out.append(f"  - 🔁 `{e['path']}` — {e['hits']} hit(s)")
    # Saves by kind — the seed signal for the (deferred) per-kind autonomy
    # graduation policy: which note-kinds the team actually accepts.
    if s.get("notes_saved"):
        by_kind = ", ".join(f"{k}:{n}" for k, n
                            in sorted(s["saves_by_kind"].items()))
        out.append(f"- {s['notes_saved']} note(s) saved in "
                   f"{int(s['since_days'])}d ({s['saves_via_draft']} via draft)"
                   + (f" — {by_kind}" if by_kind else ""))
    # Recall audit trail — the observability surface: what was searched, how it
    # was answered, and what came back. Answers "why did the agent see that?"
    try:
        recents = usage.recent_recalls(since_days=7, limit=5)
    except Exception:
        recents = []
    if recents:
        out.append(f"- recent recalls (last {len(recents)}):")
        for e in recents:
            q = (e.get("query") or "").strip() or "·"
            top = e["hits"][0]["path"] if e.get("hits") else "no hits"
            out.append(f"  - 🔎 “{q}” → {e.get('n', 0)} hit(s) "
                       f"via {e.get('mechanism', '?')} → `{top}`")
    if not out:
        return [f"_no recalls or saves logged in the last "
                f"{int(s['since_days'])}d yet_"]
    # Staleness ranking — principled replacement for the old "30d old + never
    # recalled" heuristic: importance-weighted exponential decay (age measured
    # from last modify-or-recall, decaying slower the more a note is recalled).
    try:
        import staleness
        stale = staleness.rank_stale(limit=5)
        if stale:
            out.append(f"- {len(stale)} stale durable note(s) "
                       "(decayed, rarely recalled — review or archive):")
            for s in stale:
                out.append(f"  - 🥀 `{s['path']}` — staleness "
                           f"{s['staleness']:.2f} ({s['age_days']:.0f}d, "
                           f"{s['hits']} hit(s))")
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# HTML dashboard — a single self-contained file (CSS + JS + data inlined), the
# glanceable team surface. Opened via file:// — NO server, NO daemon, NO network.
#
# DO NOT "modernise" this into fetch()/ES-modules/<script src>/<link href>: a
# file:// page is an opaque null origin, so all of those hard-fail with CORS.
# Everything MUST stay inlined in the one file. The CSP meta (first child of
# <head>, connect-src 'none') is the audit-grade proof that this surface never
# touches the network — keep it first and keep it strict.
# ---------------------------------------------------------------------------

_LIFECYCLE_STAGES = ["open", "contested", "converging", "settled"]


def _lifecycle_data(limit: int = 30) -> list[dict]:
    """Propositions + decisions with their lifecycle stage + provenance, newest
    first. Maps proposition statuses + ADR statuses onto the 4-stage strip."""
    import contextlib
    rows: list[dict] = []
    with contextlib.suppress(Exception):
        import db
        with db.connect() as conn:
            for r in conn.execute(
                "SELECT path, title, scope, status, branch, mtime FROM files "
                "WHERE scope IN ('propositions', 'decisions') "
                "ORDER BY mtime DESC LIMIT ?",
                (limit,),
            ):
                status = (r["status"] or "").lower()
                if r["scope"] == "decisions":
                    stage = "settled" if status in ("accepted", "superseded") \
                        else "converging" if status == "proposed" else "settled"
                    superseded = status in ("superseded", "deprecated",
                                            "rejected")
                else:  # propositions
                    if status.startswith("settled") or status.startswith("refuted"):
                        stage = "settled"
                    elif status in _LIFECYCLE_STAGES:
                        stage = status
                    else:
                        stage = "open"
                    superseded = status.startswith("refuted")
                rows.append({
                    "path": r["path"], "title": r["title"] or r["path"],
                    "scope": r["scope"], "status": status or "?",
                    "stage": stage, "branch": r["branch"] or "",
                    "superseded": superseded,
                })
    return rows


def _dashboard_data() -> dict:
    """Every section as JSON-serialisable data — the single compute path the
    HTML render consumes (the markdown build reads the same underlying sources)."""
    import contextlib
    counts = _scope_counts()

    tray: dict = {"decide": [], "review": [], "draft": None}
    with contextlib.suppress(Exception):
        import inbox
        tray["decide"] = inbox.aging_questions()
        tray["review"] = inbox.auto_notes()
    with contextlib.suppress(Exception):
        import draft_store
        d = draft_store.load_draft()
        if d:
            tray["draft"] = {"topic": d.get("topic") or "session draft"}

    stale: list[dict] = []
    with contextlib.suppress(Exception):
        import db
        stale = db.stale_decisions()

    drift: list[dict] = []
    with contextlib.suppress(Exception):
        import code_graph
        drift = code_graph.find_drifted_notes() or []

    usage: dict = {}
    with contextlib.suppress(Exception):
        import usage as _u
        usage = _u.summary()

    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "scope_counts": counts,
        "tray": tray,
        "lifecycle": _lifecycle_data(),
        "stale_adrs": stale,
        "drift": drift,
        "recent": _recent_activity(),
        "usage": usage,
    }


def _inline_json(data: dict) -> str:
    """Serialise + neutralise `</script>` (escape < and > to \\u escapes) so a
    stray closing tag in any note title can't break out of the data block."""
    raw = json.dumps(data, ensure_ascii=False)
    return raw.replace("<", "\\u003c").replace(">", "\\u003e")


def _esc(s) -> str:
    return html.escape(str(s), quote=True)


def _cmd_chip(cmd: str) -> str:
    """A click-to-copy slash-command chip. file:// is read-only — never a fake
    mutating button; the chip copies the command the human then runs."""
    c = _esc(cmd)
    return (f'<button class="cmd" data-cmd="{c}" '
            f'title="click to copy">{c}</button>')


def _tray_section(tray: dict) -> str:
    items: list[str] = []
    for q in tray.get("decide", []):
        age = q.get("age_days", 0)
        stale = ' <span class="flag">stale</span>' if age >= 14 else ""
        items.append(
            f'<article class="item" data-search="{_esc(q["title"])} '
            f'{_esc(q["path"])} decide">'
            f'<span class="badge decide">❓ decide</span> '
            f'<b>{_esc(q["title"])}</b> '
            f'<span class="meta">[{_esc(q.get("status", "open"))}] · '
            f'{age}d{stale} · <code>{_esc(q["path"])}</code></span> '
            f'{_cmd_chip("/strata:propose")}</article>')
    for a in tray.get("review", []):
        age = a.get("age_days", 0)
        stale = ' <span class="flag">stale</span>' if age >= 14 else ""
        items.append(
            f'<article class="item" data-search="{_esc(a["title"])} '
            f'{_esc(a["path"])} review auto">'
            f'<span class="badge review">🤖 review</span> '
            f'<b>{_esc(a["title"])}</b> '
            f'<span class="meta">auto-captured · {age}d{stale} · '
            f'<code>{_esc(a["path"])}</code></span> '
            f'{_cmd_chip("/strata:forget " + a["path"])}</article>')
    draft = tray.get("draft")
    if draft:
        items.append(
            f'<article class="item" data-search="{_esc(draft["topic"])} draft">'
            f'<span class="badge draft">📝 draft</span> '
            f'<b>{_esc(draft["topic"])}</b> '
            f'<span class="meta">pending session draft</span> '
            f'{_cmd_chip("/strata:save --apply-draft")}</article>')
    n = len(items)
    body = "".join(items) or '<p class="empty">Nothing awaiting input — clear.</p>'
    open_attr = " open" if items else ""
    return (f'<details class="card tray"{open_attr}>'
            f'<summary><h2>📥 Awaiting your input</h2>'
            f'<span class="count">{n}</span></summary>{body}</details>')


def _lifecycle_section(rows: list[dict]) -> str:
    if not rows:
        return ('<section class="card"><h2>Decision lifecycle</h2>'
                '<p class="empty">No decisions or propositions yet.</p></section>')
    out: list[str] = []
    for r in rows:
        cur = r["stage"]
        strip = []
        active = False
        for st in _LIFECYCLE_STAGES:
            on = (st == cur)
            if on:
                active = True
            cls = "dot on" if on else ("dot done" if not active else "dot")
            strip.append(f'<span class="{cls}" title="{st}"></span>'
                         f'<span class="stage-label">{st}</span>')
        sup = ' <span class="flag">superseded</span>' if r["superseded"] else ""
        prov = (f' · {_esc(r["branch"])}' if r["branch"] else "")
        out.append(
            f'<article class="item lc" data-search="{_esc(r["title"])} '
            f'{_esc(r["path"])} {r["scope"]} {r["status"]}">'
            f'<div class="lc-head"><span class="badge {r["scope"]}">'
            f'{"⚖️" if r["scope"]=="decisions" else "🌱"} {r["status"]}{sup}'
            f'</span> <b>{_esc(r["title"])}</b> '
            f'<span class="meta"><code>{_esc(r["path"])}</code>{prov}</span></div>'
            f'<div class="strip">{"".join(strip)}</div></article>')
    return (f'<section class="card"><h2>Decision lifecycle</h2>'
            f'{"".join(out)}</section>')


def _simple_card(title: str, rows: list[str], *, empty: str,
                 collapsed: bool = False) -> str:
    body = "".join(rows) or f'<p class="empty">{empty}</p>'
    if collapsed:
        return (f'<details class="card"><summary><h2>{title}</h2>'
                f'<span class="count">{len(rows)}</span></summary>{body}</details>')
    return f'<section class="card"><h2>{title}</h2>{body}</section>'


def _row(text: str, *, search: str = "") -> str:
    return (f'<article class="item" data-search="{_esc(search or text)}">'
            f'{text}</article>')


def build_dashboard_html() -> str:
    """Render the self-contained HTML dashboard. Returns the full document."""
    d = _dashboard_data()

    stale_rows = [
        _row(f'<b>{_esc(s["title"])}</b> '
             f'<span class="meta">proposed {s.get("age_days","?")}d · '
             f'<code>{_esc(s["path"])}</code></span>',
             search=f'{s["title"]} {s["path"]}')
        for s in d["stale_adrs"]
    ]
    drift_rows = [
        _row(f'<code>{_esc(x.get("path", x))}</code>',
             search=str(x.get("path", x)))
        for x in d["drift"]
    ] if d["drift"] else []
    recent_rows = [
        _row(f'<span class="badge {r["scope"]}">{_esc(r["scope"])}</span> '
             f'<b>{_esc(r["title"])}</b> '
             f'<span class="meta"><code>{_esc(r["path"])}</code></span>',
             search=f'{r["title"]} {r["path"]} {r["scope"]}')
        for r in d["recent"]
    ]

    # Scope-count CSS bars.
    counts = d["scope_counts"]
    mx = max(counts.values()) if counts else 1
    scope_bars = "".join(
        f'<div class="bar-row"><span class="bar-label">{_esc(k)}</span>'
        f'<span class="bar" style="--w:{int(100 * v / (mx or 1))}%"></span>'
        f'<span class="bar-n">{v}</span></div>'
        for k, v in sorted(counts.items(), key=lambda kv: -kv[1])
    )
    u = d["usage"]
    usage_line = ""
    if u.get("recall_hits") or u.get("notes_saved"):
        usage_line = (f'<p class="meta">{u.get("recall_hits",0)} recall hit(s) · '
                      f'{u.get("notes_saved",0)} note(s) saved · '
                      f'{u.get("nudges_shown",0)} nudge(s) ({int(u.get("since_days",30))}d)</p>')

    body = (
        _tray_section(d["tray"])
        + _lifecycle_section(d["lifecycle"])
        + _simple_card("⏳ Stale-proposed ADRs (&gt;14d)", stale_rows,
                       empty="None — decisions aren't stalling.")
        + _simple_card("🔀 Drifted notes", drift_rows,
                       empty="None — notes track the code.", collapsed=True)
        + _simple_card("🕓 Recent activity (7d)", recent_rows,
                       empty="No activity in the last 7 days.", collapsed=True)
        + (f'<details class="card"><summary><h2>📊 Vault stats</h2></summary>'
           f'<div class="bars">{scope_bars}</div>{usage_line}</details>')
    )

    title = _esc(memory_dir().name)
    shell = Template(_HTML_SHELL)
    return shell.safe_substitute(
        title=title, generated=_esc(d["generated"]), body=body,
        css=_CSS, js=_JS, data_json=_inline_json(d),
    )


_HTML_SHELL = """<!doctype html>
<html lang="en">
<head>
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Strata — $title</title>
<style>$css</style>
</head>
<body>
<header>
  <h1>Strata <span class="repo">$title</span></h1>
  <input id="q" type="search" placeholder="Filter everything…" aria-label="Filter dashboard">
  <span class="stamp">Generated $generated · offline, no network</span>
</header>
<main>$body</main>
<script type="application/json" id="strata-data">$data_json</script>
<script>$js</script>
</body>
</html>
"""

_CSS = """
:root{--bg:#fff;--fg:#1a1a1a;--muted:#666;--card:#f6f7f9;--line:#e2e5e9;
  --accent:#3b5bdb;--open:#e8590c;--contested:#c92a2a;--converging:#f08c00;
  --settled:#2b8a3e;--flag:#c92a2a;--chip:#e7ebff}
@media(prefers-color-scheme:dark){:root{--bg:#16181d;--fg:#e6e8eb;--muted:#9aa0a8;
  --card:#1e2127;--line:#2a2e36;--chip:#26304d}}
*{box-sizing:border-box}
body{margin:0;font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;
  background:var(--bg);color:var(--fg)}
header{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);
  padding:14px 20px;display:flex;gap:14px;align-items:center;flex-wrap:wrap;z-index:5}
h1{font-size:18px;margin:0}.repo{color:var(--accent)}
#q{flex:1;min-width:200px;padding:7px 11px;border:1px solid var(--line);
  border-radius:8px;background:var(--card);color:var(--fg);font-size:14px}
.stamp{color:var(--muted);font-size:12px}
main{max-width:920px;margin:0 auto;padding:18px 20px;display:flex;
  flex-direction:column;gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
  padding:14px 16px}
.card>summary{cursor:pointer;list-style:none;display:flex;align-items:center;gap:10px}
.card>summary::-webkit-details-marker{display:none}
h2{font-size:15px;margin:0 0 2px;display:inline}
.count{background:var(--accent);color:#fff;border-radius:999px;padding:1px 9px;
  font-size:12px;font-weight:600}
.item{padding:8px 0;border-top:1px solid var(--line);font-size:14px}
.card>.item:first-of-type,details>.item:first-of-type{border-top:0}
.empty{color:var(--muted);margin:6px 0 0;font-style:italic}
.meta{color:var(--muted);font-size:12.5px}
code{background:rgba(127,127,127,.14);padding:1px 5px;border-radius:5px;font-size:12px}
.badge{display:inline-block;font-size:11.5px;font-weight:600;padding:1px 8px;
  border-radius:999px;background:var(--chip);color:var(--accent);white-space:nowrap}
.badge.decisions{background:#e6f4ea;color:var(--settled)}
.badge.propositions{background:#fff3bf;color:#915c00}
.flag{color:#fff;background:var(--flag);border-radius:5px;padding:0 6px;font-size:11px}
.cmd{font:12px ui-monospace,SFMono-Regular,Menlo,monospace;border:1px solid var(--line);
  background:var(--bg);color:var(--accent);border-radius:6px;padding:2px 7px;
  cursor:pointer}
.cmd:hover{background:var(--chip)}.cmd.copied{background:var(--settled);color:#fff}
.lc .lc-head{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.strip{display:flex;align-items:center;gap:4px;margin:7px 0 2px;flex-wrap:wrap}
.dot{width:11px;height:11px;border-radius:50%;background:var(--line);
  border:2px solid var(--line)}
.dot.done{background:var(--muted);border-color:var(--muted)}
.dot.on{background:var(--accent);border-color:var(--accent);
  box-shadow:0 0 0 3px rgba(59,91,219,.25)}
.stage-label{font-size:11px;color:var(--muted);margin-right:8px}
.bars{display:flex;flex-direction:column;gap:5px}
.bar-row{display:flex;align-items:center;gap:8px;font-size:13px}
.bar-label{width:110px;color:var(--muted)}
.bar{height:9px;width:var(--w);min-width:3px;background:var(--accent);
  border-radius:5px;opacity:.8}
.bar-n{font-variant-numeric:tabular-nums;color:var(--muted)}
.hidden{display:none!important}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media print{details{open:true}.card>summary{pointer-events:none}
  details:not([open])>*{display:revert!important}header{position:static}}
"""

_JS = """
(function(){
  'use strict';
  // Click-to-copy command chips. file:// has no clipboard guarantee, so fall
  // back to a manual-select range; never throw.
  document.addEventListener('click',function(e){
    var b=e.target.closest('.cmd'); if(!b)return;
    var t=b.getAttribute('data-cmd')||'';
    var done=function(){b.classList.add('copied');var o=b.textContent;
      b.textContent='copied ✓';setTimeout(function(){b.textContent=o;
      b.classList.remove('copied');},900);};
    try{ if(navigator.clipboard&&navigator.clipboard.writeText){
      navigator.clipboard.writeText(t).then(done,done);return;} }catch(_){}
    done();
  });
  // Debounced filter over every .item via its data-search attribute.
  var q=document.getElementById('q');
  var items=Array.prototype.slice.call(document.querySelectorAll('.item'));
  var timer=null;
  function apply(){
    var v=(q.value||'').trim().toLowerCase();
    items.forEach(function(el){
      var hay=(el.getAttribute('data-search')||'').toLowerCase();
      el.classList.toggle('hidden', v!=='' && hay.indexOf(v)===-1);
    });
    // Open any details that still have visible items so matches aren't hidden.
    document.querySelectorAll('details.card').forEach(function(dt){
      if(v==='')return;
      var any=dt.querySelector('.item:not(.hidden)');
      if(any)dt.open=true;
    });
  }
  if(q)q.addEventListener('input',function(){clearTimeout(timer);
    timer=setTimeout(apply,120);});
})();
"""


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
