#!/usr/bin/env python3
"""Tests for scripts/collect.py -- stdlib unittest only, no third-party deps.

Several of these are regression tests for bugs found empirically while
building Atlas, not hypothetical edge cases:
  * message-id dedup (usage blocks repeat once per content block; the first
    cut of this plugin measured 1.8x inflation before dedup was added)
  * cache-write TTL split (a flat 1.25x multiplier understated real spend by
    ~18% on a real account where 100% of writes were 1-hour)
  * the fast-mode lever silently vanishing because compute_levers() once
    read root["fast_finding"] before it was assigned
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import collect  # noqa: E402


# A small, hand-verifiable pricing table -- deliberately not pricing.json, so
# these tests don't silently start failing (or silently drift) when real
# rates change. The two model-round-trip tests below exercise pricing.json
# directly instead.
PRICING = {
    "cache_read_multiplier": 0.1,
    "cache_write_1h_multiplier": 2.0,
    "cache_write_5m_multiplier": 1.25,
    "fast_fallback_multiplier": 2.0,
    "models": {
        "claude-opus-5": {"input": 10.0, "output": 20.0, "fast": {"input": 20.0, "output": 40.0}},
        "claude-sonnet-5": {"input": 4.0, "output": 8.0},
        "claude-haiku-4-5": {"input": 1.0, "output": 2.0},
        "unknown": {"input": 4.0, "output": 8.0},
    },
    "fallback_order": ["opus", "sonnet", "haiku"],
    "fallback_tiers": {"opus": "claude-opus-5", "sonnet": "claude-sonnet-5",
                       "haiku": "claude-haiku-4-5", "_default": "unknown"},
    "downgrade_targets": {"sonnet": "claude-sonnet-5", "haiku": "claude-haiku-4-5"},
    "tier_rank": {"claude-opus-5": 4, "claude-sonnet-5": 2, "claude-haiku-4-5": 1, "unknown": 2},
}


def u(**overrides) -> dict:
    d = collect.blank_usage()
    d.update(overrides)
    return d


# --------------------------------------------------------------------------
# cost math
# --------------------------------------------------------------------------

class TestCostMath(unittest.TestCase):
    def test_cache_write_1h_bills_double_5m(self):
        """Regression: a flat multiplier was applied before the TTL split existed."""
        cost_1h = collect.cost_of(u(cache_write_1h=1_000_000), "claude-opus-5", PRICING)
        cost_5m = collect.cost_of(u(cache_write_5m=1_000_000), "claude-opus-5", PRICING)
        # input rate $10/MTok: 1h = 10*2.0 = $20, 5m = 10*1.25 = $12.50
        self.assertAlmostEqual(cost_1h, 20.0, places=6)
        self.assertAlmostEqual(cost_5m, 12.5, places=6)
        self.assertAlmostEqual(cost_1h / cost_5m, 2.0 / 1.25, places=6)

    def test_cache_read_is_a_tenth_of_input(self):
        full = collect.cost_of(u(input=1_000_000), "claude-opus-5", PRICING)
        cached = collect.cost_of(u(cache_read=1_000_000), "claude-opus-5", PRICING)
        self.assertAlmostEqual(cached, full * PRICING["cache_read_multiplier"], places=6)

    def test_fast_mode_uses_fast_rate_when_present(self):
        standard = collect.cost_of(u(output=1_000_000), "claude-opus-5", PRICING, fast=False)
        fast = collect.cost_of(u(output=1_000_000), "claude-opus-5", PRICING, fast=True)
        self.assertAlmostEqual(standard, 20.0, places=6)  # $20/MTok output
        self.assertAlmostEqual(fast, 40.0, places=6)      # fast table: $40/MTok output

    def test_fast_mode_falls_back_to_multiplier_when_no_fast_table(self):
        # claude-sonnet-5 has no "fast" entry in PRICING -- must use fast_fallback_multiplier
        standard = collect.rate_for("claude-sonnet-5", PRICING, fast=False)
        fast = collect.rate_for("claude-sonnet-5", PRICING, fast=True)
        self.assertEqual(fast["input"], standard["input"] * PRICING["fast_fallback_multiplier"])

    def test_unknown_model_falls_back_by_tier_substring(self):
        # "some-org/claude-sonnet-5-custom" isn't a key in PRICING["models"], but
        # contains "sonnet" -- must resolve to the sonnet tier rate, not zero
        # and not the bare "unknown" catch-all (which differs here on purpose).
        r = collect.rate_for("my-fork-of-claude-sonnet-5", PRICING)
        self.assertEqual(r, PRICING["models"]["claude-sonnet-5"])

    def test_totally_unrecognized_model_uses_default_not_zero(self):
        r = collect.rate_for("some-future-model-xyz", PRICING)
        self.assertEqual(r, PRICING["models"]["unknown"])
        self.assertGreater(r["input"], 0)

    def test_real_pricing_json_loads_and_prices_a_known_model(self):
        # Sanity check against the actual shipped pricing.json, so a schema
        # change there (renamed key, wrong type) fails a test instead of
        # silently producing $0.00 in the dashboard.
        plugin_root = Path(__file__).resolve().parent.parent
        pricing = collect.load_pricing(plugin_root)
        cost = collect.cost_of(u(input=1_000_000, output=1_000_000), "claude-opus-5", pricing)
        self.assertGreater(cost, 0)


# --------------------------------------------------------------------------
# usage accumulation
# --------------------------------------------------------------------------

class TestUsageHelpers(unittest.TestCase):
    def test_add_usage_sums_every_key(self):
        a = u(input=1, output=2, cache_read=3, cache_creation=4, cache_write_1h=5, cache_write_5m=6)
        b = u(input=10, output=20, cache_read=30, cache_creation=40, cache_write_1h=50, cache_write_5m=60)
        collect.add_usage(a, b)
        self.assertEqual(a, u(input=11, output=22, cache_read=33, cache_creation=44,
                              cache_write_1h=55, cache_write_5m=66))

    def test_total_of_excludes_ttl_split_fields(self):
        # total_of() sums input+output+cache_read+cache_creation only -- the
        # cache_write_1h/5m fields are a breakdown OF cache_creation, not
        # additional tokens, so including them would double-count.
        usage = u(input=10, output=10, cache_read=10, cache_creation=10,
                  cache_write_1h=10, cache_write_5m=0)
        self.assertEqual(collect.total_of(usage), 40)


# --------------------------------------------------------------------------
# transcript parsing (end-to-end against real temp files)
# --------------------------------------------------------------------------

def assistant_line(msg_id, model="claude-opus-5", input_tok=100, output_tok=50,
                    cache_read=0, cache_write_1h=0, cache_write_5m=0, speed="standard",
                    cwd="/tmp/proj", ts="2026-08-01T10:00:00Z", tools=(), thinking=False):
    content = []
    if thinking:
        content.append({"type": "thinking", "thinking": ""})
    for name in tools:
        content.append({"type": "tool_use", "name": name})
    content.append({"type": "text", "text": "ok"})
    rec = {
        "type": "assistant", "timestamp": ts, "cwd": cwd,
        "message": {
            "id": msg_id, "model": model, "stop_reason": "end_turn", "content": content,
            "usage": {
                "input_tokens": input_tok, "output_tokens": output_tok,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_write_1h + cache_write_5m,
                "cache_creation": {"ephemeral_1h_input_tokens": cache_write_1h,
                                   "ephemeral_5m_input_tokens": cache_write_5m},
                "speed": speed,
                "server_tool_use": {"web_search_requests": 0, "web_fetch_requests": 0},
            },
        },
    }
    # Compact separators: real transcripts have no space after ':' or ',',
    # and parse_session's cwd extraction is a literal substring match on
    # '"cwd":"' -- json.dumps' default spacing would silently break that.
    return json.dumps(rec, separators=(",", ":")) + "\n"


def user_line(ts="2026-08-01T09:59:00Z"):
    return json.dumps({"type": "user", "timestamp": ts}, separators=(",", ":")) + "\n"


class TestParseSession(unittest.TestCase):
    def _write(self, lines: list[str]) -> Path:
        d = Path(self._tmp.name)
        f = d / "session.jsonl"
        f.write_text("".join(lines), encoding="utf-8")
        return f

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def test_duplicate_message_id_counted_once(self):
        """The exact real-world bug: one content block per line, same usage,
        same message id -- naive summing inflated totals 1.8x on real data."""
        line = assistant_line("msg_1", input_tok=1000, output_tok=500)
        f = self._write([user_line(), line, line, line])  # same line 3x
        s = collect.parse_session(f)
        self.assertEqual(s["messages"]["assistant"], 1)
        self.assertEqual(s["usage"]["input"], 1000)
        self.assertEqual(s["usage"]["output"], 500)

    def test_distinct_message_ids_each_counted(self):
        f = self._write([
            assistant_line("msg_1", input_tok=100),
            assistant_line("msg_2", input_tok=200),
        ])
        s = collect.parse_session(f)
        self.assertEqual(s["messages"]["assistant"], 2)
        self.assertEqual(s["usage"]["input"], 300)

    def test_cwd_takes_the_modal_value_not_first_seen(self):
        """Regression: a session that briefly visited another directory (a
        worktree, a /tmp checkout) was mislabeled by taking the first cwd
        seen. The project should be identified by where most turns happened."""
        f = self._write([
            assistant_line("msg_1", cwd="/tmp/detour"),
            assistant_line("msg_2", cwd="/Users/x/real-project"),
            assistant_line("msg_3", cwd="/Users/x/real-project"),
            assistant_line("msg_4", cwd="/Users/x/real-project"),
        ])
        s = collect.parse_session(f)
        self.assertEqual(s["cwd"], "/Users/x/real-project")

    def test_cache_write_ttl_split_flows_through(self):
        f = self._write([assistant_line("msg_1", cache_write_1h=500, cache_write_5m=100)])
        s = collect.parse_session(f)
        self.assertEqual(s["usage"]["cache_write_1h"], 500)
        self.assertEqual(s["usage"]["cache_write_5m"], 100)
        self.assertEqual(s["usage"]["cache_creation"], 600)

    def test_fast_turns_counted(self):
        f = self._write([
            assistant_line("msg_1", speed="fast"),
            assistant_line("msg_2", speed="standard"),
        ])
        s = collect.parse_session(f)
        self.assertEqual(s["fast_turns"], 1)

    def test_tool_use_classified_and_thinking_flagged(self):
        f = self._write([assistant_line("msg_1", tools=["Bash", "Read"], thinking=True)])
        s = collect.parse_session(f)
        self.assertEqual(s["tools"]["Bash"], 1)
        self.assertEqual(s["tools"]["Read"], 1)
        self.assertEqual(s["tool_classes"]["exec"], 1)  # Bash
        self.assertEqual(s["tool_classes"]["read"], 1)  # Read
        self.assertEqual(s["thinking_turns"], 1)

    def test_empty_transcript_returns_none(self):
        f = self._write([user_line()])  # no assistant records at all
        self.assertIsNone(collect.parse_session(f))

    def test_multiple_models_in_one_session(self):
        f = self._write([
            assistant_line("msg_1", model="claude-opus-5", input_tok=100),
            assistant_line("msg_2", model="claude-haiku-4-5", input_tok=50),
        ])
        s = collect.parse_session(f)
        self.assertIn("claude-opus-5", s["models"])
        self.assertIn("claude-haiku-4-5", s["models"])
        self.assertEqual(s["models"]["claude-opus-5"]["std"]["input"], 100)
        self.assertEqual(s["models"]["claude-haiku-4-5"]["std"]["input"], 50)


# --------------------------------------------------------------------------
# fast-mode finding
# --------------------------------------------------------------------------

class TestFastModeFinding(unittest.TestCase):
    def test_finds_a_real_premium(self):
        node = {"models": {
            "claude-opus-5": {"fast_messages": 3, "fast": u(output=100_000), "std": u()},
        }}
        f = collect.fast_mode_finding(node, PRICING)
        self.assertIsNotNone(f)
        self.assertEqual(f["turns"], 3)
        # output 100k tokens: fast $40/MTok vs standard $20/MTok -> premium = $2.00
        self.assertAlmostEqual(f["premium"], 2.0, places=6)

    def test_none_when_no_fast_turns(self):
        node = {"models": {"claude-opus-5": {"fast_messages": 0, "fast": u(), "std": u()}}}
        self.assertIsNone(collect.fast_mode_finding(node, PRICING))

    def test_none_when_premium_negligible(self):
        node = {"models": {"claude-opus-5": {"fast_messages": 1, "fast": u(output=1), "std": u()}}}
        self.assertIsNone(collect.fast_mode_finding(node, PRICING))


# --------------------------------------------------------------------------
# cost levers
# --------------------------------------------------------------------------

class TestComputeLevers(unittest.TestCase):
    def test_fast_mode_lever_appears_when_fast_finding_present(self):
        """Regression: compute_levers once read root['fast_finding'] before it
        was assigned in the same dict literal, silently dropping this lever."""
        root = {
            "usage": u(input=1_000_000, cache_write_1h=0, cache_write_5m=0,
                      cache_read=0, cache_creation=0),
            "models": {"claude-opus-5": {"usage": u(input=1_000_000)}},
            "fast_finding": {"turns": 5, "premium": 12.34},
        }
        levers = collect.compute_levers(root, PRICING)
        ids = {lv["id"] for lv in levers}
        self.assertIn("fast_mode", ids)
        fast_lever = next(lv for lv in levers if lv["id"] == "fast_mode")
        self.assertAlmostEqual(fast_lever["amount"], 12.34, places=6)
        self.assertTrue(fast_lever["actionable"])

    def test_cache_ttl_lever_present_and_not_actionable(self):
        root = {
            "usage": u(input=1_000_000, cache_write_1h=500_000, cache_write_5m=0,
                      cache_read=0, cache_creation=500_000),
            "models": {"claude-opus-5": {"usage": u(input=1_000_000)}},
            "fast_finding": None,
        }
        levers = collect.compute_levers(root, PRICING)
        ttl = next(lv for lv in levers if lv["id"] == "cache_ttl")
        self.assertFalse(ttl["actionable"])
        self.assertGreater(ttl["amount"], 0)

    def test_no_levers_on_clean_usage(self):
        # hit rate = cache_read / (cache_read + cache_creation + input)
        #          = 900_000 / (900_000 + 0 + 100_000) = 0.90 -- above the 0.85 floor
        root = {
            "usage": u(input=100_000, cache_read=900_000),
            "models": {"claude-opus-5": {"usage": u(input=100_000, cache_read=900_000)}},
            "fast_finding": None,
        }
        levers = collect.compute_levers(root, PRICING)
        self.assertEqual(levers, [])  # no 1h writes, no fast turns, cache hit rate is high


# --------------------------------------------------------------------------
# recommender
# --------------------------------------------------------------------------

def fake_session(turns, cost, primary_model, heavy_ratio, think_rate, avg_output):
    """A session dict with just enough shape for assign_recommendations()."""
    write_calls = round(heavy_ratio * 100)
    tool_classes = {"read": 100 - write_calls, "write": write_calls, "exec": 0, "other": 0}
    inner = {"turns": turns, "tool_classes": tool_classes,
             "usage": u(output=round(avg_output * turns)), "thinking_turns": round(think_rate * turns)}
    score = collect.score_session(inner)
    std = u(input=100 * turns, output=round(avg_output * turns))
    return {
        "turns": turns, "cost": cost, "primary_model": primary_model,
        "score": score, "models": {primary_model: {"std": std, "fast": u()}},
    }


class TestRecommender(unittest.TestCase):
    def test_heavy_edit_session_never_recommended(self):
        """Regression: an earlier version flagged a 93%-reasoning session with
        the reason 'read-only work' -- a literally false claim. Heavy edit/exec
        work must be disqualified before any relative ranking runs."""
        sessions = [
            fake_session(turns=50, cost=10.0, primary_model="claude-opus-5",
                        heavy_ratio=0.90, think_rate=0.10, avg_output=800),
            # a second, unremarkable session so the cohort isn't trivially small
            fake_session(turns=20, cost=2.0, primary_model="claude-opus-5",
                        heavy_ratio=0.10, think_rate=0.10, avg_output=200),
        ]
        collect.assign_recommendations(sessions, PRICING)
        self.assertIsNone(sessions[0]["recommendation"])

    def test_routine_session_gets_a_recommendation_with_true_reasons(self):
        sessions = [
            fake_session(turns=10, cost=5.0, primary_model="claude-opus-5",
                        heavy_ratio=0.05, think_rate=0.05, avg_output=150),
            fake_session(turns=50, cost=8.0, primary_model="claude-opus-5",
                        heavy_ratio=0.60, think_rate=0.60, avg_output=900),
        ]
        collect.assign_recommendations(sessions, PRICING)
        r = sessions[0]["recommendation"]
        self.assertIsNotNone(r)
        self.assertGreater(r["saving"], 0)
        # every reason must be truthfully derivable from the session's own metrics
        m = r["metrics"]
        for reason in r["reasons"]:
            if "read-only tool use" in reason:
                self.assertLessEqual(m["heavy_tool_ratio"], 0.30)
            if "short replies" in reason:
                self.assertLessEqual(m["avg_output"], 450)
            if reason.startswith("only") and "turns" in reason:
                self.assertLessEqual(m["turns"], 25)

    def test_cheap_sessions_are_not_candidates(self):
        # below the $0.25 floor -- too little signal to act on
        sessions = [fake_session(turns=10, cost=0.05, primary_model="claude-opus-5",
                                 heavy_ratio=0.0, think_rate=0.0, avg_output=50)]
        collect.assign_recommendations(sessions, PRICING)
        self.assertIsNone(sessions[0]["recommendation"])

    def test_already_cheap_model_is_never_a_candidate(self):
        sessions = [fake_session(turns=10, cost=5.0, primary_model="claude-sonnet-5",
                                 heavy_ratio=0.0, think_rate=0.0, avg_output=50)]
        collect.assign_recommendations(sessions, PRICING)
        self.assertIsNone(sessions[0]["recommendation"])

    def test_target_is_never_a_more_expensive_tier(self):
        sessions = [fake_session(turns=10, cost=5.0, primary_model="claude-opus-5",
                                 heavy_ratio=0.0, think_rate=0.0, avg_output=50)]
        collect.assign_recommendations(sessions, PRICING)
        r = sessions[0]["recommendation"]
        if r:
            self.assertLess(PRICING["tier_rank"][r["target"]], PRICING["tier_rank"]["claude-opus-5"])


# --------------------------------------------------------------------------
# roll_up aggregation
# --------------------------------------------------------------------------

class TestRollUp(unittest.TestCase):
    def test_aggregates_usage_and_models_across_children(self):
        child_a = {
            "usage": u(input=100), "models": {"claude-opus-5": {"std": u(input=100), "fast": u(),
                       "messages": 1, "fast_messages": 0, "thinking_turns": 0}},
            "daily": {}, "hours": {}, "tools": {"Bash": 2},
            "tool_classes": {"read": 0, "write": 0, "exec": 2, "other": 0},
            "stop_reasons": {"end_turn": 1}, "turns": 1, "thinking_turns": 0,
            "fast_turns": 0, "web_search": 0, "web_fetch": 0, "duration_minutes": 5.0,
        }
        child_b = {
            "usage": u(input=200), "models": {"claude-opus-5": {"std": u(input=200), "fast": u(),
                       "messages": 1, "fast_messages": 0, "thinking_turns": 0}},
            "daily": {}, "hours": {}, "tools": {"Bash": 3},
            "tool_classes": {"read": 0, "write": 0, "exec": 3, "other": 0},
            "stop_reasons": {"end_turn": 1}, "turns": 1, "thinking_turns": 0,
            "fast_turns": 0, "web_search": 0, "web_fetch": 0, "duration_minutes": 5.0,
        }
        agg = collect.roll_up([child_a, child_b], PRICING)
        self.assertEqual(agg["usage"]["input"], 300)
        self.assertEqual(agg["models"]["claude-opus-5"]["usage"]["input"], 300)
        self.assertEqual(agg["tools"]["Bash"], 5)
        self.assertEqual(agg["tool_classes"]["exec"], 5)
        self.assertEqual(agg["duration_minutes"], 10.0)


if __name__ == "__main__":
    unittest.main()
