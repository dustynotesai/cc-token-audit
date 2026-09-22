"""Carry cost: decompose the cache-read bill back onto what caused it.

The accounting identity this rests on:

    ctx(i)   = input + cache_creation + cache_read   (billed context at turn i)
    delta(i) = ctx(i) - ctx(i-1)                     (what entered before turn i)

    total cache_read = SUM over i of  delta(i) * (turns that follow i)

Anything that enters the context is paid for once as a cache write and then
again as a cache read on every later turn in the session. So a tool result is
not charged for what it cost to fetch; it is charged for how long it then sat
there. That multiplier is the whole story, and it is why a big read early in a
long session is far more expensive than the same read at the end.

The split of a delta across the events that caused it is proportional to their
measured sizes and therefore an estimate. The delta itself, and every total
built from it, comes from billed token counts and is exact. `fidelity()`
reports how closely the reconstruction matches the real bill.
"""
from dataclasses import dataclass, field

from . import pricing
from .loader import Event

# A drop in context this large means history was compacted or reset; events
# before it are no longer being carried.
RESET_DROP = 0.80


@dataclass
class Charge:
    """One event, and what carrying it actually cost."""
    event: Event
    turn: int            # turn index where it entered
    tokens: int          # attributed delta, in tokens
    carried: int         # number of later turns that re-read it
    write_usd: float
    read_usd: float
    model: str

    @property
    def usd(self):
        return self.write_usd + self.read_usd

    @property
    def total_tokens(self):
        """Tokens billed across the whole life of this event."""
        return self.tokens * (self.carried + 1)


@dataclass
class Analysis:
    charges: list = field(default_factory=list)
    turns: list = field(default_factory=list)
    actual_usd: float = 0.0
    actual_read_tokens: int = 0
    attributed_read_tokens: int = 0
    actual_write_tokens: int = 0
    attributed_write_tokens: int = 0
    churn_usd: float = 0.0
    output_usd: float = 0.0
    resets: int = 0

    @property
    def carry_usd(self):
        return sum(c.usd for c in self.charges)

    @property
    def churn_tokens(self):
        """Cache writes beyond what context growth explains: the same content
        written to cache again after an entry expired. Paid at the write rate,
        which on a 1h TTL is 2x base input."""
        return max(0, self.actual_write_tokens - self.attributed_write_tokens)

    def fidelity(self):
        """Attributed read tokens as a fraction of the real cache-read bill."""
        if not self.actual_read_tokens:
            return 1.0
        return self.attributed_read_tokens / self.actual_read_tokens


def _suffix_read_rates(turns):
    """R[i] = USD per token to re-read one token on every turn after i."""
    n = len(turns)
    suffix = [0.0] * (n + 1)
    for i in range(n - 1, -1, -1):
        suffix[i] = suffix[i + 1] + pricing.rate_for(turns[i].model).read / pricing.M
    return suffix


def _write_rate(turn):
    """Blended USD per token for this turn's cache write, honouring the 5m/1h mix."""
    r = pricing.rate_for(turn.model)
    total = turn.write_5m + turn.write_1h
    if not total:
        return r.write_5m / pricing.M
    blended = (turn.write_5m * r.write_5m + turn.write_1h * r.write_1h) / total
    return blended / pricing.M


def segments(turns):
    """Split at compaction/cache resets. An event is only carried to the end of
    its own segment -- after a reset the earlier history is gone and stops being
    billed. Returns a list of (start, end) half-open index ranges."""
    bounds = [0]
    prev = 0
    for i, t in enumerate(turns):
        if prev and t.ctx < prev * RESET_DROP:
            bounds.append(i)
        prev = t.ctx
    bounds.append(len(turns))
    return list(zip(bounds, bounds[1:]))


def analyse(turns):
    """Attribute every carried token in a list of turns (one conversation)."""
    an = Analysis(turns=turns)
    if not turns:
        return an

    for t in turns:
        an.actual_usd += pricing.usd(t.model, read=t.read, write_5m=t.write_5m,
                                     write_1h=t.write_1h, inp=t.inp, out=t.out)
        an.output_usd += pricing.usd(t.model, out=t.out)
        an.actual_read_tokens += t.read
        an.actual_write_tokens += t.write

    suffix = _suffix_read_rates(turns)
    segs = segments(turns)
    an.resets = len(segs) - 1

    for seg, (start, end) in enumerate(segs):
        prev_ctx = 0
        for i in range(start, end):
            t = turns[i]
            delta = t.ctx - prev_ctx
            prev_ctx = t.ctx
            if delta <= 0:
                continue

            if i == start:
                # The standing context every turn in this segment pays for:
                # system prompt, tool schemas, CLAUDE.md. After a reset it is
                # re-established history rather than the original baseline.
                events = [Event("base" if seg == 0 else "context_rebuild", delta)]
            else:
                events = [e for e in t.events if e.approx > 0] or \
                         [Event("unattributed", delta)]

            total_approx = sum(e.approx for e in events)
            carried = end - 1 - i                    # re-read only within this segment
            wrate = _write_rate(t)
            rrate = suffix[i + 1] - suffix[end]

            assigned = 0
            for k, e in enumerate(events):
                share = (delta - assigned if k == len(events) - 1
                         else delta * e.approx // total_approx)
                assigned += share
                if share <= 0:
                    continue
                an.charges.append(Charge(
                    event=e, turn=i, tokens=share, carried=carried,
                    write_usd=share * wrate, read_usd=share * rrate, model=t.model,
                ))
                an.attributed_read_tokens += share * carried
                an.attributed_write_tokens += share

    churn = max(0, an.actual_write_tokens - an.attributed_write_tokens)
    if churn and turns:
        an.churn_usd = churn * _write_rate(turns[0])
    return an


def analyse_session(session):
    """Main thread and sidechains are separate contexts -- a subagent's reading
    never enters the main window -- so they are analysed apart and then merged.
    The merged `turns` must hold both, or sidechain tokens vanish from totals."""
    main = analyse(session.main)
    side = analyse(session.side)
    main.turns = session.turns
    main.charges.extend(side.charges)
    main.actual_usd += side.actual_usd
    main.output_usd += side.output_usd
    main.actual_read_tokens += side.actual_read_tokens
    main.attributed_read_tokens += side.attributed_read_tokens
    main.actual_write_tokens += side.actual_write_tokens
    main.attributed_write_tokens += side.attributed_write_tokens
    main.churn_usd += side.churn_usd
    main.resets += side.resets
    return main
