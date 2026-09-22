"""USD rates per million tokens.

Source: https://platform.claude.com/docs/en/about-claude/pricing (fetched 2026-09-22).
Cache multipliers relative to base input: 5m write 1.25x, 1h write 2x,
read 0.1x -- except Fable 5.1 / Mythos 5.1, which read at 0.025x.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Rate:
    inp: float
    write_5m: float
    write_1h: float
    read: float
    out: float


# per million tokens, USD
RATES = {
    "claude-fable-5-1":  Rate(10.0, 12.50, 20.0, 0.25, 50.0),
    "claude-mythos-5-1": Rate(10.0, 12.50, 20.0, 0.25, 50.0),
    "claude-fable-5":    Rate(10.0, 12.50, 20.0, 1.00, 50.0),
    "claude-opus-5":     Rate(5.0,   6.25, 10.0, 0.50, 25.0),
    "claude-opus-4-8":   Rate(5.0,   6.25, 10.0, 0.50, 25.0),
    "claude-opus-4-7":   Rate(5.0,   6.25, 10.0, 0.50, 25.0),
    "claude-opus-4-6":   Rate(5.0,   6.25, 10.0, 0.50, 25.0),
    "claude-sonnet-5":   Rate(2.0,   2.50,  4.0, 0.20, 10.0),
    "claude-sonnet-4-6": Rate(3.0,   3.75,  6.0, 0.30, 15.0),
    "claude-haiku-4-5":  Rate(1.0,   1.25,  2.0, 0.10,  5.0),
}

FREE = Rate(0.0, 0.0, 0.0, 0.0, 0.0)
_FALLBACK = RATES["claude-opus-5"]

M = 1_000_000.0


def rate_for(model):
    """Rate for a model id. Synthetic/local turns are free; unknown ids fall back
    to Opus 5 so an unrecognised model is never silently priced at zero."""
    if not model or model.startswith("<"):
        return FREE
    r = RATES.get(model)
    if r is not None:
        return r
    base = model.rsplit("-", 1)[0]
    return RATES.get(base, _FALLBACK)


def usd(model, *, read=0, write_5m=0, write_1h=0, inp=0, out=0):
    r = rate_for(model)
    return (read * r.read + write_5m * r.write_5m + write_1h * r.write_1h
            + inp * r.inp + out * r.out) / M
