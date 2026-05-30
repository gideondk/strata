"""Tests for the self-contained HTML dashboard (build_dashboard_html)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))


def _write(mem, rel, content):
    p = mem / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return p


def test_html_is_self_contained_and_csp_first(initialised_vault):
    import dashboard
    html = dashboard.build_dashboard_html()
    assert html.startswith("<!doctype html>")
    # CSP meta must be the FIRST element in <head> (a meta CSP only governs
    # content parsed after it).
    head = html.split("</head>", 1)[0]
    csp = head.find("Content-Security-Policy")
    assert csp != -1
    assert csp < head.find("<title>")
    assert "connect-src 'none'" in head        # the no-egress proof
    # Truly offline: no external resource references at all.
    assert "http://" not in html and "https://" not in html
    assert "<script src" not in html and "<link " not in html
    assert "fetch(" not in html and "type=\"module\"" not in html


def test_html_inlines_css_js_and_data(initialised_vault):
    import dashboard
    html = dashboard.build_dashboard_html()
    assert "<style>" in html
    assert '<script type="application/json" id="strata-data">' in html
    assert "Awaiting your input" in html
    assert "Decision lifecycle" in html


def test_script_close_tag_in_note_cannot_break_out(initialised_vault):
    """A note title containing </script> must not terminate the data block."""
    import db
    mem = initialised_vault
    _write(mem, "decisions/2026-05-30-x.md",
           "---\ntitle: 'evil </script><img> title'\nstatus: accepted\n---\nbody\n")
    db.reindex(force=True)
    import dashboard
    html = dashboard.build_dashboard_html()
    # The raw closing tag must be neutralised inside the JSON block.
    data_block = html.split('id="strata-data">', 1)[1].split("</script>", 1)[0]
    assert "</script>" not in data_block
    assert "\\u003c/script" in data_block or "\\u003c/" in data_block
    # And in visible HTML the title is escaped, not live markup.
    assert "evil </script><img>" not in html


def test_lifecycle_renders_stage_strip(initialised_vault):
    import db
    mem = initialised_vault
    _write(mem, "propositions/2026-05-30-q.md",
           "---\ntitle: Open question\nstatus: contested\n---\nbody\n")
    db.reindex(force=True)
    import dashboard
    html = dashboard.build_dashboard_html()
    assert "Open question" in html
    assert "dot on" in html           # the active-stage marker rendered
    for stage in ("open", "contested", "converging", "settled"):
        assert stage in html


def test_quarantined_note_appears_in_review_tray_not_recall(initialised_vault):
    """An auto-note shows in the dashboard review tray (where the human triages
    it) — consistent with being quarantined from recall."""
    import db
    mem = initialised_vault
    _write(mem, "pr-context/feat-x/2026-05-30-1200--gk--obs.md",
           "---\nkind: observation\nstatus: auto\nsource: git-derived\n"
           "title: Tray observation\n---\nbody\n")
    db.reindex(force=True)
    import dashboard
    html = dashboard.build_dashboard_html()
    assert "Tray observation" in html
    assert "🤖 review" in html


def test_refresh_index_writes_html_atomically(initialised_vault):
    import importlib.util
    import os
    mem = initialised_vault
    spec = importlib.util.spec_from_file_location(
        "refresh_index",
        os.path.join(HERE.parent, "scripts", "refresh-index.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.regenerate_index()
    idx = mem / "index.html"
    assert idx.exists()
    assert idx.read_text().startswith("<!doctype html>")
    assert not (mem / "index.html.tmp").exists()  # tmp cleaned by os.replace
    # Rough HTML well-formedness: balanced doctype + closing html.
    assert idx.read_text().rstrip().endswith("</html>")
    assert len(re.findall(r"<details", idx.read_text())) >= 1
