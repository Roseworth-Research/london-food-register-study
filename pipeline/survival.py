"""
Survival statistics, implemented directly rather than pulled from a library.

The study's headline claim is about survival, and the study brief requires
Kaplan-Meier estimates with a log-rank test rather than crude survival
percentages. Both are short, standard calculations, and writing them out has a
real advantage for a report that expects hostile reading: a reviewer can check
the arithmetic against a textbook without installing anything or trusting a
library's defaults about tie handling and censoring.

Why censoring matters here
--------------------------
A naive "what share of 2019 incorporations are still alive?" is wrong in two
directions at once. Companies incorporated recently have had less time to die,
so they look healthier. Companies still trading at the snapshot date have not
lived exactly that long -- they have lived AT LEAST that long, and will live
longer. Kaplan-Meier handles both: each still-trading company contributes to
the risk set until the snapshot date and then leaves without counting as a
death.

Definitions used throughout
---------------------------
    duration  days from incorporation to death, or to the snapshot date
    event     1 if the company died, 0 if it was still on the register
              (right-censored) at the snapshot date
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy import stats


@dataclass
class KaplanMeier:
    """A Kaplan-Meier survival curve with Greenwood standard errors."""

    times: np.ndarray = field(default_factory=lambda: np.array([]))
    survival: np.ndarray = field(default_factory=lambda: np.array([]))
    at_risk: np.ndarray = field(default_factory=lambda: np.array([]))
    events: np.ndarray = field(default_factory=lambda: np.array([]))
    variance: np.ndarray = field(default_factory=lambda: np.array([]))
    n: int = 0
    n_events: int = 0

    def survival_at(self, t: float) -> float:
        """Estimated survival probability at time `t`."""
        if len(self.times) == 0:
            return float("nan")
        idx = np.searchsorted(self.times, t, side="right") - 1
        return 1.0 if idx < 0 else float(self.survival[idx])

    def ci_at(self, t: float, z: float = 1.96) -> tuple[float, float]:
        """Confidence interval for survival at `t`, on the log-log scale.

        The log-log transform is used rather than a plain normal interval
        because it keeps the bounds inside [0, 1], which matters at the tails
        where the naive interval runs off the end.
        """
        if len(self.times) == 0:
            return (float("nan"), float("nan"))
        idx = np.searchsorted(self.times, t, side="right") - 1
        if idx < 0:
            return (1.0, 1.0)
        s = float(self.survival[idx])
        v = float(self.variance[idx])
        if s <= 0 or s >= 1 or v <= 0:
            return (s, s)
        # Greenwood variance is for S(t); transform to log(-log(S)).
        se = math.sqrt(v) / (s * abs(math.log(s)))
        centre = math.log(-math.log(s))
        lo = math.exp(-math.exp(centre + z * se))
        hi = math.exp(-math.exp(centre - z * se))
        return (min(lo, hi), max(lo, hi))

    def median_survival(self) -> float:
        """First time at which estimated survival drops to 0.5 or below."""
        below = np.where(self.survival <= 0.5)[0]
        return float(self.times[below[0]]) if len(below) else float("nan")


def kaplan_meier(durations, events) -> KaplanMeier:
    """Fit a Kaplan-Meier curve.

    `durations` are in whatever unit the caller uses (this study uses days);
    `events` are 1 for a death and 0 for right-censored.
    """
    d = np.asarray(durations, dtype=float)
    e = np.asarray(events, dtype=int)
    keep = ~np.isnan(d)
    d, e = d[keep], e[keep]
    if len(d) == 0:
        return KaplanMeier()

    order = np.argsort(d, kind="mergesort")
    d, e = d[order], e[order]

    unique_times = np.unique(d[e == 1])
    n = len(d)
    survival, at_risk, events_at, variance = [], [], [], []
    s = 1.0
    var_sum = 0.0

    for t in unique_times:
        risk = int(np.sum(d >= t))
        deaths = int(np.sum((d == t) & (e == 1)))
        if risk == 0:
            continue
        s *= 1 - deaths / risk
        # Greenwood's formula for the variance of S(t).
        if risk > deaths:
            var_sum += deaths / (risk * (risk - deaths))
        survival.append(s)
        at_risk.append(risk)
        events_at.append(deaths)
        variance.append((s ** 2) * var_sum)

    return KaplanMeier(
        times=unique_times,
        survival=np.array(survival),
        at_risk=np.array(at_risk),
        events=np.array(events_at),
        variance=np.array(variance),
        n=n,
        n_events=int(np.sum(e)),
    )


def logrank_test(d1, e1, d2, e2) -> dict:
    """Two-sample log-rank test.

    Compares the whole survival curves rather than survival at one arbitrary
    point, which is what makes it the right test here: the interesting claim is
    that one format outlives the other throughout, not that it happens to be
    ahead at five years.

    Returns the chi-square statistic on one degree of freedom, the p-value, and
    the observed and expected event counts for group 1.
    """
    d1, e1 = np.asarray(d1, float), np.asarray(e1, int)
    d2, e2 = np.asarray(d2, float), np.asarray(e2, int)
    all_times = np.unique(np.concatenate([d1[e1 == 1], d2[e2 == 1]]))

    obs1 = exp1 = var = 0.0
    for t in all_times:
        n1 = float(np.sum(d1 >= t))
        n2 = float(np.sum(d2 >= t))
        n = n1 + n2
        if n <= 1:
            continue
        o1 = float(np.sum((d1 == t) & (e1 == 1)))
        o2 = float(np.sum((d2 == t) & (e2 == 1)))
        o = o1 + o2
        if o == 0:
            continue
        obs1 += o1
        exp1 += o * n1 / n
        # Hypergeometric variance, with the standard correction for ties.
        var += (o * (n1 / n) * (1 - n1 / n) * ((n - o) / (n - 1))) if n > 1 else 0.0

    if var <= 0:
        return {"chi2": float("nan"), "p": float("nan"),
                "observed_1": obs1, "expected_1": exp1}

    chi2 = (obs1 - exp1) ** 2 / var
    return {
        "chi2": float(chi2),
        "p": float(stats.chi2.sf(chi2, df=1)),
        "observed_1": float(obs1),
        "expected_1": float(exp1),
        # Below 1 means group 1 dies less often than expected.
        "observed_over_expected_1": float(obs1 / exp1) if exp1 else float("nan"),
    }


def cumulative_incidence(durations, causes, n_causes: int = 2) -> dict:
    """Aalen-Johansen cumulative incidence functions for competing risks.

    Why this is needed, and why Kaplan-Meier was the wrong tool
    -----------------------------------------------------------
    A company can leave the register in two mutually exclusive ways: through an
    insolvency procedure, or by being struck off. An earlier version of this
    analysis estimated "insolvency-free survival" with Kaplan-Meier, treating
    strike-off as ordinary censoring. That is wrong, and the error runs in a
    known direction.

    Kaplan-Meier censoring assumes the censored observation would have gone on
    to face the same risk as everyone still at risk. A company that has been
    struck off cannot subsequently become insolvent -- it no longer exists. So
    strike-off is not censoring at all; it is a competing event, and treating
    it as censoring inflates the estimated insolvency risk in a way that
    depends on how often the competing event happens. Since counter formats are
    struck off far more often than service formats, the bias is not even
    symmetric between the groups being compared.

    The cumulative incidence function is the correct estimator. It answers the
    question actually being asked: *of all the companies that started, what
    proportion had reached insolvency by time t*, accounting for the fact that
    others left by another route first.

        CIF_k(t) = sum over event times u <= t of  S(u-) * (d_k(u) / n(u))

    where S is the overall Kaplan-Meier survival for leaving by ANY cause,
    d_k(u) is the number of cause-k events at u, and n(u) the number at risk.

    `causes` is 0 for still-alive (genuinely censored, e.g. the observation
    window ended), and 1..n_causes for each competing event type.
    """
    d = np.asarray(durations, dtype=float)
    c = np.asarray(causes, dtype=int)
    keep = ~np.isnan(d)
    d, c = d[keep], c[keep]
    if len(d) == 0:
        return {}

    # Vectorised. A naive loop that recomputes `np.sum(d >= t)` at every event
    # time is O(n x times), which on 40,000 companies with tens of thousands of
    # distinct durations is slow enough to make bootstrapping impossible. Sort
    # once and use searchsorted instead.
    n = len(d)
    times = np.unique(d[c > 0])
    if len(times) == 0:
        return {k: {"times": np.array([]), "cif": np.array([]), "n": n, "events": 0}
                for k in range(1, n_causes + 1)}

    d_sorted = np.sort(d)
    at_risk = n - np.searchsorted(d_sorted, times, side="left")

    # Events at each time, per cause.
    counts = np.zeros((n_causes, len(times)))
    for k in range(1, n_causes + 1):
        dk = d[c == k]
        if len(dk):
            uniq, cnt = np.unique(dk, return_counts=True)
            counts[k - 1, np.searchsorted(times, uniq)] = cnt

    total = counts.sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        hazard = np.where(at_risk > 0, total / at_risk, 0.0)
        # S(u-) is the overall survival just BEFORE each event time, so shift.
        surv_before = np.concatenate(([1.0], np.cumprod(1 - hazard)[:-1]))
        increments = np.where(
            at_risk > 0, surv_before * counts / np.maximum(at_risk, 1), 0.0
        )

    return {
        k: {
            "times": times,
            "cif": np.cumsum(increments[k - 1]),
            "n": n,
            "events": int(np.sum(c == k)),
        }
        for k in range(1, n_causes + 1)
    }


def cif_at(fit: dict, t: float) -> float:
    """Cumulative incidence of one cause at time `t`."""
    if not fit or len(fit["times"]) == 0:
        return float("nan")
    idx = np.searchsorted(fit["times"], t, side="right") - 1
    return 0.0 if idx < 0 else float(fit["cif"][idx])


def grays_test_approx(d1, c1, d2, c2, cause: int = 1, n_boot: int = 400,
                      horizon: float = 1095, seed: int = 12345) -> dict:
    """Bootstrap comparison of two cumulative incidence curves at a horizon.

    Gray's test proper is not implemented here. This resamples both groups and
    reports the distribution of the difference in cumulative incidence at a
    fixed horizon, which is what the report quotes, and gives a confidence
    interval rather than only a point estimate. Stated as what it is: a
    bootstrap, not Gray's test.
    """
    rng = np.random.default_rng(seed)
    d1, c1 = np.asarray(d1, float), np.asarray(c1, int)
    d2, c2 = np.asarray(d2, float), np.asarray(c2, int)

    observed = (
        cif_at(cumulative_incidence(d1, c1).get(cause, {}), horizon)
        - cif_at(cumulative_incidence(d2, c2).get(cause, {}), horizon)
    )

    diffs = []
    for _ in range(n_boot):
        i1 = rng.integers(0, len(d1), len(d1))
        i2 = rng.integers(0, len(d2), len(d2))
        a = cif_at(cumulative_incidence(d1[i1], c1[i1]).get(cause, {}), horizon)
        b = cif_at(cumulative_incidence(d2[i2], c2[i2]).get(cause, {}), horizon)
        diffs.append(a - b)
    diffs = np.array(diffs)
    return {
        "difference": float(observed),
        "ci_low": float(np.percentile(diffs, 2.5)),
        "ci_high": float(np.percentile(diffs, 97.5)),
        "n_bootstrap": n_boot,
    }


def mann_whitney(a, b) -> dict:
    """Mann-Whitney U for two independent samples, with a rank-biserial effect size.

    Used for comparing medians (of growth rates, of lifespans) between formats.
    Significance on 100,000 companies is nearly automatic, so the effect size
    is what the report leads with: a p-value of 1e-40 on a rank-biserial
    correlation of 0.02 is a real difference nobody would notice in a shop.
    """
    a = np.asarray([x for x in a if x is not None and not np.isnan(x)], float)
    b = np.asarray([x for x in b if x is not None and not np.isnan(x)], float)
    if len(a) < 2 or len(b) < 2:
        return {"u": float("nan"), "p": float("nan"), "effect_size": float("nan"),
                "n1": len(a), "n2": len(b)}
    u, p = stats.mannwhitneyu(a, b, alternative="two-sided")
    # Rank-biserial correlation: 0 means the distributions overlap completely,
    # +1 means every value in a exceeds every value in b.
    effect = 2 * u / (len(a) * len(b)) - 1
    return {
        "u": float(u),
        "p": float(p),
        "effect_size": float(effect),
        "median_1": float(np.median(a)),
        "median_2": float(np.median(b)),
        "n1": len(a),
        "n2": len(b),
    }


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion.

    Preferred over the normal approximation because it behaves at proportions
    near 0 and 1 and in small samples, both of which occur in the borough-level
    breakdowns.
    """
    if total == 0:
        return (float("nan"), float("nan"))
    p = successes / total
    denom = 1 + z ** 2 / total
    centre = (p + z ** 2 / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z ** 2 / (4 * total ** 2)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def proportion_difference(s1: int, n1: int, s2: int, n2: int) -> dict:
    """Two-proportion z-test with a confidence interval on the difference."""
    if n1 == 0 or n2 == 0:
        return {"difference": float("nan"), "p": float("nan"),
                "ci": (float("nan"), float("nan"))}
    p1, p2 = s1 / n1, s2 / n2
    pooled = (s1 + s2) / (n1 + n2)
    se_pooled = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    z = (p1 - p2) / se_pooled if se_pooled else float("nan")
    se_diff = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    return {
        "p1": p1,
        "p2": p2,
        "difference": p1 - p2,
        "z": z,
        "p": float(2 * stats.norm.sf(abs(z))) if se_pooled else float("nan"),
        "ci": (p1 - p2 - 1.96 * se_diff, p1 - p2 + 1.96 * se_diff),
    }
