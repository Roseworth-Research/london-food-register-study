"""
Step 40 -- every figure that appears in the published papers, drawn from the
frozen database so that a chart can never drift from the number beside it.

Paper 0 figures go to out/charts/paper0, Paper 1 figures to out/charts/paper1.
Values are read from the database or from the analysis CSVs rather than typed
in, with two exceptions noted in the code where a series is small and the
source log is the only artefact.
"""

from __future__ import annotations

import csv, json, os, sys
import duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

import config
import survival as sv

ROOT = str(config.ROOT) if hasattr(config, "ROOT") else "."
D0 = str(config.OUT / "paper0_charts")
D1 = str(config.OUT / "paper1_charts")
os.makedirs(D0, exist_ok=True)
os.makedirs(D1, exist_ok=True)

INK = "#1a1a1a"; GREY = "#5a5a5a"; GRID = "#e3ddd3"; NAVY = "#0B1E39"
# Palette: navy for service formats, azure for counter formats.
SERVICE = "#1A3C6E"; COUNTER = "#00A6E6"; RED = "#C8483D"
GREEN = "#8EC5E3"; VIOLET = "#D9922E"; AMBER = "#D9922E"

plt.rcParams.update({
    "svg.fonttype": "path",
    "font.family": "Segoe UI", "font.size": 10, "text.color": INK,
    "axes.edgecolor": GRID, "axes.labelcolor": GREY, "axes.titlesize": 11,
    "axes.titleweight": "bold", "axes.titlecolor": NAVY,
    "xtick.color": GREY, "ytick.color": GREY, "figure.facecolor": "white",
})
def save(fig, path) -> None:
    """Write each chart twice: PNG for screens, SVG (text as outlines) for print."""
    path = str(path)
    fig.savefig(path)
    fig.savefig(path[:-4] + ".svg")


def style(ax, axis="y"):
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GRID)
    ax.grid(axis=axis, color=GRID, linewidth=0.7); ax.set_axisbelow(True)

con = duckdb.connect(str(config.DB_PATH), read_only=True)
YEARS = list(range(2018, 2026))

# ── Paper 0 · 1 · formations vs removals ────────────────────────────
F = {(y, f): n for y, f, n in con.execute("""
    SELECT year(born), format, count(*) FROM companies
    WHERE year(born) BETWEEN 2018 AND 2025 AND format IN ('counter','service')
    GROUP BY 1,2""").fetchall()}
D = {(y, f): n for y, f, n in con.execute("""
    SELECT year(died), format, count(*) FROM companies
    WHERE year(died) BETWEEN 2018 AND 2025 AND format IN ('counter','service')
      AND outcome IN ('dead','failing') GROUP BY 1,2""").fetchall()}
forms = [F.get((y,"counter"),0)+F.get((y,"service"),0) for y in YEARS]
disss = [D.get((y,"counter"),0)+D.get((y,"service"),0) for y in YEARS]
cshare = [100*F.get((y,"counter"),0)/max(1,F.get((y,"counter"),0)+F.get((y,"service"),0)) for y in YEARS]

fig, ax = plt.subplots(figsize=(6.9, 3.2), dpi=200)
w = 0.38
ax.bar([y-w/2 for y in YEARS], forms, w, color=SERVICE, label="Companies formed")
ax.bar([y+w/2 for y in YEARS], disss, w, color="#b9b2a6", label="Companies removed")
ax.set_title("Formations have outpaced removals in every year")
ax.legend(frameon=False, fontsize=9)
ax.yaxis.set_major_formatter(FuncFormatter(lambda v,_: f"{int(v):,}"))
style(ax); fig.tight_layout(); save(fig, f"{D0}/c1_form_vs_remove.png"); plt.close(fig)

# ── Paper 0 · 2 · counter share ─────────────────────────────────────
fig, ax = plt.subplots(figsize=(6.9, 3.0), dpi=200)
ax.plot(YEARS, cshare, color=COUNTER, linewidth=2.2, marker="o", markersize=4)
ax.axvspan(2020, 2020.99, color="#f3efe8", zorder=0)
ax.annotate("2020: the step", xy=(2020.5, cshare[2]), xytext=(2021.4, cshare[2]+1.6),
            fontsize=9, color=GREY, arrowprops=dict(arrowstyle="-", color=GREY, lw=0.8))
ax.set_ylim(35, 50)
ax.set_title("Takeaway & bakery share of new formations stepped up in 2020, and stayed up")
ax.yaxis.set_major_formatter(FuncFormatter(lambda v,_: f"{v:.0f}%"))
style(ax); fig.tight_layout(); save(fig, f"{D0}/c2_counter_share.png"); plt.close(fig)

# ── Paper 0 · 3 · exit routes ───────────────────────────────────────
fam = con.execute("""
    SELECT year(c.died),
      sum(CASE WHEN e.exit_route='registrar_strike_off' THEN 1 ELSE 0 END),
      sum(CASE WHEN e.exit_route='voluntary_strike_off' THEN 1 ELSE 0 END),
      sum(CASE WHEN e.exit_family='insolvency' THEN 1 ELSE 0 END),
      sum(CASE WHEN e.exit_family='solvent_winding_up' THEN 1 ELSE 0 END)
    FROM companies c JOIN company_exit_v2 e USING (company_number)
    WHERE year(c.died) BETWEEN 2018 AND 2025 GROUP BY 1 ORDER BY 1""").fetchall()
ys = [r[0] for r in fam]
fig, ax = plt.subplots(figsize=(6.9, 3.3), dpi=200)
b0 = [0]*len(ys)
for idx, col, lab in ((1, SERVICE, "Struck off by Companies House"),
                      (2, GREEN, "Struck off on directors’ own application"),
                      (3, RED, "Insolvency procedures"),
                      (4, VIOLET, "Solvent members’ winding-up")):
    vals = [r[idx] for r in fam]
    ax.bar(ys, vals, 0.62, bottom=b0, color=col, label=lab)
    b0 = [a+b for a, b in zip(b0, vals)]
ax.set_title("How companies left the register: strike-off dominates, insolvency is the sliver")
ax.legend(frameon=False, fontsize=8.2, ncol=2)
ax.yaxis.set_major_formatter(FuncFormatter(lambda v,_: f"{int(v):,}"))
style(ax); fig.tight_layout(); save(fig, f"{D0}/c3_routes.png"); plt.close(fig)

# ── Paper 0 · 4 · pre-deadline share ────────────────────────────────
pre = con.execute("""
    SELECT year(died), count(*),
      sum(CASE WHEN accounts_last_made_up IS NULL
        AND NOT EXISTS (SELECT 1 FROM accounts a WHERE a.company_number=c.company_number)
        AND lifespan_days < 638 THEN 1 ELSE 0 END)
    FROM companies c WHERE year(died) BETWEEN 2018 AND 2025
      AND outcome IN ('dead','failing') GROUP BY 1 ORDER BY 1""").fetchall()
fig, ax = plt.subplots(figsize=(6.9, 3.2), dpi=200)
xs = [r[0] for r in pre]
ys = [100*r[2]/max(1, r[1]) for r in pre]
ax.plot(xs, ys, color=NAVY, linewidth=2.2, marker="o", markersize=4)
for x, y in zip(xs, ys):
    ax.annotate(f"{y:.0f}%", (x, y), textcoords="offset points", xytext=(0, 7),
                ha="center", fontsize=8, color=NAVY, fontweight="bold")
# The axis must contain every point: derived from the data, never fixed.
ax.set_ylim(0, max(60, 10 * (int(max(ys)) // 10 + 1)))
y20, y22 = ys[xs.index(2020)], ys[xs.index(2022)]
ax.annotate("strike-off action\npaused, 2020", (2020, y20), textcoords="offset points",
            xytext=(0, -30), ha="center", fontsize=7.5, color=GREY)
ax.annotate("catch-up, 2022", (2022, y22), textcoords="offset points",
            xytext=(38, 2), ha="left", fontsize=7.5, color=GREY)
ax.set_title("Share of removed companies that never reached their first accounts")
ax.yaxis.set_major_formatter(FuncFormatter(lambda v,_: f"{v:.0f}%"))
style(ax); fig.tight_layout(); save(fig, f"{D0}/c4_predeadline.png"); plt.close(fig)

# ── Paper 1 · rank flip ─────────────────────────────────────────────
rows = list(csv.DictReader(open(config.OUT / "rank_reversal_survival_3y.csv", encoding="utf-8")))
rows.sort(key=lambda r: int(r["rank_A_as_registered"]))
fig, ax = plt.subplots(figsize=(6.4, 6.2), dpi=200)
for r in rows:
    a, b = int(r["rank_A_as_registered"]), int(r["rank_B_single_company"])
    moved = abs(a-b) >= 5
    col = COUNTER if moved else "#c9c2b6"
    ax.plot([0,1], [a,b], color=col, linewidth=2.1 if moved else 1.1, zorder=3 if moved else 1)
    ax.scatter([0,1], [a,b], color=col, s=22 if moved else 12, zorder=4)
    ax.text(-0.045, a, r[""], ha="right", va="center", fontsize=8,
            color=INK if moved else GREY, weight="bold" if moved else "normal")
    ax.text(1.045, b, r[""], ha="left", va="center", fontsize=8,
            color=INK if moved else GREY, weight="bold" if moved else "normal")
ax.set_xlim(-0.62, 1.62); ax.invert_yaxis(); ax.axis("off")
ax.text(0, -1.2, "As registered", ha="center", fontsize=10, weight="bold", color=NAVY)
ax.text(1, -1.2, "Single-company addresses", ha="center", fontsize=10, weight="bold", color=NAVY)
ax.set_title("Borough rank on three-year register survival, under two readings of the\nsame data (orange = moved five places or more)", pad=26)
fig.tight_layout(); save(fig, f"{D1}/p1_rank_flip.png"); plt.close(fig)

# ── Paper 1 · survival curves ───────────────────────────────────────
df = con.execute("""
    SELECT format, lifespan_days, (outcome IN ('dead','failing')) AS event
    FROM companies WHERE birth_era='cost_of_living' AND lifespan_days >= 0
      AND format IN ('counter','service')""").df()
fig, ax = plt.subplots(figsize=(6.4, 3.3), dpi=200)
surv3 = {}
for f, col, lab in (("service", SERVICE, "Restaurant & café formats"),
                    ("counter", COUNTER, "Takeaway & bakery formats")):
    s = df[df.format == f]
    km = sv.kaplan_meier(s.lifespan_days.tolist(), s.event.tolist())
    surv3[f] = 100*km.survival_at(1095)
    xs = list(range(0, 1130, 10))
    ax.plot([x/365.25 for x in xs], [100*km.survival_at(x) for x in xs],
            color=col, linewidth=2.3, label=lab)
    ax.scatter([1095/365.25], [surv3[f]], color=col, s=26, zorder=5)
    ax.annotate(f"{surv3[f]:.1f}%", xy=(1095/365.25, surv3[f]), xytext=(6,-2),
                textcoords="offset points", fontsize=9, color=col, weight="bold")
ax.set_xlabel("Years since incorporation"); ax.set_ylim(30, 101); ax.set_xlim(0, 3.35)
ax.yaxis.set_major_formatter(FuncFormatter(lambda v,_: f"{v:.0f}%"))
ax.legend(frameon=False, fontsize=9, loc="lower left")
ax.set_title("Companies remaining on the register, incorporated since April 2022")
style(ax); fig.tight_layout(); save(fig, f"{D1}/p1_survival.png"); plt.close(fig)

# ── Paper 1 · robustness forest ─────────────────────────────────────
labels = {"baseline (as specified)": "As specified",
          "premises-confirmed only [SELECTED subset]": "Premises-confirmed only*",
          "56102 reassigned to counter (extreme reading)": "Cafés counted as counter†",
          "56102 dropped entirely": "Excluding cafés",
          "47240 dropped entirely": "Excluding bakeries",
          "era start a quarter earlier (2022-01-01)": "Era start one quarter earlier",
          "era start a quarter later (2022-07-01)": "Era start one quarter later"}
rb = list(csv.DictReader(open(config.OUT / "robustness_extra.csv", encoding="utf-8")))
items = [(labels.get(r["run"], r["run"]), float(r["gap_pp"])) for r in rb][::-1]
fig, ax = plt.subplots(figsize=(6.4, 3.0), dpi=200)
yy = range(len(items))
ax.hlines(list(yy), [0]*len(items), [i[1] for i in items], color="#c9c2b6", linewidth=1.6)
ax.scatter([i[1] for i in items], list(yy), color=COUNTER, s=44, zorder=4)
for y, (lab, v) in zip(yy, items):
    ax.text(v-0.35, y, f"{v:.1f}", va="center", ha="right", fontsize=8.6, weight="bold")
ax.set_yticks(list(yy)); ax.set_yticklabels([i[0] for i in items], fontsize=9)
ax.axvline(0, color=GREY, linewidth=1)
ax.set_xlim(-11, 1.2); ax.set_xlabel("Difference in three-year survival, percentage points")
ax.set_title("The gap under seven specifications: negative throughout")
style(ax, axis="x"); fig.tight_layout(); save(fig, f"{D1}/p1_robustness.png"); plt.close(fig)

# ── Paper 1 · blind spot (establishment level, from the linkage file) ─
bl = [("Takeaway / sandwich shop", 65.3, 61.3), ("Restaurant, café or canteen", 54.1, 48.4),
      ("Mobile caterer", 52.5, 41.0), ("Other catering premises", 26.7, 22.6),
      ("Manufacturers & packers", 16.6, 14.9), ("Other retailers", 6.9, 6.2)]
fig, ax = plt.subplots(figsize=(6.4, 3.2), dpi=200)
yy = list(range(len(bl)))[::-1]; h = 0.34
for y, (lab, food, coh) in zip(yy, bl):
    ax.barh(y+h/2, food, h, color="#b7d3f6")
    ax.barh(y-h/2, coh, h, color=SERVICE)
    ax.text(coh+1.2, y-h/2, f"{coh:.1f}%", va="center", fontsize=8.4)
ax.set_yticks(yy); ax.set_yticklabels([b[0] for b in bl], fontsize=9)
ax.set_xlim(0, 78); ax.set_xlabel("Per cent of resolved establishments")
ax.legend(handles=[plt.Rectangle((0,0),1,1,color="#b7d3f6"), plt.Rectangle((0,0),1,1,color=SERVICE)],
          labels=["Operator carries a food classification", "Operator inside this study's cohort"],
          frameon=False, fontsize=8.6, loc="lower right")
ax.set_title("How much of the real food economy a register-defined study sees")
style(ax, axis="x"); fig.tight_layout(); save(fig, f"{D1}/p1_blindspot.png"); plt.close(fig)

# ── Paper 1 · balance sheets ────────────────────────────────────────
st = list(csv.DictReader(open(config.OUT / "structure_yoy.csv", encoding="utf-8")))
cols = {"56101": SERVICE, "56102": GREEN, "56103": COUNTER, "47240": AMBER}
names = {"56101": "Licensed restaurants", "56102": "Unlicensed restaurants & cafés",
         "56103": "Takeaway & mobile food", "47240": "Bakery retail"}
fig, axes = plt.subplots(1, 2, figsize=(6.6, 2.9), dpi=200)
for sic in cols:
    rs = sorted([r for r in st if r["sic"] == sic], key=lambda r: int(r["financial_year"]))
    yrs = [int(r["financial_year"]) for r in rs]
    axes[0].plot(yrs, [float(r["median_cash_share"]) for r in rs], color=cols[sic],
                 linewidth=2, marker="o", markersize=3, label=names[sic])
    axes[1].plot(yrs, [float(r["pct_negative_equity"]) for r in rs], color=cols[sic],
                 linewidth=2, marker="o", markersize=3)
axes[0].axvspan(2020, 2021, color="#f3efe8", zorder=0)
axes[0].set_title("Cash as a share of current assets", fontsize=10); axes[0].set_ylim(.28,.8)
axes[1].set_title("Filers with negative equity", fontsize=10); axes[1].set_ylim(15,32)
axes[1].yaxis.set_major_formatter(FuncFormatter(lambda v,_: f"{v:.0f}%"))
for a in axes: style(a); a.tick_params(labelsize=8.5)
axes[0].legend(frameon=False, fontsize=7.4, loc="upper left")
fig.tight_layout(); save(fig, f"{D1}/p1_balance.png"); plt.close(fig)

# ── Paper 1 · address timing ────────────────────────────────────────
at = list(csv.DictReader(open(config.OUT / "address_timing.csv", encoding="utf-8")))
n = len(at)
never = sum(1 for r in at if int(r["n_moves"]) == 0)
after = sum(1 for r in at if int(r["moves_before"]) == 0 and int(r["moves_after"]) > 0)
both = sum(1 for r in at if int(r["moves_before"]) > 0 and int(r["moves_after"]) > 0)
before = sum(1 for r in at if int(r["moves_before"]) > 0 and int(r["moves_after"]) == 0)
segs = [("Moved only once insolvency had begun", after, RED),
        ("Moved both before and after", both, "#ec835a"),
        ("Moved only before insolvency", before, SERVICE),
        ("Never moved", never, "#c9c2b6")]
fig, ax = plt.subplots(figsize=(6.4, 1.75), dpi=200)
left = 0
for lab, v, col in segs:
    ax.barh([0], [100*v/n], left=left, height=.5, color=col)
    if 100*v/n > 6:
        ax.text(left+100*v/n/2, 0, f"{100*v/n:.1f}%", ha="center", va="center",
                color="white", fontsize=9.5, weight="bold")
    left += 100*v/n
ax.set_xlim(0,100); ax.set_ylim(-.6,.9); ax.axis("off")
ax.legend(handles=[plt.Rectangle((0,0),1,1,color=c) for _,_,c in segs],
          labels=[s[0] for s in segs], frameon=False, fontsize=8.2, ncol=2,
          loc="upper center", bbox_to_anchor=(.5,1.5))
ax.set_title(f"When the registered office moved, for {n:,} companies entering insolvency", pad=34)
fig.tight_layout(); save(fig, f"{D1}/p1_address_timing.png"); plt.close(fig)

json.dump({"forms": sum(forms), "removals": sum(disss),
           "cshare_2018": round(cshare[0],1), "cshare_2020": round(cshare[2],1),
           "cshare_2025": round(cshare[-1],1),
           "surv3_counter": round(surv3["counter"],1),
           "surv3_service": round(surv3["service"],1)},
          open(f"{D0}/meta.json", "w"))
con.close()
print("charts rebuilt |", f"survival {surv3['counter']:.1f} vs {surv3['service']:.1f}",
      f"| formations {sum(forms):,} removals {sum(disss):,}")
