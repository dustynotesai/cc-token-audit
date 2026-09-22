"""Which carried tokens were avoidable.

Every finding here is a carry cost -- not the size of the thing, but what it
cost to keep the thing in context for the rest of the session. A 5k-token file
read into a session with 900 turns left is more expensive than a 50k-token read
on the last turn, and only this view shows that.

Each rule says plainly what it assumes, because "avoidable" is a judgement and
the reader should be able to disagree with a specific number.
"""
from dataclasses import dataclass, field

from .i18n import t

# Tools whose result is a pure read of existing state. Running one twice on the
# same target in one session yields the same bytes twice -- unless the file was
# written in between, which WRITE_TOOLS resets. Bash/PowerShell are not here:
# the same command run twice (git status, a test suite after a fix) legitimately
# returns different output.
READ_ONLY_TOOLS = {"Read", "Grep", "Glob", "NotebookRead", "WebFetch"}
WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

OVERSIZED_TOKENS = 10_000


@dataclass
class Finding:
    category: str
    usd: float
    tokens: int
    detail: str
    assumption: str = ""
    items: list = field(default_factory=list)

    def __lt__(self, other):
        return self.usd < other.usd


def _ident(e):
    return e.key or e.target


def _dup_key(charge):
    e = charge.event
    if e.kind != "tool_result" or e.tool not in READ_ONLY_TOOLS or not _ident(e):
        return None
    return (e.tool, _ident(e))


def duplicate_reads(analysis):
    """Second and later reads of the same target in one conversation. A write
    to that target in between makes the next read legitimate again."""
    seen = set()
    dups = []
    for c in sorted(analysis.charges, key=lambda c: c.turn):
        e = c.event
        if e.kind == "tool_result" and e.tool in WRITE_TOOLS and _ident(e):
            written = _ident(e)
            seen = {k for k in seen if k[1] != written}
            continue
        key = _dup_key(c)
        if key is None:
            continue
        if key in seen:
            dups.append(c)
        else:
            seen.add(key)
    if not dups:
        return None
    return Finding(
        category="duplicate-read",
        usd=sum(c.usd for c in dups),
        tokens=sum(c.total_tokens for c in dups),
        detail=t("detail.duplicate-read", n=len(dups)),
        assumption=t("assume.duplicate-read"),
        items=dups,
    )


def failed_tools(analysis):
    """Errors, interruptions and empty searches. These returned nothing usable
    and were then carried for the rest of the session anyway."""
    bad = [c for c in analysis.charges
           if c.event.kind == "tool_result" and not c.event.ok]
    if not bad:
        return None
    return Finding(
        category="failed-tool",
        usd=sum(c.usd for c in bad),
        tokens=sum(c.total_tokens for c in bad),
        detail=t("detail.failed-tool", n=len(bad)),
        assumption=t("assume.failed-tool"),
        items=bad,
    )


def oversized_results(analysis, limit=OVERSIZED_TOKENS):
    """Single tool results far larger than a turn needs. Only the excess over
    the limit is counted -- some of that output was presumably wanted."""
    big = [c for c in analysis.charges
           if c.event.kind == "tool_result" and c.tokens > limit]
    if not big:
        return None
    usd = sum(c.usd * (c.tokens - limit) / c.tokens for c in big)
    return Finding(
        category="oversized-result",
        usd=usd,
        tokens=sum((c.tokens - limit) * (c.carried + 1) for c in big),
        detail=t("detail.oversized-result", n=len(big), limit=limit),
        assumption=t("assume.oversized-result", limit=limit),
        items=big,
    )


def cache_churn(analysis):
    """Context re-written to cache after an entry expired -- the same bytes
    bought twice, at the write rate rather than the read rate."""
    if analysis.churn_usd <= 0:
        return None
    return Finding(
        category="cache-churn",
        usd=analysis.churn_usd,
        tokens=analysis.churn_tokens,
        detail=t("detail.cache-churn"),
        assumption=t("assume.cache-churn"),
    )


RULES = (duplicate_reads, failed_tools, oversized_results, cache_churn)


def findings(analysis, limit=OVERSIZED_TOKENS):
    out = []
    for rule in RULES:
        f = rule(analysis, limit) if rule is oversized_results else rule(analysis)
        if f:
            out.append(f)
    return sorted(out, reverse=True)
