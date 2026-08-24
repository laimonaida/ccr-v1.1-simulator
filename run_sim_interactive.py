"""Interactive version of the CCR aggregation-behaviour simulator.

Generates a random run (unpredictable behaviour) and writes an interactive HTML
chart: hover anywhere on the trajectory and the data pops up (input index,
dominance, the current resistance/support phase, and any breakout / decision at
that point). Opens in the browser. The figure itself carries no predictive text.
"""

import os
import sys
import random
import shutil
import subprocess
import plotly.graph_objects as go
from aggregation_behavior_sim import make_inputs, simulate

N = 1000
DECIDE = 5
OSC = 0.30
NUM_RUNS = 4
GREEN, RED, NAVY = "#2C6E52", "#B03A2E", "#1F3864"


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


def build(r, path):
    sp = r.params["spacing"]; DEC = r.params["decide_level"]
    rel = r.relevance
    n_all = len(rel)
    # keep only the inputs that passed the relevance filter, and re-index the
    # x-axis to those (so it runs 1 .. number-passed). Dropped inputs changed
    # nothing, so removing their held points just compresses the flats.
    keep_pos = [0] + [i + 1 for i in range(n_all) if rel[i]]
    traj = r.traj[keep_pos]
    anchors = r.anchors[keep_pos]
    bands = r.bands[keep_pos]        # per-step amplitude, so each phase has its own height
    pos_map = {orig: p for p, orig in enumerate(keep_pos)}
    kept = len(traj) - 1
    n = len(traj)

    phases = phases_of(anchors)
    kind_per = [""] * n
    for a, b, lvl, kind in phases:
        for i in range(a, b + 1):
            kind_per[i] = kind
    # per-point event text (breakout / decision) for the hover popup, remapped
    # onto the compressed (passed-only) x positions
    event = [""] * n
    for (idx, dom, lvl, kind) in r.breakouts:
        p = pos_map.get(idx + 1)
        if p is not None:
            event[p] = f"breakout ({kind}), dominance {dom:.2f}"
    if r.decided_at is not None:
        p = pos_map.get(r.decided_at + 1)
        if p is not None:
            event[p] = "converged: DECISION reached"
    customdata = list(zip(kind_per, event))

    yc = r.params.get("y_center", 0.0)
    yspan = r.params.get("y_span")
    fig = go.Figure()
    if yspan is not None:
        lo, hi = float(yspan[0]), float(yspan[1])
    else:
        lo = float(traj.min()) - 1.1 * sp
        hi = float(traj.max()) + 1.1 * sp
        if DEC * sp < hi:
            fig.add_hrect(y0=DEC * sp, y1=hi, fillcolor=GREEN, opacity=0.06, line_width=0, layer="below")
        if -DEC * sp > lo:
            fig.add_hrect(y0=lo, y1=-DEC * sp, fillcolor=RED, opacity=0.06, line_width=0, layer="below")
    for (a, b, lvl, kind) in phases:
        if b - a < 4:
            continue
        c = yc + lvl * sp
        Bp = float(bands[a])         # this phase's own amplitude
        col = RED if kind == "resistance" else GREEN
        fig.add_shape(type="rect", x0=a, x1=b, y0=c - Bp, y1=c + Bp, layer="below",
                      fillcolor=col, opacity=0.14, line_width=0)
        for y in (c + Bp, c - Bp):
            fig.add_shape(type="line", x0=a, x1=b, y0=y, y1=y, line=dict(color=col, width=1))
    # trajectory with rich hover
    fig.add_trace(go.Scatter(
        x=list(range(n)), y=list(traj), mode="lines",
        line=dict(color=NAVY, width=1), customdata=customdata,
        hovertemplate=("input %{x}<br>dominance %{y:.2f}"
                       "<br>phase: %{customdata[0]}"
                       "<br>%{customdata[1]}<extra></extra>")))
    # V1.1 output: converging (to either area) is a decision; only oscillation is no decision.
    is_decision = (r.decision == "decision")
    # mark WHERE it converged, on the graph itself
    if r.decided_at is not None:
        cp = pos_map.get(r.decided_at + 1)
        if cp is not None:
            cy = float(traj[cp])
            fig.add_shape(type="line", x0=cp, x1=cp, y0=lo, y1=hi,
                          line=dict(color="#555", width=1, dash="dash"), layer="below")
            fig.add_trace(go.Scatter(x=[cp], y=[cy], mode="markers",
                          marker=dict(symbol="star", size=15, color=GREEN,
                                      line=dict(color="white", width=1)),
                          hoverinfo="skip", showlegend=False))
            fig.add_annotation(x=cp, y=cy, text="converged", showarrow=True, arrowhead=2,
                               ax=0, ay=-34, font=dict(color=GREEN, size=12),
                               bgcolor="rgba(255,255,255,0.75)")
    # OUTPUT of the aggregation function, shown BELOW the graph only
    out_text = "Output:  decision" if is_decision else "Output:  no decision"
    out_color = GREEN if is_decision else "#6B6B6B"
    fig.add_annotation(xref="paper", yref="paper", x=0.5, y=-0.20, showarrow=False,
                       text=out_text, font=dict(color=out_color, size=19))
    # divider: separate the aggregation output from the pre-processing filter results
    fig.add_shape(type="line", xref="paper", yref="paper", x0=0.30, x1=0.70,
                  y0=-0.275, y1=-0.275, line=dict(color="#CCCCCC", width=1))
    # pre-processing filter results, under a labelled header
    fig.add_annotation(xref="paper", yref="paper", x=0.5, y=-0.335, showarrow=False,
                       text="Pre-processing filter", font=dict(color=NAVY, size=15))
    passed = int(rel.sum()); dropped = n_all - passed
    fig.add_annotation(xref="paper", yref="paper", x=0.5, y=-0.405, showarrow=False,
                       text=f"Passed the filter:  {passed} / {n_all}  ({100*passed/n_all:.1f}%)",
                       font=dict(color=GREEN, size=14))
    fig.add_annotation(xref="paper", yref="paper", x=0.5, y=-0.470, showarrow=False,
                       text=f"Did not pass:  {dropped} / {n_all}  ({100*dropped/n_all:.1f}%)",
                       font=dict(color=RED, size=14))
    fig.update_layout(
        template="plotly_white", height=780,
        margin=dict(l=60, r=30, t=30, b=270), showlegend=False,
        xaxis=dict(title=f"inputs that passed the filter (D1 ... D{kept})", range=[0, kept]),
        yaxis=dict(title="dominance", range=[lo, hi], showticklabels=False),
        hovermode="x unified")
    fig.write_html(path, include_plotlyjs="cdn", auto_open=False)


def open_file(path):
    """Open the HTML in a real web browser.

    NOTE: we do NOT use xdg-open here. On this machine the default handler for
    text/html is Thunderbird, so xdg-open would attach the file to a new email
    instead of opening it. We launch an actual browser directly.
    """
    url = "file://" + os.path.abspath(path)
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", url]); return
        if sys.platform.startswith("win"):
            os.startfile(path); return  # type: ignore[attr-defined]
        # Linux: prefer Chrome, then any real browser, never the generic default handler
        for b in ("google-chrome", "google-chrome-stable", "x-www-browser",
                  "chromium", "chromium-browser", "firefox"):
            exe = shutil.which(b)
            if exe:
                subprocess.Popen([exe, url],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                print("opened in", b)
                return
        import webbrowser
        webbrowser.open(url)
    except Exception as e:
        print("could not auto-open:", e)


def random_config():
    """Random parameters -> unpredictable behaviour with many, frequent phases.

    More phases come from (a) more dominant inputs and an easier breakout
    threshold, so levels change often, and (b) a higher decision threshold and
    weaker trend, so the run keeps oscillating instead of deciding early and
    freezing.
    """
    # dominance is a bounded score in [0, 100], centred at 50. Each phase samples
    # its own full height (amplitude) uniformly in [20, 50], so band (half-height)
    # is in [10, 25]. Spacing is one band_max, so a few clean levels stack inside
    # 0..100 and the trajectory reflects off the 0 and 100 walls.
    amp_min, amp_max = 10.0, 30.0
    band_min, band_max = amp_min / 2.0, amp_max / 2.0     # 5 .. 15
    spacing = band_max                                    # clean up/down breakouts within 0..100
    return dict(
        make=dict(
            bias=random.uniform(-0.06, 0.06),          # weak trend -> wanders, no fast march
            dominant_prob=random.uniform(0.07, 0.12),   # more dominant inputs -> more breakouts
            dominant_when=random.choice(["spread", "spread", "spread", "late", "early"]),
            dominant_align=random.uniform(0.45, 0.60),  # breakouts go both ways -> little net drift
            relevance_prob=random.uniform(0.55, 0.90),  # pre-processing filter: keep 55-90% of inputs
        ),
        sim=dict(
            spacing=spacing,
            band_range=(band_min, band_max),            # random per-phase amplitude, 20..50
            y_center=50.0, y_span=(0.0, 100.0),         # dominance bounded to 0..100
            break_thr=random.uniform(0.55, 0.85),       # easier breakouts -> more, more frequent phases
            decide_level=999,                            # not used; convergence is detected anywhere
            stable_window=random.randint(10, 20),        # end settled in one area (no breakout) this
                                                         # long to count as converged -> decision
            osc_speed=random.uniform(0.14, 0.22),       # fraction of the band per step
        ),
    )


def main():
    out_dir = os.path.join(os.path.dirname(__file__), "outputs")
    os.makedirs(out_dir, exist_ok=True)
    for i in range(1, NUM_RUNS + 1):
        seed = random.randrange(1_000_000)
        cfg = random_config()
        r = simulate(make_inputs(N, seed=seed, **cfg["make"]), seed=seed, **cfg["sim"])
        path = os.path.join(out_dir, f"sim_interactive_{i}.html")
        build(r, path)
        kept = int(r.relevance.sum()) if r.relevance is not None else N
        print(f"run {i}: saved {path}  (kept {kept}/{N} inputs, "
              f"breakouts={len(r.breakouts)}, decided={r.decision})")
        open_file(path)


if __name__ == "__main__":
    main()
