"""What a different working habit would have cost.

These are replays, not guesses. The delta sequence is measured from the real
bill; a policy changes only which deltas are still being carried on each turn,
and the same rates are reapplied. Where a policy implies re-establishing
context, that rebuild is charged too, so the numbers are not free wins.

The one estimated input is how much context a fresh session needs to pick up
where the last one stopped (`rebuild_turns`). It is charged, deliberately, on
the pessimistic side.
"""
from dataclasses import dataclass

from . import carry, pricing
from .i18n import t

DEFAULT_THRESHOLDS = (100_000, 150_000, 200_000, 300_000, 500_000)
REBUILD_TURNS = 20


@dataclass
class Scenario:
    label: str
    usd: float
    baseline_usd: float
    note: str = ""

    @property
    def saved(self):
        return self.baseline_usd - self.usd

    @property
    def pct(self):
        if not self.baseline_usd:
            return 0.0
        return 100.0 * self.saved / self.baseline_usd


def _deltas(turns):
    """Per-turn context growth, with its read and write rates."""
    out = []
    prev = 0
    for turn in turns:
        d = turn.ctx - prev
        prev = turn.ctx
        r = pricing.rate_for(turn.model)
        wr = r.write_1h if turn.write_1h else r.write_5m
        out.append((max(0, d), r.read / pricing.M, wr / pricing.M))
    return out


def measured(turns):
    """What the carried context actually cost, straight from the billed counts."""
    total = 0.0
    for turn in turns:
        r = pricing.rate_for(turn.model)
        total += turn.read * r.read / pricing.M
        total += (turn.write_5m * r.write_5m
                  + turn.write_1h * r.write_1h) / pricing.M
    return total


def runs(turns):
    """Split a thread where its context actually reset. Inside a run the window
    only grows, which is what the replay assumes; ignoring the compactions that
    really happened would model a context that never comes back down."""
    return [turns[a:b] for a, b in carry.segments(turns)]


def cap_context(turns, threshold, rebuild_turns=REBUILD_TURNS):
    """Start a fresh session whenever context would pass `threshold`.

    Each restart pays to re-establish the standing context plus the last
    `rebuild_turns` of conversation, so the cost of breaking up work is
    included rather than assumed away.
    """
    deltas = _deltas(turns)
    if not deltas:
        return 0.0, 0
    base = deltas[0][0]
    total = 0.0
    ctx = 0
    recent = []
    restarts = 0

    for d, rrate, wrate in deltas:
        if ctx and ctx + d > threshold:
            restarts += 1
            rebuilt = base + sum(recent[-rebuild_turns:])
            total += rebuilt * wrate          # re-writing it into a fresh cache
            ctx = rebuilt
        ctx += d
        total += d * wrate + (ctx - d) * rrate
        recent.append(d)
    return total, restarts


def slim_base(turns, fraction):
    """Cut the standing turn-0 context (system prompt, tool schemas, CLAUDE.md,
    MCP tool definitions) by `fraction` and recharge every turn that carried it."""
    if not turns:
        return 0.0
    base = turns[0].ctx
    removed = int(base * fraction)
    saved = 0.0
    for turn in turns[1:]:
        saved += removed * pricing.rate_for(turn.model).read / pricing.M
    r = pricing.rate_for(turns[0].model)
    saved += removed * (r.write_1h if turns[0].write_1h else r.write_5m) / pricing.M
    return saved


def scenarios(turns, thresholds=DEFAULT_THRESHOLDS, rebuild_turns=REBUILD_TURNS):
    return aggregate([turns], thresholds, rebuild_turns)


NO_CAP = float("inf")


def aggregate(threads, thresholds=DEFAULT_THRESHOLDS, rebuild_turns=REBUILD_TURNS):
    """Replay every conversation under each policy and sum the results.

    A policy has to be applied per conversation -- you restart a session, not a
    history -- so each thread is replayed on its own and the totals added. Short
    threads are included: they simply never trip a threshold and contribute
    their unchanged cost to both sides, which keeps the percentages honest.

    The baseline runs through the same replay with no cap, so both sides of
    every comparison are produced by identical arithmetic. Comparing a modelled
    scenario against the measured bill would fold the model's own error into
    the saving.
    """
    threads = [run for th in threads if th for run in runs(th)]
    base_usd = sum(cap_context(th, NO_CAP, rebuild_turns)[0] for th in threads)
    out = []

    for thr in thresholds:
        usd = 0.0
        restarts = 0
        for th in threads:
            u, r = cap_context(th, thr, rebuild_turns)
            usd += u
            restarts += r
        if not restarts:
            continue
        # A policy that costs more is kept: finding the floor, where restarting
        # so often that rebuilding the base dominates, is part of the answer.
        out.append(Scenario(
            label=t("policy.cap", k=thr // 1000),
            usd=usd, baseline_usd=base_usd,
            note=t("note.restarts", n=restarts, turns=rebuild_turns),
        ))

    for frac, key in ((0.25, "slim.quarter"), (0.5, "slim.half")):
        saved = sum(slim_base(th, frac) for th in threads)
        if saved > 0:
            out.append(Scenario(
                label=t("policy.slim", name=t(key)),
                usd=base_usd - saved, baseline_usd=base_usd,
                note=t("note.slim"),
            ))
    return out
