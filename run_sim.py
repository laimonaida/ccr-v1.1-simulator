"""Run the CCR aggregation-behaviour simulator on 1000 synthetic inputs.

Each run uses RANDOM parameters, so the behaviour (up-trend / down-trend /
ranging / late decision / no decision) emerges and is not known in advance.
The figure carries no explanatory or predictive text: only the dominance
trajectory over the inputs, with each oscillating phase shaded as a resistance
(red) or support (green) band. Support vs resistance is decided from the data
after the fact: a phase entered from below is resistance, from above support.
"""

import os
import sys
import random
import subprocess
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from aggregation_behavior_sim import make_inputs, simulate

N = 1000
DECIDE = 5
OSC = 0.30
NUM_RUNS = 4
GREEN, RED, NAVY = "#2C6E52", "#B03A2E", "#1F3864"


def open_file(path):
    try:
        if sys.platform.startswith("linux"):
            subprocess.Popen(["xdg-open", path],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
    except Exception as e:
        print("could not auto-open:", e)


def random_inputs():
    """Random parameters -> unpredictable behaviour every run."""
    return dict(
        bias=random.uniform(-0.17, 0.17),
        dominant_prob=random.uniform(0.018, 0.035),
        dominant_when=random.choice(["spread", "spread", "spread", "late", "early"]),
        dominant_align=random.uniform(0.60, 0.82),
        relevance_prob=random.uniform(0.55, 0.90),  # pre-processing filter: keep 55-90% of inputs
    )


def phases_of(anchors):
    ph = []; s = 0
    for i in range(1, len(anchors)):
        if anchors[i] != anchors[i - 1]:
            ph.append([s, i - 1, int(anchors[i - 1])]); s = i
    ph.append([s, len(anchors) - 1, int(anchors[-1])])
    out = []
    for i, (a, b, lvl) in enumerate(ph):
        if i > 0:
            kind = "resistance" if lvl > ph[i - 1][2] else "support"
        elif len(ph) > 1:
            kind = "resistance" if ph[1][2] > lvl else "support"
        else:
            kind = "resistance"
        out.append((a, b, lvl, kind))
    return out


def plot_run(r, ins, path):
    sp = r.params["spacing"]; B = r.params["band"]; DEC = r.params["decide_level"]
    n_all = len(ins)
    # keep only the inputs that passed the relevance filter, and re-index the
    # x-axis to those (so it runs 1 .. number-passed, e.g. 866). Dropped inputs
    # changed nothing, so removing their held points just compresses the flats.
    rel = r.relevance
    keep_pos = [0] + [i + 1 for i in range(n_all) if rel[i]]
    traj = r.traj[keep_pos]
    anchors = r.anchors[keep_pos]
    kept = len(traj) - 1
    x = range(len(traj))
    fig, ax = plt.subplots(figsize=(12.5, 4.8))
    lo = float(traj.min()) - 1.1 * sp
    hi = float(traj.max()) + 1.1 * sp
    # decision zones (structural shading only, no text)
    if DEC * sp < hi:
        ax.axhspan(DEC * sp, hi, color=GREEN, alpha=0.06)
    if -DEC * sp > lo:
        ax.axhspan(lo, -DEC * sp, color=RED, alpha=0.06)
    # each oscillating phase = one resistance (red) or support (green) band
    for (a, b, lvl, kind) in phases_of(anchors):
        if b - a < 12:
            continue
        c = lvl * sp
        col = RED if kind == "resistance" else GREEN
        ax.add_patch(Rectangle((a, c - B), b - a, 2 * B, facecolor=col, alpha=0.14,
                               edgecolor="none", zorder=1))
        ax.plot([a, b], [c + B, c + B], color=col, lw=0.9, zorder=2)
        ax.plot([a, b], [c - B, c - B], color=col, lw=0.9, zorder=2)
    ax.plot(x, traj, "-", color=NAVY, lw=0.8, zorder=3)
    ax.set_ylim(lo, hi); ax.set_xlim(0, kept)
    ax.set_yticks([])
    ax.set_xlabel(f"inputs that passed the filter  (D1 ... D{kept})", fontsize=9)
    ax.set_ylabel("dominance", fontsize=9)
    for s in ["top", "right"]:
        ax.spines[s].set_visible(False)

    # stats of passed vs dropped inputs, below the chart (counts only)
    passed = sum(1 for p in ins if p.relevant)
    dropped = n_all - passed
    fig.subplots_adjust(bottom=0.24)
    fig.text(0.5, 0.09, f"Passed the filter:  {passed} / {n_all}  ({100*passed/n_all:.1f}%)",
             ha="center", fontsize=11, color=GREEN)
    fig.text(0.5, 0.03, f"Did not pass:  {dropped} / {n_all}  ({100*dropped/n_all:.1f}%)",
             ha="center", fontsize=11, color=RED)
    plt.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)


def main():
    out_dir = os.path.join(os.path.dirname(__file__), "outputs")
    os.makedirs(out_dir, exist_ok=True)
    for i in range(1, NUM_RUNS + 1):
        seed = random.randrange(1_000_000)
        ins = make_inputs(N, seed=seed, **random_inputs())
        r = simulate(ins, decide_level=DECIDE, osc_speed=OSC, seed=seed)
        path = os.path.join(out_dir, f"sim_run_{i}.png")
        plot_run(r, ins, path)
        kept = int(r.relevance.sum())
        print(f"run {i}: saved {path}  (kept {kept}/{N} inputs)")
        open_file(path)


if __name__ == "__main__":
    main()
