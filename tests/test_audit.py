"""Tests for the three things that are easy to get wrong here.

Each of these corresponds to a bug that was actually hit while building this:
duplicated assistant records doubling the bill, the carry identity not closing,
and compaction letting pre-reset events be billed to the end of the session.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cc_token_audit import carry, live, pricing, simulate, waste   # noqa: E402
from cc_token_audit.loader import parse_session                      # noqa: E402


def assistant(mid, read, write, out=10, model="claude-opus-5", blocks=None,
              sidechain=False, ts="2026-09-01T00:00:00Z"):
    return {
        "type": "assistant", "timestamp": ts, "isSidechain": sidechain,
        "sessionId": "s1", "cwd": "/x", "gitBranch": "main",
        "message": {
            "id": mid, "model": model, "role": "assistant",
            "content": blocks or [{"type": "text", "text": "hi"}],
            "usage": {
                "input_tokens": 0,
                "cache_creation_input_tokens": write,
                "cache_read_input_tokens": read,
                "output_tokens": out,
                "cache_creation": {"ephemeral_1h_input_tokens": write,
                                   "ephemeral_5m_input_tokens": 0},
            },
        },
    }


def tool_result(tool_use_id, text, is_error=False, tur=None):
    rec = {
        "type": "user", "timestamp": "2026-09-01T00:00:00Z",
        "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": tool_use_id,
             "content": text, "is_error": is_error}]},
    }
    if tur is not None:
        rec["toolUseResult"] = tur
    return rec


def write_log(records):
    fh = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False,
                                     encoding="utf-8")
    for r in records:
        fh.write(json.dumps(r) + "\n")
    fh.close()
    return fh.name


class TestDeduplication(unittest.TestCase):
    """One logical assistant message is written once per content block, each
    copy repeating the same usage. Counting lines instead of messages roughly
    doubles the bill -- the single most consequential bug in this domain."""

    def test_repeated_message_id_counts_once(self):
        recs = [
            assistant("m1", 0, 1000, blocks=[{"type": "thinking", "thinking": "a"}]),
            assistant("m1", 0, 1000, blocks=[{"type": "text", "text": "b"}]),
            assistant("m1", 0, 1000, blocks=[{"type": "text", "text": "c"}]),
            assistant("m2", 1000, 500),
        ]
        path = write_log(recs)
        try:
            sess = parse_session(path)
            self.assertEqual(len(sess.turns), 2)
            self.assertEqual(sum(t.ctx for t in sess.turns), 1000 + 1500)
        finally:
            os.unlink(path)

    def test_output_tokens_take_the_last_snapshot(self):
        """The duplicate records are streaming snapshots and output_tokens grows
        across them. Reading the first copy understated output by 9.5% against
        ccusage; the input side is fixed at request time and must not move."""
        recs = [
            assistant("m1", 500, 1000, out=10),
            assistant("m1", 500, 1000, out=120),
            assistant("m1", 500, 1000, out=350),
        ]
        path = write_log(recs)
        try:
            turn = parse_session(path).turns[0]
            self.assertEqual(turn.out, 350)
            self.assertEqual(turn.ctx, 1500)      # input side unchanged
        finally:
            os.unlink(path)

    def test_content_blocks_are_merged_across_copies(self):
        recs = [
            assistant("m1", 0, 1000, blocks=[{"type": "text", "text": "x" * 400}]),
            assistant("m1", 0, 1000, blocks=[{"type": "text", "text": "y" * 400}]),
        ]
        path = write_log(recs)
        try:
            sess = parse_session(path)
            # both blocks contribute to what the next turn will carry
            self.assertGreater(sess.turns[0].out_chars, 700)
        finally:
            os.unlink(path)


class TestCarryIdentity(unittest.TestCase):
    """total cache_read == sum over deltas of delta * turns-that-follow."""

    def test_reconstruction_is_exact(self):
        recs = [assistant("m0", 0, 1000),
                assistant("m1", 1000, 500),
                assistant("m2", 1500, 500)]
        path = write_log(recs)
        try:
            an = carry.analyse_session(parse_session(path))
            self.assertEqual(an.actual_read_tokens, 2500)
            self.assertEqual(an.attributed_read_tokens, 2500)
            self.assertEqual(an.fidelity(), 1.0)
        finally:
            os.unlink(path)

    def test_early_content_costs_more_than_identical_late_content(self):
        recs = [assistant("m0", 0, 1000)]
        recs += [assistant(f"m{i}", 1000 + (i - 1) * 100, 100)
                 for i in range(1, 8)]
        path = write_log(recs)
        try:
            an = carry.analyse_session(parse_session(path))
            ordered = sorted((c for c in an.charges if c.tokens == 100),
                             key=lambda c: c.turn)
            self.assertGreater(ordered[0].usd, ordered[-1].usd)
            self.assertEqual(ordered[-1].read_usd, 0.0)   # nothing follows it
        finally:
            os.unlink(path)


class TestCompaction(unittest.TestCase):
    """After a reset the earlier history is gone. Billing it to the end of the
    session inflated a real measurement to 325% of the actual bill."""

    def test_events_are_not_carried_past_a_reset(self):
        recs = [assistant("m0", 0, 100_000),
                assistant("m1", 100_000, 1_000),
                assistant("m2", 0, 20_000),        # compacted: context collapses
                assistant("m3", 20_000, 1_000)]
        path = write_log(recs)
        try:
            an = carry.analyse_session(parse_session(path))
            self.assertEqual(an.resets, 1)
            self.assertLessEqual(an.fidelity(), 1.01)
            pre = [c for c in an.charges if c.turn == 0][0]
            self.assertEqual(pre.carried, 1)   # not 3
        finally:
            os.unlink(path)

    def test_segments_split_on_large_drop(self):
        class T:
            def __init__(self, ctx):
                self.ctx = ctx
        turns = [T(100), T(200), T(50), T(80)]
        self.assertEqual(carry.segments(turns), [(0, 2), (2, 4)])


class TestPricing(unittest.TestCase):
    def test_fable_reads_at_a_quarter_the_usual_rate(self):
        # Fable 5.1 reads at 0.025x base, not the standard 0.1x.
        self.assertEqual(pricing.rate_for("claude-fable-5-1").read, 0.25)
        self.assertEqual(pricing.rate_for("claude-opus-5").read, 0.50)

    def test_one_hour_writes_cost_double_base_input(self):
        r = pricing.rate_for("claude-opus-5")
        self.assertEqual(r.write_1h, r.inp * 2)
        self.assertEqual(r.write_5m, r.inp * 1.25)

    def test_synthetic_turns_are_free_and_unknown_models_are_not(self):
        self.assertEqual(pricing.rate_for("<synthetic>").read, 0.0)
        self.assertGreater(pricing.rate_for("claude-unreleased-9").read, 0.0)


class TestWaste(unittest.TestCase):
    def _session(self, extra):
        recs = [assistant("m0", 0, 1000)]
        for i, (blocks, result) in enumerate(extra, start=1):
            recs.append(assistant(f"m{i}", 1000 * i, 1000, blocks=blocks))
            recs.append(result)
        recs.append(assistant("mz", 1000 * (len(extra) + 1), 1000))
        return write_log(recs)

    def test_repeat_read_of_same_file_is_flagged(self):
        use = lambda i: [{"type": "tool_use", "id": f"t{i}", "name": "Read",
                          "input": {"file_path": "/a/same.py"}}]
        path = self._session([(use(1), tool_result("t1", "x" * 4000)),
                              (use(2), tool_result("t2", "x" * 4000))])
        try:
            an = carry.analyse_session(parse_session(path))
            found = waste.duplicate_reads(an)
            self.assertIsNotNone(found)
            self.assertEqual(len(found.items), 1)      # the second read only
        finally:
            os.unlink(path)

    def test_edits_to_one_file_are_not_duplicates(self):
        use = lambda i: [{"type": "tool_use", "id": f"t{i}", "name": "Edit",
                          "input": {"file_path": "/a/same.py"}}]
        path = self._session([(use(1), tool_result("t1", "ok")),
                              (use(2), tool_result("t2", "ok"))])
        try:
            an = carry.analyse_session(parse_session(path))
            self.assertIsNone(waste.duplicate_reads(an))
        finally:
            os.unlink(path)

    def test_failed_and_empty_results_are_flagged(self):
        use = lambda i, n: [{"type": "tool_use", "id": f"t{i}", "name": n,
                             "input": {"command": "x"}}]
        path = self._session([
            (use(1, "Bash"), tool_result("t1", "boom", tur={"returnCode": 2,
                                                            "stderr": "boom",
                                                            "stdout": ""})),
            (use(2, "Grep"), tool_result("t2", "No matches found")),
        ])
        try:
            an = carry.analyse_session(parse_session(path))
            found = waste.failed_tools(an)
            self.assertIsNotNone(found)
            self.assertEqual(len(found.items), 2)
        finally:
            os.unlink(path)


class TestSimulate(unittest.TestCase):
    def test_restarting_too_often_costs_more(self):
        """Rebuilding the standing context is charged at the write rate, which
        is 20x a read, so there has to be a point where capping stops paying."""
        recs = [assistant("m0", 0, 50_000)]
        ctx = 50_000
        for i in range(1, 60):
            recs.append(assistant(f"m{i}", ctx, 5_000))
            ctx += 5_000
        path = write_log(recs)
        try:
            turns = parse_session(path).main
            loose, _ = simulate.cap_context(turns, 10_000_000)
            tight, n = simulate.cap_context(turns, 60_000)
            self.assertGreater(n, 5)
            self.assertGreater(tight, loose)
        finally:
            os.unlink(path)

    def test_baseline_and_scenario_share_one_code_path(self):
        recs = [assistant("m0", 0, 1000), assistant("m1", 1000, 1000)]
        path = write_log(recs)
        try:
            turns = parse_session(path).main
            a, n = simulate.cap_context(turns, simulate.NO_CAP)
            self.assertEqual(n, 0)
            self.assertGreater(a, 0)
        finally:
            os.unlink(path)


class TestSidechain(unittest.TestCase):
    def test_sidechain_tokens_are_not_dropped_from_totals(self):
        """Subagent turns live in their own context but are still billed."""
        recs = [assistant("m0", 0, 1000),
                assistant("s0", 0, 7777, sidechain=True),
                assistant("m1", 1000, 500)]
        path = write_log(recs)
        try:
            sess = parse_session(path)
            an = carry.analyse_session(sess)
            self.assertEqual(len(an.turns), 3)
            self.assertEqual(sum(t.write for t in an.turns), 1000 + 7777 + 500)
        finally:
            os.unlink(path)


class TestLiveStatusline(unittest.TestCase):
    """The in-session signal. It renders on every keystroke-ish update, so it
    must never raise and must never block."""

    OPUS = {"id": "claude-opus-5", "display_name": "Opus 5"}

    def _payload(self, ctx, transcript="", **cache):
        return {"model": self.OPUS, "transcript_path": transcript,
                "context_window": {"total_input_tokens": ctx,
                                   "used_percentage": ctx / 10000,
                                   "context_window_size": 1_000_000},
                "prompt_cache": cache}

    def test_breakeven_shrinks_as_context_grows(self):
        rate = pricing.rate_for("claude-opus-5")
        small = live.breakeven_turns(100_000, 54_000, rate)
        large = live.breakeven_turns(500_000, 54_000, rate)
        self.assertGreater(small, large)
        self.assertAlmostEqual(small, 20 * 54_000 / 46_000, places=6)

    def test_no_breakeven_below_the_standing_context(self):
        rate = pricing.rate_for("claude-opus-5")
        self.assertIsNone(live.breakeven_turns(40_000, 54_000, rate))
        self.assertIsNone(live.breakeven_turns(0, 54_000, rate))

    def test_renders_before_the_first_api_response(self):
        out = live.render({"model": self.OPUS, "context_window": {}})
        self.assertIn("Opus 5", out)
        self.assertNotIn("$", out)

    def test_survives_missing_and_null_fields(self):
        for payload in ({}, {"model": None}, {"context_window": None},
                        {"context_window": {"total_input_tokens": None,
                                            "used_percentage": None}},
                        {"prompt_cache": None, "context_window": {}}):
            self.assertIsInstance(live.render(payload), str)

    def test_warns_before_the_cache_goes_cold(self):
        p = self._payload(300_000, warm=True, ttl="1h",
                          expires_at=1000.0 + 300,
                          recache_tokens_if_cold=300_000)
        self.assertIn("$3.00", live.render(p, now=1000.0))

    def test_no_cold_warning_when_the_cache_has_hours_left(self):
        p = self._payload(300_000, warm=True, ttl="1h",
                          expires_at=1000.0 + 3600,
                          recache_tokens_if_cold=300_000)
        self.assertNotIn("$3.00", live.render(p, now=1000.0))

    def test_bad_stdin_yields_an_empty_line_not_a_crash(self):
        import io
        self.assertEqual(live.main(io.StringIO("not json")), "")
        self.assertEqual(live.main(io.StringIO("[1,2,3]")), "")


class TestOutputEncoding(unittest.TestCase):
    """Chinese is the default output language, and Windows consoles still
    default to a legacy code page. Without forcing UTF-8 the tool aborts with
    UnicodeEncodeError before printing anything."""

    def test_report_survives_a_legacy_codepage(self):
        import io

        from cc_token_audit import cli, i18n
        i18n.set_lang("zh-TW")
        legacy = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
        real = sys.stdout
        sys.stdout = legacy
        try:
            cli._force_utf8()
            print(i18n.t("title"))
            legacy.flush()
        finally:
            sys.stdout = real
        self.assertEqual(legacy.encoding, "utf-8")

    def test_every_key_exists_in_both_languages(self):
        from cc_token_audit import i18n
        zh = set(i18n.STRINGS["zh-TW"])
        en = set(i18n.STRINGS["en"])
        self.assertEqual(zh - en, set(), "keys missing from en")
        self.assertEqual(en - zh, set(), "keys missing from zh-TW")


if __name__ == "__main__":
    unittest.main(verbosity=2)
