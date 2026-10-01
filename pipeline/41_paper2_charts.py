"""
Step 41 -- the charts for Paper 2, The Boundary.

The chain figures are read from out/chain_vat_model.csv (step 13) so a chart
cannot drift from the model. The Greggs scenario range, the rate history and
the delivery illustration are small typed series, each with its source noted
beside it; the delivery chart is an illustration on stated assumptions, not a
measurement, and is captioned as such in the paper.
"""
from __future__ import annotations

import csv
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import config

OUT = config.OUT / "charts" / "paper2"
os.makedirs(OUT, exist_ok=True)

NAVY = "#0B1E39"; SERVICE = "#1A3C6E"; COUNTER = "#00A6E6"; GREY = "#5a5a5a"
GRID = "#e3ddd3"; RED = "#C8483D"; LIGHT = "#8EC5E3"; AMBER = "#D9922E"
plt.rcParams.update({
    "svg.fonttype": "path",
    "font.family": "Segoe UI", "font.size": 10, "text.color": "#1a1a1a",
    "axes.edgecolor": GRID, "axes.labelcolor": GREY, "axes.titlesize": 11,
    "axes.titleweight": "bold", "axes.titlecolor": NAVY,
    "xtick.color": GREY, "ytick.color": GREY, "figure.facecolor": "white",
})


def save(fig, path) -> None:
    """Write each chart twice: PNG for screens, SVG (text as outlines) for print."""
    path = str(path)
    fig.savefig(path)
    fig.savefig(path[:-4] + ".svg")


def style(ax, axis="x"):
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GRID)
    ax.grid(axis=axis, color=GRID, linewidth=0.7)
    ax.set_axisbelow(True)


# ── 1 · the £10 test, latest year per chain ─────────────────────────
latest: dict[str, tuple[str, float]] = {}
with open(config.OUT / "chain_vat_model.csv", encoding="utf-8") as fh:
    for r in csv.DictReader(fh):
        if "stub" in r["financial_year"]:
            continue
        prev = latest.get(r["chain"])
        if prev is None or r["year_end"] > prev[0]:
            latest[r["chain"]] = (r["year_end"], float(r["kept_per_10_consumer_spend"]))
short = {"Costa Limited": "Costa", "Greggs plc": "Greggs",
         "Pret A Manger (Europe) Limited": "Pret A Manger"}
rows = [("Wholly standard-rated restaurant", 10 / 1.2, SERVICE)]
for chain, (_, kept) in sorted(latest.items(), key=lambda kv: kv[1][1]):
    name = short.get(chain, "Gail’s" if "Gail" in chain or "Grain" in chain or "Bread" in chain else chain)
    rows.append((name, kept, COUNTER))
rows.append(("Wholly zero-rated counter", 10.0, LIGHT))
fig, ax = plt.subplots(figsize=(6.9, 3.4), dpi=200)
ys = list(range(len(rows)))[::-1]
for y, (lab, v, c) in zip(ys, rows):
    ax.barh(y, v, color=c, height=0.62)
    x = 9.34 if lab == "Greggs" else v
    ax.text(x + 0.04, y, f"£{v:.2f}", va="center", fontsize=9, color=NAVY, fontweight="bold")
gy = ys[[r[0] for r in rows].index("Greggs")]
ax.plot([8.82, 9.34], [gy, gy], color=AMBER, linewidth=3, solid_capstyle="butt")
ax.text(8.84, gy + 0.42, "cooling-rule scenarios: up to £9.34", fontsize=7.5, color=AMBER)
ax.set_yticks(ys, [r[0] for r in rows], fontsize=9)
ax.set_xlim(7.5, 10.6)
ax.set_xlabel("Kept from every £10 of consumer spending, after output VAT (modelled)")
ax.set_title("The £10 test: real counter operators sit near the restaurant")
style(ax)
fig.tight_layout(); save(fig, OUT / "p2_ten_pound_test.png"); plt.close(fig)

# ── 2 · width of the boundary since 1984 ────────────────────────────
# Standard rate history: HMRC / House of Commons Library SN05620. Eat-in
# reduced rate 15 Jul 2020 - 31 Mar 2022: VAT (Reduced Rate) (Hospitality and
# Tourism) Orders. Cold takeaway food: zero-rated throughout.
steps = [(1984.33, 15.0), (1991.25, 17.5), (2008.92, 15.0), (2010.0, 17.5),
         (2011.01, 20.0), (2026.75, 20.0)]
eat_in = [(1984.33, 15.0), (1991.25, 17.5), (2008.92, 15.0), (2010.0, 17.5),
          (2011.01, 20.0), (2020.54, 5.0), (2021.75, 12.5), (2022.25, 20.0), (2026.75, 20.0)]
fig, ax = plt.subplots(figsize=(6.9, 2.9), dpi=200)
xs = [s[0] for s in eat_in]; vs = [s[1] for s in eat_in]
ax.step(xs, vs, where="post", color=SERVICE, linewidth=2.2, label="Eat-in and hot takeaway (catering)")
ax.axhline(0, color=COUNTER, linewidth=2.2, label="Cold takeaway food (zero-rated)")
ax.fill_between(xs, vs, step="post", color=SERVICE, alpha=0.08)
ax.axvspan(2020.54, 2022.25, color=AMBER, alpha=0.12)
ax.text(2020.3, 9, "pandemic relief", fontsize=7.5, color=AMBER, ha="right")
ax.set_ylim(-1.5, 24); ax.set_xlim(1983, 2027)
ax.set_ylabel("VAT rate, %")
ax.set_title("The width of the boundary: 15 points in 1984, 20 only since 2011")
ax.legend(frameon=False, fontsize=8, loc="lower left", bbox_to_anchor=(0, 0.08))
style(ax, axis="y")
fig.tight_layout(); save(fig, OUT / "p2_boundary_history.png"); plt.close(fig)

# ── 3 · the delivery stack, worked illustration ─────────────────────
# £10 VAT-inclusive basket of hot food; commission taken on the inclusive
# basket at 30% (reported tiers run to 35%); VAT on the commission is
# recoverable by a registered restaurant and so excluded.
price = 10.0; vat = price / 6; commission = 0.30 * price
kept = price - vat - commission
fig, ax = plt.subplots(figsize=(6.9, 2.9), dpi=200)
left = 0
for lab, v, c in (("Kept by the kitchen", kept, SERVICE), ("Output VAT", vat, RED),
                  ("Commission, 30% tier", commission, AMBER)):
    ax.barh(0, v, left=left, color=c, height=0.5)
    ax.text(left + v / 2, 0, f"£{v:.2f}", ha="center", va="center", fontsize=8.6, color="white", fontweight="bold")
    ax.text(left + v / 2, -0.36, lab, ha="center", va="top", fontsize=7.4, color=GREY)
    left += v
for y, (lab, v) in zip((1, 2), (("Cold item over the counter", 10.0), ("Same meal eaten in", price - vat))):
    ax.barh(y, v, color=LIGHT if y == 1 else SERVICE, height=0.5, alpha=0.9 if y == 1 else 0.55)
    ax.text(v + 0.08, y, f"£{v:.2f}", va="center", fontsize=9, color=NAVY, fontweight="bold")
ax.set_yticks([0, 1, 2], ["Hot meal, delivered", "Cold item, counter", "Hot meal, eaten in"], fontsize=9)
ax.set_xlim(0, 11.2); ax.set_ylim(-0.95, 2.45)
ax.set_xlabel("£ of every £10 the customer pays (illustration, stated assumptions)")
ax.set_title("Delivery stacks a platform take on the most heavily taxed way to sell food")
style(ax)
fig.tight_layout(); save(fig, OUT / "p2_delivery_stack.png"); plt.close(fig)
print("paper 2 charts written to", OUT, "| delivered kept", round(kept, 2))
