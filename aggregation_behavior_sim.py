"""
CCR V1.1 - Aggregation-function BEHAVIOR simulator.

This does NOT implement a specific aggregation function (no two-expert rule, no
library). It is an abstract oracle that models the *behaviour* of an aggregation
function: as filtered inputs (beliefs/evidence with a dominance) arrive one by
one, the "decision" moves along a trajectory - like a price chart with support
and resistance areas, momentum, breakouts, and convergence to a decision
(a fixed point) or continued oscillation (no decision yet).

Concepts implemented
--------------------
- decision trajectory x(t): a scalar that moves as inputs arrive.
- support / resistance levels: an integer grid; x oscillates inside a band
  around the current level (a plateau) and bounces off the band edges.
- momentum m(t): accumulates a decaying sum of the signed pushes.
- dominant evidence -> breakout: to leave the current band (break a resistance
  going up, or a support going down) the momentum must exceed a break
  threshold; only dominant inputs (or a sustained run) achieve that. The
  breakout is amplified (a jump to the next level).
- oscillation / stabilization: while nothing is dominant enough, x just
  oscillates in the band (a "negotiation" phase, no decision yet).
- convergence / fixed point: if x reaches a decision zone (top = YES, bottom =
  NO) and stays stable for a window, a decision is made (x(t+1)=x(t)).
- order / time-invariance: because it is a running accumulation, moving the
  dominant inputs later delays the decision (shift in input -> shift in output).
- traceability: every breakout and the convergence step are recorded, so you
  can see which dominant evidence moved the decision through each level.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import numpy as np


@dataclass
class Inp:
    idx: int
    push: float        # signed = direction * dominance
    dominance: float   # magnitude in [0, ~1.7]
    dominant: bool     # True for the rare high-dominance ("major") evidence
    relevant: bool = True   # pre-processing (relevance) filter: 1 = kept, 0 = dropped


def make_inputs(n: int = 100, bias: float = 0.0, dominant_prob: float = 0.08,
                dominant_when: str = "spread", dominant_align: float = 0.85,
                relevance_prob: float = 1.0, seed: int = 0) -> List[Inp]:
    """Synthetic filtered inputs.

    bias in [-0.5, 0.5] tilts the direction of the pushes (drives a trend).
    dominant_prob is the fraction of rare, high-dominance ("major") inputs.
    dominant_when: 'spread' | 'late' | 'early' controls when the dominant
        inputs occur (used to show order / time-invariance).
    dominant_align: how strongly the dominant ("major") evidence follows the
        trend (bias) direction; these are the inputs that drive breakouts.
    relevance_prob: the per-node pre-processing (relevance) filter. Each input
        D_i is independently kept (relevant = 1) with this probability, else
        dropped (relevant = 0) and never reaches aggregation. 1.0 keeps all.
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
    traj: np.ndarray                    # decision trajectory x(t), length n+1
    momentum: np.ndarray                # momentum m(t)
    anchors: np.ndarray                 # current support/resistance level per step
    breakouts: List[Tuple[int, float, int, str]]  # (input idx, dominance, new level, kind: 'dominant'|'momentum')
    decided_at: Optional[int]           # step index of the decision, or None
    decision: Optional[str]             # 'YES' / 'NO' / None
    levels_visited: List[int]
    params: dict
    relevance: Optional[np.ndarray] = None  # per-input 1 = kept / 0 = dropped by the filter
    bands: Optional[np.ndarray] = None      # per-step channel amplitude (phase height)


def simulate(inputs: List[Inp], *, spacing: float = 2.6, band: float = 0.95,
             band_range: Optional[Tuple[float, float]] = None,
             y_center: float = 0.0, y_span: Optional[Tuple[float, float]] = None,
             osc_speed: float = 0.30, push_gain: float = 0.05, decay: float = 0.85,
             break_thr: float = 1.25, break_reset: float = 0.4, decide_level: int = 3,
             stable_window: int = 6, noise: float = 0.03, seed: int = 0) -> SimResult:
    """Run the behaviour oracle over the inputs.

    The trajectory CONSOLIDATES inside a channel (a level +/- band): during a
    consolidation phase it zig-zags edge to edge, touching the resistance line
    (top of the band) and the support line (bottom) several times, like a price
    chart. It only BREAKS OUT to the next level when the accumulated momentum
    passes a threshold (a dominant input, or a sustained run). This keeps the
    support/resistance phases long and easy to see by eye.

    decide_level: how many levels away the decision zone is (YES at
        +decide_level, NO at -decide_level).
    """
    rng = np.random.default_rng(seed + 1)
    rng_b = np.random.default_rng(seed + 2)   # separate stream for per-phase amplitude

    def _band() -> float:
        # each channel (phase) gets its own amplitude when band_range is given,
        # so phase heights vary; otherwise the fixed band is used everywhere.
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
    m = 0.0
    x = y_center
    traj = [x]; mom = [0.0]; anch = [0]; bands = [cur_band]
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
            traj.append(x); mom.append(m); anch.append(anchor); bands.append(cur_band)
            continue
        relevance.append(1)
        m = decay * m + inp.push
        # breakout when momentum crosses the barrier; otherwise consolidate.
        # kind = "dominant" if this single input's own push crosses the barrier,
        # else "momentum" (an ordinary input carried over by accumulated momentum).
        if decided_at is None and m > break_thr and anchor + 1 <= amax:
            anchor += 1
            cur_band = _band()         # new channel, new random amplitude
            o = -cur_band * 0.6        # jump into the low of the new channel
            m *= break_reset
            d = 1.0
            kind = "dominant" if abs(inp.push) >= break_thr else "momentum"
            breakouts.append((inp.idx, inp.dominance, anchor, kind))
        elif decided_at is None and m < -break_thr and anchor - 1 >= amin:
            anchor -= 1
            cur_band = _band()
            o = cur_band * 0.6
            m *= break_reset
            d = -1.0
            kind = "dominant" if abs(inp.push) >= break_thr else "momentum"
            breakouts.append((inp.idx, inp.dominance, anchor, kind))
        else:
            # blocked at a boundary: bleed the momentum so it does not hammer the wall
            if m > break_thr or m < -break_thr:
                m *= break_reset
            # consolidation: zig-zag across the channel, bouncing off the edges.
            # the step scales with the channel amplitude so tall and short phases
            # both fill their band in a similar number of steps.
            o += osc_speed * cur_band * d + push_gain * inp.push + rng.normal(0, noise)
            if o >= cur_band:
                o = cur_band; d = -1.0     # bounce down off the resistance line
            elif o <= -cur_band:
                o = -cur_band; d = 1.0     # bounce up off the support line
        x = y_center + anchor * spacing + o
        traj.append(x); mom.append(m); anch.append(anchor); bands.append(cur_band)
        # convergence -> the OUTPUT of the aggregation function (V1.1): binary.
        # a decision is reached when the trajectory settles in a support or
        # resistance area (an extreme level) and stays there for a window;
        # otherwise it keeps oscillating and there is no decision.
        if y_span is not None:
            at_area = (anchor == amax or anchor == amin)
        else:
            at_area = abs(anchor) >= decide_level
        if decided_at is None and at_area:
            stable += 1
            if stable >= stable_window:
                decided_at = inp.idx
                # V1.1 rule (agreed): converging to a support OR resistance area is
                # a decision; only continued oscillation is no decision.
                decision = "decision"
        else:
            stable = 0
    return SimResult(np.array(traj), np.array(mom), np.array(anch), breakouts,
                     decided_at, decision, sorted(set(anch)),
                     dict(spacing=spacing, band=band, band_range=band_range,
                          y_center=y_center, y_span=y_span,
                          osc_speed=osc_speed, break_thr=break_thr,
                          decide_level=decide_level, stable_window=stable_window),
                     relevance=np.array(relevance), bands=np.array(bands))


if __name__ == "__main__":
    # quick self-check
    ins = make_inputs(100, bias=0.14, seed=1)
    r = simulate(ins, seed=1)
    print("decided:", r.decision, "at step", r.decided_at, "| breakouts:", len(r.breakouts))
