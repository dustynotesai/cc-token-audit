"""What subagents cost, and what running that work inline would have cost.

A subagent reads in its own context window. Whatever it opens is billed for the
few turns that subagent lives and is then gone; only its conclusion returns to
the main thread. Doing the same work inline puts every tool result into the
main window, where it is re-read on every remaining turn of the session.

That difference is the one lever that changes the *shape* of the cost instead
of trimming it: the other savings reduce what you carry, this one stops it
being carried at all.

Subagent transcripts are separate files -- `<project>/<session-id>/subagents/`
-- and carry their parent's id in `sessionId`, which is how the two halves are
matched back together here.

The counterfactual charges a subagent's content against the parent's remaining
turns at the moment it ran. It deliberately omits the summary the subagent
hands back, since that text enters the main thread either way, so the number is
a floor rather than a best case.
"""
from dataclasses import dataclass, field

from . import carry, pricing


@dataclass
class Split:
    main_tokens: int = 0
    main_usd: float = 0.0
    main_turns: int = 0
    side_tokens: int = 0
    side_usd: float = 0.0
    side_turns: int = 0
    inline_usd: float = 0.0
    threads: int = 0
    parents: int = 0
    orphans: int = 0
    sessions: int = 0
    by_project: list = field(default_factory=list)

    @property
    def total_tokens(self):
        return self.main_tokens + self.side_tokens

    @property
    def side_share(self):
        return self.side_tokens / self.total_tokens if self.total_tokens else 0.0

    @property
    def avoided_usd(self):
        """What keeping that reading out of the main window saved."""
        return max(0.0, self.inline_usd - self.side_usd)

    @property
    def multiple(self):
        return self.inline_usd / self.side_usd if self.side_usd else 0.0


def cost(turn):
    r = pricing.rate_for(turn.model)
    return (turn.read * r.read + turn.write_5m * r.write_5m
            + turn.write_1h * r.write_1h + turn.out * r.out
            + turn.inp * r.inp) / pricing.M


def split_sessions(sessions):
    """Separate main transcripts from subagent ones and index the latter by the
    parent session they belong to."""
    mains, subs = [], {}
    for sess in sessions:
        if sess.is_subagent:
            subs.setdefault(sess.session_id, []).append(sess)
        else:
            mains.append(sess)
    return mains, subs


def inline_cost(parent, children):
    """What the children's content would have cost inside the parent's window."""
    main_ts = sorted(t.ts for t in parent.turns)
    if not main_ts:
        return 0.0, 0

    total = 0.0
    threads = 0
    for child in children:
        turns = child.turns
        if not turns:
            continue
        threads += 1
        prev = 0
        for i, turn in enumerate(turns):
            delta = turn.ctx - prev
            prev = turn.ctx
            if delta <= 0:
                continue
            if i == 0:
                # A subagent opens with the system prompt and tool schemas the
                # parent already carries; inline work would not re-add them.
                continue
            # How much of the parent's life this content would have survived.
            remaining = sum(1 for ts in main_ts if ts > turn.ts)
            r = pricing.rate_for(turn.model)
            write = r.write_1h if turn.write_1h else r.write_5m
            total += delta * (write + remaining * r.read) / pricing.M
    return total, threads


def analyse(sessions):
    """Aggregate the main/subagent split and the carry cost it avoided."""
    mains, subs = split_sessions(sessions)
    split = Split(sessions=len(sessions))
    by_project = {}

    for sess in mains:
        for turn in sess.turns:
            split.main_tokens += turn.read + turn.write + turn.out + turn.inp
            split.main_usd += cost(turn)
        split.main_turns += len(sess.turns)

    claimed = set()
    for parent in mains:
        children = subs.get(parent.session_id)
        if not children:
            continue
        claimed.add(parent.session_id)
        split.parents += 1
        actual = sum(cost(t) for c in children for t in c.turns)
        inline, threads = inline_cost(parent, children)
        split.inline_usd += inline
        split.threads += threads
        saved = inline - actual
        if saved > 0:
            row = by_project.setdefault(parent.project, [0.0, 0.0, 0.0, 0])
            row[0] += saved
            row[1] += actual
            row[2] += inline
            row[3] += threads

    for sid, children in subs.items():
        for child in children:
            for turn in child.turns:
                split.side_tokens += turn.read + turn.write + turn.out + turn.inp
                split.side_usd += cost(turn)
            split.side_turns += len(child.turns)
        if sid not in claimed:
            # The parent transcript was deleted or lies outside --project/--since,
            # so there is no timeline to charge the counterfactual against.
            split.orphans += len(children)

    split.by_project = sorted(
        ((v[0], v[1], v[2], v[3], k) for k, v in by_project.items()), reverse=True)
    return split
