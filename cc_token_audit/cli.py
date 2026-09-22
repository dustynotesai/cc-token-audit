"""cc-token-audit -- find out which of your Claude Code tokens were avoidable.

ccusage and friends tell you how much you spent and when. This tells you what
caused it: every cache-read token is traced back to the moment something
entered the context, and multiplied by how long it then stayed there.
"""
import argparse
import collections
import json
import os
import sys
import time

from . import carry, i18n, live, pricing, report, simulate, verify, waste
from .i18n import t
from .loader import DEFAULT_ROOT, parse_session, walk


def _since(spec):
    if not spec:
        return None
    unit, mult = spec[-1].lower(), {"d": 86400, "w": 604800, "h": 3600}
    if unit in mult:
        try:
            return time.time() - float(spec[:-1]) * mult[unit]
        except ValueError:
            pass
    raise SystemExit(t("err.bad_since", spec=repr(spec)))


def _collect(args):
    sessions, analyses = [], []
    for sess in walk(args.root, args.project, _since(args.since)):
        an = carry.analyse_session(sess)
        sessions.append(sess)
        analyses.append(an)
    return sessions, analyses


def _totals(analyses):
    tok = collections.Counter()
    usd = collections.Counter()
    for an in analyses:
        for turn in an.turns:
            r = pricing.rate_for(turn.model)
            tok["cache read"] += turn.read
            tok["cache write"] += turn.write
            tok["output"] += turn.out
            tok["input"] += turn.inp
            usd["cache read"] += turn.read * r.read / pricing.M
            usd["cache write"] += (turn.write_5m * r.write_5m
                                   + turn.write_1h * r.write_1h) / pricing.M
            usd["output"] += turn.out * r.out / pricing.M
            usd["input"] += turn.inp * r.inp / pricing.M
    return tok, usd


def _by_model(analyses):
    """Tokens and USD per model. Opus costs several times Sonnet per turn, so a
    single summed token count would hide which model the bill came from."""
    rows = {}
    for an in analyses:
        for turn in an.turns:
            m = turn.model or "?"
            r = pricing.rate_for(m)
            row = rows.setdefault(m, collections.Counter())
            row["turns"] += 1
            row["cache read"] += turn.read
            row["cache write"] += turn.write
            row["input"] += turn.inp
            row["output"] += turn.out
            row["usd"] += (turn.read * r.read + turn.write_5m * r.write_5m
                           + turn.write_1h * r.write_1h + turn.inp * r.inp
                           + turn.out * r.out) / pricing.M
    return sorted(rows.items(), key=lambda kv: -kv[1]["usd"])


def cmd_audit(args):
    sessions, analyses = _collect(args)
    if not sessions:
        raise SystemExit(t("err.no_sessions", root=args.root or DEFAULT_ROOT))

    tok, usd = _totals(analyses)
    models = _by_model(analyses)
    total_usd = sum(usd.values())
    turns = sum(len(a.turns) for a in analyses)
    read_actual = sum(a.actual_read_tokens for a in analyses)
    read_attr = sum(a.attributed_read_tokens for a in analyses)
    fidelity = read_attr / read_actual if read_actual else 1.0
    span = f"{min(s.start for s in sessions)[:10]} .. {max(s.end for s in sessions)[:10]}"

    charges = [c for a in analyses for c in a.charges]

    merged = carry.Analysis(charges=charges,
                            turns=[turn for a in analyses for turn in a.turns])
    merged.churn_usd = sum(a.churn_usd for a in analyses)
    merged.actual_write_tokens = sum(a.actual_write_tokens for a in analyses)
    merged.attributed_write_tokens = sum(a.attributed_write_tokens for a in analyses)
    finds = waste.findings(merged, args.oversized)

    # Policies apply per conversation, so every main thread is replayed
    # separately and the results summed. Sidechains are left out: a subagent
    # context is short-lived and is not something you restart.
    scen = simulate.aggregate([s.main for s in sessions],
                              rebuild_turns=args.rebuild)

    rows = sorted(
        ((a.actual_usd, len(a.turns),
          max((turn.ctx for turn in a.turns), default=0),
          s.project, s.session_id)
         for s, a in zip(sessions, analyses)), reverse=True)

    if args.json:
        json.dump({
            "sessions": len(sessions), "turns": turns, "span": span,
            "fidelity": fidelity,
            "tokens": dict(tok), "usd": dict(usd), "total_usd": total_usd,
            "by_model": [dict(row, model=m) for m, row in models],
            "findings": [{"category": f.category, "usd": f.usd,
                          "tokens": f.tokens, "detail": f.detail,
                          "assumption": f.assumption} for f in finds],
            "scenarios": [{"label": s.label, "usd": s.usd,
                           "saved": s.saved, "pct": s.pct} for s in scen],
            "top_sessions": [{"usd": u, "turns": n, "peak_ctx": p,
                              "project": pr, "session": sid}
                             for u, n, p, pr, sid in rows[:args.top]],
        }, sys.stdout, indent=2)
        print()
        return

    out = report.header(len(sessions), turns, span, fidelity)
    out += report.bill(tok, usd)
    out += report.by_model(models)
    out += report.attribution(charges, total_usd)
    out += report.findings_block(finds, total_usd)
    if scen:
        out += report.savings(scen, sum(len(s.main) for s in sessions),
                              sum(simulate.measured(s.main) for s in sessions))
    out += report.top_sessions(rows, args.top)
    out += report.footer()
    print("\n".join(out))


def cmd_drill(args):
    path = args.session
    if not os.path.exists(path):
        matches = [s.path for s in walk(args.root)
                   if args.session in s.path or args.session in s.session_id]
        if not matches:
            raise SystemExit(t("err.no_match", q=repr(args.session)))
        path = matches[0]

    sess = parse_session(path)
    an = carry.analyse_session(sess)
    main = sess.main

    print(f"\n  {path}")
    print(f"  {sess.project}  |  "
          + t("drill_summary", main=len(main), side=len(sess.side)))
    print("  " + t("drill_bill", usd=report.money(an.actual_usd),
                   pct=an.fidelity() * 100, resets=an.resets))
    peak = max((turn.ctx for turn in main), default=0)
    print("  " + t("drill_peak", peak=peak) + "\n")

    print(report.rule(t("drill_head")))
    print()
    print(f"  {i18n.pad(t('col_usd'), 9, '>')} {i18n.pad(t('col_tokens'), 9, '>')} "
          f"{i18n.pad(t('col_reread'), 8, '>')}  "
          f"{i18n.pad(t('col_entered'), 12)} {t('col_what')}")
    for c in sorted(an.charges, key=lambda c: -c.usd)[:args.top]:
        print(f"  {i18n.pad(report.money(c.usd), 9, '>')} {c.tokens:>9,} "
              f"{c.carried:>8}  {i18n.pad(t('turn_at', n=c.turn), 12)} "
              f"{i18n.clip(c.event.label, 38)}")
    print()

    finds = waste.findings(an, args.oversized)
    print("\n".join(report.findings_block(finds, an.actual_usd)))
    print("\n".join(report.savings(
        simulate.scenarios(main, rebuild_turns=args.rebuild),
        len(main), simulate.measured(main))))
    print("\n".join(report.footer()))


def cmd_baseline(args):
    """The standing context every session starts with, and what carrying it cost."""
    sessions, analyses = _collect(args)
    if not sessions:
        raise SystemExit(t("err.no_sessions", root=args.root or DEFAULT_ROOT))

    rows = []
    total_usd = 0.0
    for sess, an in zip(sessions, analyses):
        main = [turn for turn in an.turns if not turn.sidechain]
        if len(main) < 3:
            continue
        cost = simulate.slim_base(main, 1.0)
        total_usd += cost
        rows.append((cost, main[0].ctx, len(main), sess.project))

    rows.sort(reverse=True)
    bases = sorted(r[1] for r in rows)
    mid = bases[len(bases) // 2] if bases else 0

    print("\n  " + report.rule(t("base_head")) + "\n")
    for ln in i18n.lines("base_intro"):
        print("  " + ln)
    print()
    label = 28
    print(f"  {i18n.pad(t('base_median'), label)}: {mid:,} tokens")
    if bases:
        print(f"  {i18n.pad(t('base_range'), label)}: "
              f"{bases[0]:,} .. {bases[-1]:,} tokens")
        print(f"  {i18n.pad(t('base_total'), label)}: {report.money(total_usd)}")
        print("  " + t("base_half", usd=report.money(total_usd / 2)))
    print()
    print(f"  {i18n.pad(t('col_base_cost'), 13, '>')} "
          f"{i18n.pad(t('col_base_tok'), 11, '>')} "
          f"{i18n.pad(t('col_turns'), 7, '>')}  {t('col_project')}")
    for cost, base, n, proj in rows[:args.top]:
        print(f"  {i18n.pad(report.money(cost), 13, '>')} {base:>11,} {n:>7}  "
              f"{i18n.clip(proj, 40)}")
    print()
    for ln in i18n.lines("base_note"):
        print("  " + ln)
    print()


def _preselect_lang(argv):
    """argparse builds its help text as the parser is constructed, so the
    language has to be known before that. A tiny pre-scan of argv is the least
    surprising way to get it."""
    for i, a in enumerate(argv):
        if a == "--lang" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--lang="):
            return a.split("=", 1)[1]
    return i18n.DEFAULT_LANG


def cmd_verify(args):
    """Evidence, not reassurance: re-derive our own totals and put them next to
    an independent tool's reading of the same logs."""
    sessions, analyses = _collect(args)
    if not sessions:
        raise SystemExit(t("err.no_sessions", root=args.root or DEFAULT_ROOT))
    tok, _usd = _totals(analyses)

    checks = [verify.internal(analyses),
              verify.per_session_sums(analyses, tok["cache read"])]

    print()
    print(report.rule(t("verify.head")))
    print()
    print("  " + t("verify.internal"))
    _print_checks(checks)

    print()
    print("  " + t("verify.external"))
    totals = verify.run_ccusage()
    if totals is None:
        for ln in i18n.lines("verify.no_ccusage"):
            print("    " + ln)
    else:
        ext = verify.against_ccusage(tok, totals)
        _print_checks(ext)
        checks += ext

    print()
    for ln in i18n.lines("verify.note"):
        print("  " + ln)
    bad = [c for c in checks if not c["ok"]]
    print()
    print("  " + (t("verify.verdict_ok") if not bad
                  else t("verify.verdict_bad", n=len(bad))))
    print()
    return 0 if not bad else 1


def _print_checks(checks):
    head = (f"    {i18n.pad('', 20)}{i18n.pad('cc-token-audit', 18, '>')}"
            f"{i18n.pad('ccusage / actual', 18, '>')}"
            f"{i18n.pad('drift', 10, '>')}")
    print(head)
    for c in checks:
        mark = t("verify.pass") if c["ok"] else t("verify.fail")
        ours = f"{c['ours']:,}"
        theirs = f"{c['theirs']:,}"
        drift = f"{c['drift'] * 100:+.2f}%"
        print(f"    {i18n.pad(i18n.clip(c['name'], 20), 20)}"
              f"{i18n.pad(ours, 18, '>')}{i18n.pad(theirs, 18, '>')}"
              f"{i18n.pad(drift, 10, '>')}  {mark}")



def cmd_statusline(args):
    """Claude Code pipes session JSON in on stdin and prints whatever comes out.
    It must stay fast and must never crash the status line, so any failure
    degrades to an empty line rather than a traceback in the user's UI."""
    try:
        print(live.main(sys.stdin))
    except Exception:
        print("")


def build_parser():
    # Shared options live on a parent so they work on either side of the
    # subcommand -- `audit --top 5` and `--top 5 audit` both read naturally.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", default=None,
                        help=t("cli.root", default=DEFAULT_ROOT))
    common.add_argument("--project", help=t("cli.project"))
    common.add_argument("--since", help=t("cli.since"))
    common.add_argument("--top", type=int, default=12, help=t("cli.top"))
    common.add_argument("--oversized", type=int, default=waste.OVERSIZED_TOKENS,
                        help=t("cli.oversized"))
    common.add_argument("--rebuild", type=int, default=simulate.REBUILD_TURNS,
                        help=t("cli.rebuild"))
    common.add_argument("--lang", choices=i18n.LANGS, default=i18n.DEFAULT_LANG,
                        help=t("cli.lang"))

    p = argparse.ArgumentParser(
        prog="cc-token-audit", parents=[common],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=t("cli.desc"), epilog=t("cli.epilog"),
    )
    sub = p.add_subparsers(dest="cmd")

    a = sub.add_parser("audit", parents=[common], help=t("cli.audit"))
    a.add_argument("--json", action="store_true", help=t("cli.json"))
    a.set_defaults(func=cmd_audit)

    d = sub.add_parser("drill", parents=[common], help=t("cli.drill"))
    d.add_argument("session", help=t("cli.session_arg"))
    d.set_defaults(func=cmd_drill)

    b = sub.add_parser("baseline", parents=[common], help=t("cli.baseline"))
    b.set_defaults(func=cmd_baseline)

    sl = sub.add_parser("statusline", parents=[common], help=t("cli.statusline"))
    sl.set_defaults(func=cmd_statusline)

    v = sub.add_parser("verify", parents=[common], help=t("cli.verify"))
    v.set_defaults(func=cmd_verify)
    return p


def _force_utf8():
    """Windows consoles still default to a legacy code page (cp1252, cp950),
    which raises UnicodeEncodeError the moment Chinese output is printed. The
    default output language is Chinese, so this is not optional. `errors` is set
    so that an unmappable glyph degrades to a placeholder instead of aborting a
    report the user has already waited for."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass        # not a reconfigurable text stream; nothing to do


def main(argv=None):
    _force_utf8()
    argv = list(sys.argv[1:] if argv is None else argv)
    i18n.set_lang(_preselect_lang(argv))
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        args = parser.parse_args(argv + ["audit"])
    try:
        args.func(args)
    except BrokenPipeError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
