"""Tests for the small-sample stats behind the retrieval benchmarks."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


def test_wilson_known_values():
    import eval_stats as es
    # Reference Wilson 95% intervals (z=1.96).
    lo, hi = es.wilson_interval(5, 10)
    assert abs(lo - 0.237) < 0.01 and abs(hi - 0.763) < 0.01
    lo, hi = es.wilson_interval(10, 10)
    assert abs(lo - 0.722) < 0.01 and hi > 0.999
    lo, hi = es.wilson_interval(0, 10)
    assert lo == 0.0 and abs(hi - 0.278) < 0.01


def test_wilson_zero_n_is_full_interval():
    import eval_stats as es
    assert es.wilson_interval(0, 0) == (0.0, 1.0)


def test_wilson_interval_narrows_with_n():
    import eval_stats as es
    _, hi_small = es.wilson_interval(8, 10)
    lo_small, _ = es.wilson_interval(8, 10)
    lo_big, hi_big = es.wilson_interval(80, 100)
    assert (hi_big - lo_big) < (hi_small - lo_small)  # more data → tighter


def test_prob_improvement_strong_evidence():
    import eval_stats as es
    assert es.prob_improvement(10, 10, 0, 10) > 0.99   # ON clearly beats OFF
    assert es.prob_improvement(0, 10, 10, 10) < 0.01   # ON clearly loses


def test_prob_improvement_no_difference_is_half():
    import eval_stats as es
    assert abs(es.prob_improvement(5, 10, 5, 10) - 0.5) < 0.05


def test_prob_improvement_modest_lift():
    import eval_stats as es
    p = es.prob_improvement(8, 10, 5, 10)
    assert 0.5 < p < 0.95  # suggestive, not certain, on a tiny set


def test_fmt_rate_includes_ci():
    import eval_stats as es
    s = es.fmt_rate(7, 10)
    assert "7/10" in s and "95% CI" in s
    assert es.fmt_rate(0, 0) == "n/a (0 cases)"
