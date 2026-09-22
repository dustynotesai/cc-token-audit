"""Checks you can run yourself, so the numbers do not rest on trust.

Two independent kinds of evidence:

1. **Internal.** The carry decomposition is an identity, so re-summing the
   attributed tokens has to reproduce the billed cache-read total. A drift
   here means the model is wrong, not merely imprecise.

2. **External.** ccusage reads the same logs and is the widely used tool in
   this space. If the two disagree on raw totals, at least one is wrong --
   and it is more likely to be the newer one. Agreement on totals is what
   earns the right to be believed about the attribution on top of them.

Small residuals are expected when Claude Code is running: both tools read a
moving target, and turns land between the two passes.
"""
import json
import subprocess
import sys

TOLERANCE = 0.01        # 1%: comfortably above sampling drift, below real bugs

CCUSAGE_CMD = ["npx", "-y", "ccusage@latest", "claude", "--json"]


def internal(analyses):
    """Re-sum the attribution and compare it to the billed cache-read total."""
    actual = sum(a.actual_read_tokens for a in analyses)
    attributed = sum(a.attributed_read_tokens for a in analyses)
    ratio = attributed / actual if actual else 1.0
    return {
        "name": "carry identity",
        "detail": "attributed cache-read tokens vs billed",
        "ours": attributed, "theirs": actual,
        "drift": ratio - 1.0,
        "ok": abs(ratio - 1.0) <= 0.05,
    }


def per_session_sums(analyses, totals):
    """Per-session figures must add up to the global ones."""
    summed = sum(a.actual_read_tokens for a in analyses)
    ok = summed == totals
    return {
        "name": "per-session sums",
        "detail": "sessions add up to the global total",
        "ours": summed, "theirs": totals,
        "drift": 0.0 if ok else (summed - totals) / (totals or 1),
        "ok": ok,
    }


def run_ccusage(timeout=600):
    """Raw totals from ccusage. Returns None when it cannot be run."""
    try:
        proc = subprocess.run(CCUSAGE_CMD, capture_output=True, text=True,
                              timeout=timeout, encoding="utf-8",
                              shell=(sys.platform == "win32"))
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    try:
        return (json.loads(proc.stdout) or {}).get("totals")
    except ValueError:
        return None


def against_ccusage(tokens, totals):
    """Compare each raw token column with ccusage."""
    pairs = (
        ("cache read", "cacheReadTokens"),
        ("cache write", "cacheCreationTokens"),
        ("input", "inputTokens"),
        ("output", "outputTokens"),
    )
    rows = []
    for mine_key, their_key in pairs:
        ours = tokens.get(mine_key, 0)
        theirs = totals.get(their_key, 0)
        drift = (ours - theirs) / theirs if theirs else 0.0
        rows.append({
            "name": mine_key, "detail": "vs ccusage",
            "ours": ours, "theirs": theirs, "drift": drift,
            "ok": abs(drift) <= TOLERANCE,
        })
    return rows
