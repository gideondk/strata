"""Small-sample statistics for the retrieval benchmarks — stdlib `math` only,
so it stays zero-network and dependency-free (no scipy/numpy).

Two tools the benchmark needs and the repo lacked:
  * wilson_interval — a 95% confidence interval on a proportion that behaves at
    n=10 and at 0/n or n/n, where the naive Wald interval breaks.
  * prob_improvement — Beta-Binomial posterior P(p_on > p_off), the honest way
    to report an ON-vs-OFF ablation delta on a small set instead of a bare mean.

Both are deterministic (no sampling), so benchmark numbers are reproducible.
"""
from __future__ import annotations

import math

Z95 = 1.959963984540054  # standard normal 97.5th percentile


def wilson_interval(successes: int, n: int, z: float = Z95) -> tuple[float, float]:
    """95% Wilson score interval for `successes`/`n`. Returns (lo, hi) in [0,1].
    n==0 yields the whole interval (no information)."""
    if n <= 0:
        return (0.0, 1.0)
    p = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return (max(0.0, center - half), min(1.0, center + half))


def _beta_logpdf(x: float, a: float, b: float) -> float:
    if x <= 0.0 or x >= 1.0:
        return float("-inf")
    return ((a - 1) * math.log(x) + (b - 1) * math.log(1 - x)
            + math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b))


def prob_improvement(on_k: int, on_n: int, off_k: int, off_n: int,
                     grid: int = 2000) -> float:
    """Posterior probability that the ON arm's true success rate exceeds the
    OFF arm's, under uniform Beta(1,1) priors — P(p_on > p_off).

    Deterministic numerical integration (midpoint grid), so it's reproducible
    and needs no RNG. ~0.5 means the ablation showed nothing; →1.0 means strong
    evidence ON beats OFF."""
    a1, b1 = 1 + on_k, 1 + on_n - on_k
    a2, b2 = 1 + off_k, 1 + off_n - off_k
    dx = 1.0 / grid
    p = 0.0
    cum_b = 0.0  # running CDF of the OFF posterior
    for i in range(grid):
        x = (i + 0.5) * dx
        pdf_a = math.exp(_beta_logpdf(x, a1, b1))
        pdf_b = math.exp(_beta_logpdf(x, a2, b2))
        # P(A>B) = ∫ f_A(x) · CDF_B(x) dx; midpoint-correct the CDF at x.
        p += pdf_a * dx * (cum_b + 0.5 * pdf_b * dx)
        cum_b += pdf_b * dx
    return min(1.0, max(0.0, p))


def mcnemar_exact_p(b: int, c: int) -> float:
    """Exact two-sided McNemar (sign) test for a PAIRED binary ablation, where
    `b` = cases the ON arm wins but OFF loses and `c` = the reverse. Our design
    runs every case ON and OFF, so the arms are paired, not independent — this
    is the correct test, and it's stronger than treating the two rates as
    independent proportions. Returns 1.0 with no discordant pairs (no evidence).
    """
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) * (0.5 ** n)
    return min(1.0, 2.0 * tail)


def fmt_rate(successes: int, n: int) -> str:
    """A proportion with its Wilson 95% CI — the only sanctioned way to print a
    benchmark rate, so a bare point estimate can't slip out."""
    if n <= 0:
        return "n/a (0 cases)"
    lo, hi = wilson_interval(successes, n)
    return f"{successes}/{n} = {successes / n:.3f}  (95% CI [{lo:.3f}, {hi:.3f}])"
