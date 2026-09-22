"""Terminal rendering. Plain ASCII frame, no dependencies, pipe-friendly.

All user-facing text comes from i18n, and every column is padded by display
width rather than character count -- a CJK glyph takes two terminal cells, so
naive padding skews any table that mixes scripts.
"""
import collections

from .i18n import clip, join_label, lines, pad, t, width

W = 78


def money(x):
    return f"${x:,.2f}"


def rule(title=""):
    if not title:
        return "-" * W
    return f"{title}  " + "-" * max(0, W - width(title) - 2)


def header(scanned, turns, span, fidelity):
    return [
        "",
        "=" * W,
        "  " + t("title"),
        "=" * W,
        "  " + t("scanned", sessions=scanned, turns=turns, span=span),
        "  " + t("fidelity", pct=fidelity * 100),
        "",
    ]


def bill(tok, usd):
    """The raw bill, before any judgement about what was necessary."""
    total_t = sum(tok.values())
    total_u = sum(usd.values())
    out = [rule(t("bill_head")), ""]
    out.append("  " + pad("", 22) + pad(t("col_tokens"), 18, ">")
               + " " + pad(t("col_usd"), 12, ">") + "   " + t("col_share"))
    for k in ("cache read", "cache write", "output", "input"):
        n, u = tok.get(k, 0), usd.get(k, 0)
        share = 100 * n / total_t if total_t else 0
        out.append(f"  {pad(t(k), 22)}{pad(f'{n:,}', 18, '>')} "
                   f"{pad(money(u), 12, '>')}  {share:5.1f}%")
    out.append(f"  {pad(t('total'), 22)}{pad(f'{total_t:,}', 18, '>')} "
               f"{pad(money(total_u), 12, '>')}")
    out.append("")
    if total_t:
        cr = 100 * tok.get("cache read", 0) / total_t
        out += ["  " + ln for ln in lines("bill_note", pct=cr)]
    out.append("")
    return out


def attribution(charges, total_usd):
    """Which kinds of content the carried bill was spent on."""
    by = collections.Counter()
    for c in charges:
        by[c.event.kind] += c.usd
    out = [rule(t("attr_head")), ""]
    for kind, usd in by.most_common():
        share = 100 * usd / total_usd if total_usd else 0
        out.append(f"  {pad(clip(t(f'kind.{kind}'), 52), 52)} "
                   f"{pad(money(usd), 11, '>')}  {share:5.1f}%")
    out.append("")
    return out


def findings_block(findings, total_usd):
    out = [rule(t("waste_head")), ""]
    if not findings:
        out += ["  " + t("waste_none"), ""]
        return out
    for i, f in enumerate(findings, 1):
        share = 100 * f.usd / total_usd if total_usd else 0
        out.append(f"  {i}. {pad(t(f'cat.{f.category}'), 20)} "
                   f"{pad(money(f.usd), 11, '>')}  {t('share_of_bill', pct=share)}")
        out.append("     " + f.detail)
        if f.assumption:
            out.append("     " + join_label(t("assumes"), f.assumption))
        for c in sorted(f.items, key=lambda c: -c.usd)[:3]:
            out.append(f"       {pad(money(c.usd), 9, '>')}  "
                       f"{pad(clip(c.event.label, 46), 46)} "
                       f"{t('carried_turns', n=c.carried)}")
        out.append("")
    return out


def savings(scenarios, threads=0, measured_usd=0.0):
    out = [rule(t("save_head")), ""]
    if not scenarios:
        out += ["  " + t("save_none"), ""]
        return out
    base = scenarios[0].baseline_usd
    out.append("  " + t("save_scope", usd=money(base), turns=threads))
    out += ["  " + ln for ln in lines("save_excluded")]
    if measured_usd:
        out += ["  " + ln for ln in lines("save_accuracy",
                                          pct=100 * base / measured_usd,
                                          usd=money(measured_usd))]
    out.append("")
    out.append(f"  {pad(t('col_policy'), 44)} {pad(t('col_would_cost'), 12, '>')} "
               f"{pad(t('col_saves'), 10, '>')}")
    worse = False
    for s in sorted(scenarios, key=lambda s: -s.saved):
        tail = "" if s.saved >= 0 else t("costs_more")
        worse = worse or s.saved < 0
        out.append(f"  {pad(clip(s.label, 44), 44)} {pad(money(s.usd), 12, '>')} "
                   f"{pad(money(s.saved), 10, '>')} {s.pct:>5.0f}%{tail}")
        if s.note:
            out.append("    " + s.note)
    out.append("")
    out += ["  " + ln for ln in lines("save_method")]
    if worse:
        out.append("")
        out += ["  " + ln for ln in lines("save_floor")]
    out.append("")
    return out


def top_sessions(rows, limit=10):
    out = [rule(t("top_head")), ""]
    out.append(f"  {pad(t('col_usd'), 10, '>')} {pad(t('col_turns'), 7, '>')} "
               f"{pad(t('col_peak'), 12, '>')}  {t('col_project')}")
    for usd, turns, peak, proj, sid in rows[:limit]:
        out.append(f"  {pad(money(usd), 10, '>')} {turns:>7} {peak:>12,}  "
                   f"{clip(proj, 30)} {sid[:8]}")
    out.append("")
    return out


def footer():
    out = [rule(), ""]
    out += ["  " + ln for ln in lines("footer_note")]
    out.append("")
    out.append("  " + t("footer_rates"))
    out.append("")
    return out
