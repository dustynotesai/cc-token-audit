"""The in-session signal: what the next turn costs, and when to act.

`audit` is retrospective. This is the same arithmetic applied to the live
session, rendered as a Claude Code status line.

The decision it answers is not "is my context big" -- a percentage already
tells you that, and it tells you nothing about money. It is "does restarting
pay for itself yet", which depends on your own standing context:

    carrying on        costs  ctx  x read   per turn
    after a restart    costs  base x read   per turn
    the restart itself costs  base x write  once

so a restart pays for itself after

    T = base x write / ((ctx - base) x read)   turns

and on a 1h TTL, write is 20x read. With a 54k base that is ~23 turns at 100k
of context but only ~4 at 300k, which is why a fixed "clear at N" rule is the
wrong shape -- the right moment moves with how heavy your session opens.

Everything here reads from the status line JSON Claude Code puts on stdin. The
transcript is touched only to find the first turn's size, and only until that
one record is found, because this runs on every render.
"""
import json
import os

from . import pricing
from .i18n import t

BAR_CELLS = 10
FULL, EMPTY = "■", "□"

# Below this, a restart cannot pay off soon enough to be worth the interruption.
WORTH_IT_TURNS = 12
SOON_TURNS = 25

# Warn while there is still time to act before the cached prefix goes cold.
COLD_WARN_SECONDS = 600


def _first_turn_context(transcript_path):
    """Size of the standing context: system prompt, tool schemas, CLAUDE.md.

    Stops at the first assistant record rather than parsing the file, so this
    stays cheap enough to run on every status line render.
    """
    if not transcript_path or not os.path.exists(transcript_path):
        return 0
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"assistant"' not in line[:300]:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("type") != "assistant":
                    continue
                u = (rec.get("message") or {}).get("usage") or {}
                return (u.get("input_tokens", 0)
                        + u.get("cache_creation_input_tokens", 0)
                        + u.get("cache_read_input_tokens", 0))
    except OSError:
        pass
    return 0


def _bar(pct):
    filled = max(0, min(BAR_CELLS, round(pct / 100 * BAR_CELLS)))
    return FULL * filled + EMPTY * (BAR_CELLS - filled)


def breakeven_turns(ctx, base, rate):
    """Turns until a restart pays for itself. None when it never does."""
    if not ctx or not base or ctx <= base:
        return None
    write = rate.write_1h or rate.write_5m
    if not rate.read:
        return None
    return base * write / ((ctx - base) * rate.read)


def render(payload, now=None):
    """Build the status line from Claude Code's stdin JSON."""
    import time
    now = time.time() if now is None else now

    model = (payload.get("model") or {}).get("display_name") or ""
    model_id = (payload.get("model") or {}).get("id") or ""
    cw = payload.get("context_window") or {}
    cache = payload.get("prompt_cache") or {}

    ctx = cw.get("total_input_tokens") or 0
    pct = cw.get("used_percentage")
    size = cw.get("context_window_size") or 0
    if pct is None:
        pct = (100 * ctx / size) if size else 0

    parts = []
    if model:
        parts.append(model)
    parts.append(f"{_bar(pct)} {pct:.0f}%")

    if not ctx:
        # Before the first API response there is nothing to reason about.
        return "  ".join(parts)

    parts.append(f"{ctx / 1000:.0f}k")

    rate = pricing.rate_for(model_id)
    per_turn = ctx * rate.read / pricing.M
    if per_turn:
        parts.append(t("live.per_turn", usd=f"${per_turn:,.3f}"))

    base = _first_turn_context(payload.get("transcript_path"))
    turns = breakeven_turns(ctx, base, rate)
    if turns is not None:
        if turns <= WORTH_IT_TURNS:
            parts.append(t("live.restart_now", n=round(turns)))
        elif turns <= SOON_TURNS:
            parts.append(t("live.restart_soon", n=round(turns)))

    expires = cache.get("expires_at")
    if cache.get("warm") and expires:
        left = expires - now
        if 0 < left <= COLD_WARN_SECONDS:
            recache = cache.get("recache_tokens_if_cold") or 0
            cost = recache * (rate.write_1h or rate.write_5m) / pricing.M
            parts.append(t("live.cache_cold", mins=int(left // 60),
                           usd=f"${cost:,.2f}"))

    return "  ".join(parts)


def main(stream):
    try:
        payload = json.load(stream)
    except (ValueError, AttributeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    return render(payload)
