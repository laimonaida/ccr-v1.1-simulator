"""
CCR V1.1 - Node behaviour simulator (pre-processing filter + aggregation function).

This does NOT implement a specific aggregation function. It is an abstract oracle
that models the BEHAVIOUR of a CCR V1.1 node:

    n inputs (D1..Dn) -> pre-processing (relevance) filter -> aggregation function -> output

- Pre-processing (relevance) filter: each input is kept (relevant = 1) or dropped
  (relevant = 0); only kept inputs reach the aggregation function.
- Aggregation-function behaviour: the aggregated dominance moves along a trajectory
  in a bounded range (e.g. 0..100), like a price chart. It oscillates inside a phase
  (a support or resistance area) and BREAKS OUT to the next area only when a single
  input has enough dominance to cross a breakout threshold.
- Output (binary): if the trajectory CONVERGES (stays in the same area, with no
  breakout) for a window, the output is a decision; if it keeps oscillating between
  areas, the output is no decision. Convergence can happen in any area, not only the
  extremes.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Tuple
import numpy as np


@dataclass
class Inp:
    idx: int
    push: float        # signed = direction * dominance
    dominance: float   # magnitude in [0, ~1.7]
    dominant: bool     # True for the rare high-dominance ("dominant") evidence
    relevant: bool = True   # pre-processing (relevance) filter: 1 = kept, 0 = dropped


def make_inputs(n: int = 100, bias: float = 0.0, dominant_prob: float = 0.08,
                dominant_when: str = "spread", dominant_align: float = 0.85,
                relevance_prob: float = 1.0, seed: int = 0) -> List[Inp]:
    """Synthetic inputs.

    bias in [-0.5, 0.5] tilts the direction of the pushes (drives a trend).
    dominant_prob is the fraction of rare, high-dominance ("dominant") inputs;
        only these can cross the breakout threshold and end a phase.
    dominant_when: 'spread' | 'late' | 'early' controls when the dominant inputs
        occur (used to show order / time dependence).
    dominant_align: how strongly the dominant evidence follows the trend (bias)
        direction; these are the inputs that drive breakouts.
    relevance_prob: the per-node pre-processing (relevance) filter. Each input is
        independently kept (relevant = 1) with this probability, else dropped
        (relevant = 0) and never reaches aggregation. 1.0 keeps all.
    """
    rng = np.random.default_rng(seed)
    n_dom = max(1, int(round(n * dominant_prob)))
    if dominant_when == "late":
        pool = range(int(n * 0.6), n)
    elif dominant_when == "early":
        pool = range(0, int(n * 0.4))
    else:  # spread
        pool = range(n)
    dominant_slots = set(rng.choice(list(pool), size=min(n_dom, len(list(pool))), replace=False))

    trend = 1.0 if bias >= 0 else -1.0
    out: List[Inp] = []
    for i in range(n):
        dominant = i in dominant_slots
        if dominant:
            dom = rng.uniform(0.9, 1.7)
            if abs(bias) < 1e-9:
                direction = 1.0 if rng.random() < 0.5 else -1.0
            else:
                direction = trend if rng.random() < dominant_align else -trend
        else:
            dom = rng.uniform(0.02, 0.28)
            direction = 1.0 if rng.random() < (0.5 + bias) else -1.0
        relevant = bool(rng.random() < relevance_prob)
        out.append(Inp(i, direction * dom, dom, dominant, relevant))
    return out


@dataclass
class SimResult:
    traj: np.ndarray                    # dominance trajectory, length n+1
    anchors: np.ndarray                 # current support/resistance level per step
    breakouts: List[Tuple[int, float, int, str]]  # (input idx, dominance, new level, "dominant")
    decided_at: Optional[int]           # step index of the decision, or None
    decision: Optional[str]             # "decision" / None (no decision)
    levels_visited: List[int]
    params: dict
    relevance: Optional[np.ndarray] = None  # per-input 1 = kept / 0 = dropped by the filter
    bands: Optional[np.ndarray] = None      # per-step channel amplitude (phase height)


def simulate(inputs: List[Inp], *, spacing: float = 2.6, band: float = 0.95,
             band_range: Optional[Tuple[float, float]] = None,
             y_center: float = 0.0, y_span: Optional[Tuple[float, float]] = None,
             osc_speed: float = 0.30, push_gain: float = 0.05,
             break_thr: float = 1.25, decide_level: int = 3,
             stable_window: int = 6, noise: float = 0.03, seed: int = 0) -> SimResult:
    """Run the behaviour oracle over the inputs.

    The trajectory oscillates inside a phase (a level +/- band): it zig-zags edge to
    edge, touching the resistance line (top of the band) and the support line (bottom).
    A phase ends (a BREAKOUT to the next level) only when a single input's dominance
    crosses break_thr; inputs below the threshold just keep it oscillating.

    Output: the trajectory CONVERGES when it stays at the same level (no breakout) for
    stable_window inputs after having moved at least once; that is a decision. If it
    keeps breaking out until the inputs run out, there is no decision.

    band_range: if given, each phase samples its own amplitude in this range.
    y_center / y_span: if given, the trajectory is centred at y_center and bounded to
        y_span (e.g. 0..100); breakouts that would leave the range are blocked.
    """
    rng = np.random.default_rng(seed + 1)
    rng_b = np.random.default_rng(seed + 2)   # separate stream for per-phase amplitude

    def _band() -> float:
        # each phase gets its own amplitude when band_range is given; else a fixed band.
        return float(rng_b.uniform(band_range[0], band_range[1])) if band_range else band

    # if a y_span (e.g. 0..100) is given, bound the levels so the whole trajectory
    # (a channel is centre +/- band) stays inside the span; blocked breakouts reflect.
    band_max = band_range[1] if band_range else band
    if y_span is not None:
        amin = int(np.ceil((y_span[0] + band_max - y_center) / spacing))
        amax = int(np.floor((y_span[1] - band_max - y_center) / spacing))
        if amin > 0: amin = 0
        if amax < 0: amax = 0
    else:
        amin, amax = -10**9, 10**9

    anchor = 0            # current level index (integer * spacing)
    cur_band = _band()   # amplitude of the current channel
    o = 0.0              # position within the channel, in [-cur_band, cur_band]
    d = 1.0              # intra-channel zig-zag direction
    x = y_center
    traj = [x]; anch = [0]; bands = [cur_band]
    breakouts: List[Tuple[int, float, int, str]] = []
    decided_at: Optional[int] = None
    decision: Optional[str] = None
    stable = 0
    relevance: List[int] = []
    for inp in inputs:
        if not inp.relevant:
            # dropped by the pre-processing (relevance) filter: it never reaches
            # aggregation, so nothing updates and the trajectory holds flat.
            relevance.append(0)
            traj.append(x); anch.append(anchor); bands.append(cur_band)
            continue
        relevance.append(1)
        # a phase ends only when a SINGLE input has enough dominance to cross the
        # breakout threshold; inputs below the threshold just keep it oscillating.
        # the FULL trajectory always runs (no early freeze).
        prev_anchor = anchor
        if inp.push > break_thr and anchor + 1 <= amax:
            anchor += 1
            cur_band = _band()         # new phase, new random amplitude
            o = -cur_band * 0.6        # jump into the low of the new channel
            d = 1.0
            breakouts.append((inp.idx, inp.dominance, anchor, "dominant"))
        elif inp.push < -break_thr and anchor - 1 >= amin:
            anchor -= 1
            cur_band = _band()
            o = cur_band * 0.6
            d = -1.0
            breakouts.append((inp.idx, inp.dominance, anchor, "dominant"))
        else:
            # consolidation: zig-zag across the channel, bouncing off the edges.
            # the step scales with the phase amplitude so tall and short phases both
            # fill their band in a similar number of steps.
            o += osc_speed * cur_band * d + push_gain * inp.push + rng.normal(0, noise)
            if o >= cur_band:
                o = cur_band; d = -1.0     # bounce down off the resistance line
            elif o <= -cur_band:
                o = -cur_band; d = 1.0     # bounce up off the support line
        x = y_center + anchor * spacing + o
        traj.append(x); anch.append(anchor); bands.append(cur_band)
        # convergence is judged from the END state of the whole trajectory: staying in
        # the same area (no breakout) for stable_window inputs is a decision. A later
        # breakout (it moved again) voids an earlier convergence, so a run that is still
        # oscillating at the end has no decision.
        if anchor != prev_anchor:
            stable = 0
            decided_at = None; decision = None
        else:
            stable += 1
            if decided_at is None and stable >= stable_window:
                decided_at = inp.idx
                decision = "decision"
    return SimResult(np.array(traj), np.array(anch), breakouts,
                     decided_at, decision, sorted(set(anch)),
                     dict(spacing=spacing, band=band, band_range=band_range,
                          y_center=y_center, y_span=y_span, osc_speed=osc_speed,
                          break_thr=break_thr, decide_level=decide_level,
                          stable_window=stable_window),
                     relevance=np.array(relevance), bands=np.array(bands))


if __name__ == "__main__":
    # quick self-check
    ins = make_inputs(1000, bias=0.0, dominant_prob=0.1, relevance_prob=0.7, seed=1)
    r = simulate(ins, band_range=(5, 15), y_center=50.0, y_span=(0.0, 100.0),
                 break_thr=0.7, stable_window=30, osc_speed=0.18, seed=1)
    print("decision:", r.decision, "at", r.decided_at,
          "| breakouts:", len(r.breakouts),
          "| kept:", int(r.relevance.sum()), "/", len(r.relevance))
