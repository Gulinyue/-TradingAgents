"""
Regression tests for runner.py parsing layer.

Covers the bugs fixed during v1 backfill development:
  1. _parse_ta_result finds eval_results/ log files
  2. _normalize_decision handles markdown bold, "Do NOT ADD" not misidentified as ADD
  3. technical_report/nonempty fields are preserved from log
  4. date/datetime/Decimal serialize safely via _deep_float
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from runner import _normalize_decision, _parse_ta_result
import runner


# ─────────────────────────────────────────────────────────────────────────────
# _normalize_decision tests
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalizeDecision(unittest.TestCase):

    def test_hold_in_markdown_bold(self):
        """Rating: **HOLD** should return HOLD, not REVIEW or ADD."""
        text = "## 1. Rating: **HOLD**"
        self.assertEqual(_normalize_decision(text), "HOLD")

    def test_do_not_add_not_misidentified_as_add(self):
        """'Do NOT ADD' should NOT match ADD keyword."""
        text = "Do NOT ADD new capital at current levels"
        self.assertNotEqual(_normalize_decision(text), "ADD")
        # Should fall through to REVIEW
        self.assertEqual(_normalize_decision(text), "REVIEW")

    def test_buy_enter(self):
        self.assertEqual(_normalize_decision("FINAL TRANSACTION PROPOSAL: **BUY**"), "ENTER")
        self.assertEqual(_normalize_decision("Rating: **ENTER**"), "ENTER")

    def test_sell(self):
        self.assertEqual(_normalize_decision("## Rating: **SELL**"), "SELL")
        self.assertEqual(_normalize_decision("Recommendation: SELL"), "SELL")

    def test_trim(self):
        self.assertEqual(_normalize_decision("Position: TRIM"), "TRIM")
        self.assertEqual(_normalize_decision("建议减仓"), "TRIM")

    def test_exit(self):
        self.assertEqual(_normalize_decision("清仓策略"), "EXIT")
        self.assertEqual(_normalize_decision("平仓"), "EXIT")

    def test_avoid(self):
        self.assertEqual(_normalize_decision("规避该标的"), "AVOID")
        self.assertEqual(_normalize_decision("AVOID"), "AVOID")

    def test_hold(self):
        self.assertEqual(_normalize_decision("建议持有"), "HOLD")
        self.assertEqual(_normalize_decision("持仓观望"), "HOLD")

    def test_review(self):
        self.assertEqual(_normalize_decision("待进一步确认"), "REVIEW")
        self.assertEqual(_normalize_decision("No decision can be made"), "REVIEW")

    def test_empty_defaults_to_review(self):
        self.assertEqual(_normalize_decision(""), "REVIEW")
        self.assertEqual(_normalize_decision(None), "REVIEW")

    def test_add_without_negation(self):
        """ADD without 'Do NOT' should still return ADD."""
        text = "建议适当加仓，前景良好"
        self.assertEqual(_normalize_decision(text), "ADD")


# ─────────────────────────────────────────────────────────────────────────────
# _deep_float tests
# ─────────────────────────────────────────────────────────────────────────────

class TestDeepFloat(unittest.TestCase):

    def test_decimal_serialization(self):
        from decimal import Decimal
        result = runner._deep_float({"price": Decimal("1416.02"), "qty": 100})
        self.assertIsInstance(result["price"], float)
        self.assertEqual(result["price"], 1416.02)

    def test_nested_decimal(self):
        from decimal import Decimal
        result = runner._deep_float({
            "outer": {"inner": Decimal("3.14"), "list": [Decimal("1.1"), Decimal("2.2")]}
        })
        self.assertIsInstance(result["outer"]["inner"], float)
        self.assertEqual(result["outer"]["list"], [1.1, 2.2])

    def test_none_preserved(self):
        result = runner._deep_float({"a": None, "b": {"c": None}})
        self.assertIsNone(result["a"])
        self.assertIsNone(result["b"]["c"])

    def test_int_preserved(self):
        result = runner._deep_float({"qty": 100, "nested": {"count": 42}})
        self.assertIsInstance(result["qty"], int)
        self.assertEqual(result["qty"], 100)

    def test_bool_preserved(self):
        result = runner._deep_float({"flag": True, "nested": {"active": False}})
        self.assertIsInstance(result["flag"], bool)
        self.assertTrue(result["flag"])


# ─────────────────────────────────────────────────────────────────────────────
# _parse_ta_result integration tests
# ─────────────────────────────────────────────────────────────────────────────

class TestParseTaResult(unittest.TestCase):

    def test_eval_results_fallback(self):
        """Should read eval_results/600519.SH/TradingAgentsStrategy_logs/"""
        result, fallback_triggered = _parse_ta_result("600519.SH", "2026-03-29")
        self.assertIn(result["decision"], ("HOLD", "ENTER", "SELL", "ADD", "TRIM", "EXIT", "AVOID", "REVIEW"))
        # technical_report must be nonempty (it's 10k+ chars in the log)
        self.assertGreater(len(result["technical_report"]), 100)
        self.assertGreater(len(result["fundamental_report"]), 100)

    def test_parse_returns_valid_structure(self):
        """All expected keys must be present."""
        result, _ = _parse_ta_result("600519.SH", "2026-03-29")
        for key in ["decision", "technical_report", "fundamental_report",
                    "sentiment", "analyst_signals", "raw_full_report"]:
            self.assertIn(key, result)

    def test_analyst_signals_populated(self):
        result, _ = _parse_ta_result("600519.SH", "2026-03-29")
        signals = result["analyst_signals"]
        for key in ["market", "fundamentals", "sentiment", "news"]:
            self.assertIn(key, signals)
            # market report should be nonempty (it's the technical analysis)
            if key == "market":
                self.assertGreater(len(signals[key]), 100)


if __name__ == "__main__":
    unittest.main(verbosity=2)
