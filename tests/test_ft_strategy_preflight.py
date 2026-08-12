"""Tests for D-FT-24 preflight gate (6 checks).

Each check is exercised in isolation. Happy path = all 6 pass.
"""

from __future__ import annotations

import pytest

from app.ft_strategy.preflight import (
    ALLOWED_TIMEFRAMES,
    PreflightCheck,
    PreflightRequest,
    _check_ast_and_methods,
    _check_data_file,
    _check_imports,
    _check_informative_timeframes,
    _check_param_keys,
    _check_research_md_length,
    module_constants,
    run_preflight,
)


# ---------------------------------------------------------------------------
# Sample strategy text — covers all positive cases
# ---------------------------------------------------------------------------


SAMPLE_GOOD_STRATEGY = '''
from freqtrade.strategy import IStrategy
from freqtrade.strategy.parameters import IntParameter
import talib.abstract as ta

class MyRSI(IStrategy):
    """Sample mean-reversion strategy."""
    timeframe = "5m"
    buy_rsi = IntParameter(10, 30, default=20)
    sell_rsi = IntParameter(70, 90, default=80)

    @informative("1h")
    def populate_indicators_1h(self, dataframe, metadata):
        dataframe["rsi"] = ta.RSI(dataframe, 14)
        return dataframe

    @informative("BTC/USDT", "1h")
    def populate_btc_1h(self, dataframe, metadata):
        return dataframe

    def populate_indicators(self, dataframe, metadata):
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["ema"] = ta.EMA(dataframe, timeperiod=21)
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        dataframe.loc[(dataframe["rsi"] < 30), "enter_long"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        dataframe.loc[(dataframe["rsi"] > 70), "exit_long"] = 1
        return dataframe
'''


GOOD_RESEARCH_MD = (
    "## Decision\nbuy on RSI<30\n"
    "## Question\nDoes this work?\n"
    "## Motivation\nTest\n"
    "## Universe\nBTC/USDT\n"
    "## Constraints\nleverage=1\n"
    "## Failure modes\nDD > 12%\n"
    "## Open Qs\n4h context?\n" + ("x" * 200)
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _request(**kwargs):
    defaults = {
        "strategy_text": SAMPLE_GOOD_STRATEGY,
        "research_md": GOOD_RESEARCH_MD,
        "pair": "BTC/USDT",
        "interval": "5m",
        "user_data_dir": None,
        "hyperopt_spaces": ("buy_rsi", "sell_rsi"),
    }
    defaults.update(kwargs)
    return PreflightRequest(**defaults)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


class TestCheckAstAndMethods:
    def test_valid_strategy_passes(self):
        c = _check_ast_and_methods(SAMPLE_GOOD_STRATEGY)
        assert c.passed

    def test_missing_methods_fails(self):
        text = "from x import y\nclass A:\n    pass\n"
        c = _check_ast_and_methods(text)
        assert not c.passed
        assert "missing required methods" in c.note

    def test_syntax_error_fails(self):
        text = "def broken(:\n    pass\n"
        c = _check_ast_and_methods(text)
        assert not c.passed
        assert "syntax error" in c.note

    def test_partial_methods_fails(self):
        text = '''
class A:
    def populate_indicators(self):
        pass
'''
        c = _check_ast_and_methods(text)
        assert not c.passed
        assert "populate_entry_trend" in c.note


class TestCheckImports:
    def test_all_imports_present(self):
        assert _check_imports(SAMPLE_GOOD_STRATEGY).passed

    def test_missing_isstrategy(self):
        text = "import talib.abstract as ta\nclass A: pass\n"
        c = _check_imports(text)
        assert not c.passed
        assert "IStrategy" in c.note

    def test_missing_ta(self):
        text = "from freqtrade.strategy import IStrategy\nclass A: pass\n"
        c = _check_imports(text)
        assert not c.passed
        assert any(t in c.note for t in ("ta.RSI", "ta.EMA"))


class TestCheckInformativeTf:
    def test_no_informative_passes(self):
        c = _check_informative_timeframes("class A: pass\n")
        assert c.passed

    def test_valid_timeframes_pass(self):
        c = _check_informative_timeframes('''
@informative("1h")
def f(self, df, md): pass

@informative("4h")
def f2(self, df, md): pass
''')
        assert c.passed

    def test_invalid_timeframe_fails(self):
        c = _check_informative_timeframes('''
@informative("7y")
def f(self, df, md): pass
''')
        assert not c.passed
        assert "7y" in c.note

    def test_double_quote_variants(self):
        c = _check_informative_timeframes('''
@informative("1h")
def a(self, df, md): pass

@informative("4h")
def b(self, df, md): pass
''')
        assert c.passed


class TestCheckDataFile:
    def test_no_user_data_dir_passes(self):
        c = _check_data_file("BTC/USDT", "5m", None)
        assert c.passed
        assert "skipping" in c.note

    def test_existing_file_passes(self, tmp_path):
        d = tmp_path / "data"
        d.mkdir()
        (d / "BTC_USDT-5m.feather").touch()
        c = _check_data_file("BTC/USDT", "5m", str(tmp_path))
        assert c.passed
        assert "feather" in c.note

    def test_csv_extension_fallback(self, tmp_path):
        d = tmp_path / "data"
        d.mkdir()
        (d / "BTC_USDT-5m.csv").touch()
        c = _check_data_file("BTC/USDT", "5m", str(tmp_path))
        assert c.passed

    def test_missing_file_fails(self, tmp_path):
        d = tmp_path / "data"
        d.mkdir()
        c = _check_data_file("ETH/USDT", "1h", str(tmp_path))
        assert not c.passed
        assert "run prepare.py" in c.note


class TestCheckParamKeys:
    def test_no_spaces_skips(self):
        c = _check_param_keys("class A: pass", None)
        assert c.passed
        assert "skipping" in c.note

    def test_empty_spaces_tuple_skips(self):
        c = _check_param_keys("class A: pass", ())
        assert c.passed

    def test_all_params_referenced(self):
        c = _check_param_keys("buy_rsi and sell_rsi and stop_loss", ("buy_rsi", "sell_rsi"))
        assert c.passed

    def test_missing_param_referenced_only(self):
        # Text references only buy_rsi, but spaces require both
        c = _check_param_keys("buy_rsi", ("buy_rsi", "missing_param"))
        assert not c.passed
        assert "missing_param" in c.note


class TestCheckResearchMdLength:
    def test_long_enough(self):
        c = _check_research_md_length("x" * 200)
        assert c.passed

    def test_too_short(self):
        c = _check_research_md_length("x" * 50)
        assert not c.passed
        assert "200" in c.note

    def test_exactly_200(self):
        c = _check_research_md_length("x" * 200)
        assert c.passed

    def test_exactly_199_fails(self):
        c = _check_research_md_length("x" * 199)
        assert not c.passed


# ---------------------------------------------------------------------------
# run_preflight integration
# ---------------------------------------------------------------------------


class TestRunPreflightHappyPath:
    def test_all_six_pass(self, tmp_path):
        d = tmp_path / "data"
        d.mkdir()
        (d / "BTC_USDT-5m.feather").touch()
        r = run_preflight(_request(
            user_data_dir=str(tmp_path),
            hyperopt_spaces=("buy_rsi", "sell_rsi"),
        ))
        assert r.ok, [i.label for i in r.items if not i.passed]
        assert len(r.items) == 6

    def test_dash_labels(self, tmp_path):
        d = tmp_path / "data"
        d.mkdir()
        (d / "BTC_USDT-5m.feather").touch()
        r = run_preflight(_request(user_data_dir=str(tmp_path)))
        labels = [i.label for i in r.items]
        assert "ast_methods" in labels
        assert "imports" in labels
        assert "informative_tf" in labels
        assert "data_file_exists" in labels
        assert "param_in_set" in labels
        assert "research_md_length" in labels


class TestRunPreflightFailures:
    def test_syntax_error_blocks(self):
        r = run_preflight(_request(strategy_text="def bad(:\n    pass"))
        assert not r.ok
        # ast_methods OR ast_parse — both indicate AST failure
        assert ("ast_methods" in r.failing_labels) or ("ast_parse" in r.failing_labels)

    def test_missing_methods_blocks(self):
        r = run_preflight(_request(strategy_text="class A:\n    pass\n"))
        assert not r.ok
        # ast_methods OR ast_parse — both indicate AST failure
        assert ("ast_methods" in r.failing_labels) or ("ast_parse" in r.failing_labels)

    def test_invalid_timeframe_blocks(self):
        text = SAMPLE_GOOD_STRATEGY.replace(
            '@informative("1h")',
            '@informative("99m")',
        )
        r = run_preflight(_request(strategy_text=text))
        assert not r.ok
        assert "informative_tf" in r.failing_labels

    def test_missing_data_file_blocks(self, tmp_path):
        r = run_preflight(_request(user_data_dir=str(tmp_path)))
        assert not r.ok
        assert "data_file_exists" in r.failing_labels

    def test_short_research_md_blocks(self):
        r = run_preflight(_request(research_md="short"))
        assert not r.ok
        assert "research_md_length" in r.failing_labels

    def test_multiple_failures_listed(self):
        r = run_preflight(_request(
            strategy_text="class A: pass\n",  # syntax ok but no methods
            research_md="short",
        ))
        assert not r.ok
        # ast_methods OR ast_parse — both indicate AST failure
        assert ("ast_methods" in r.failing_labels) or ("ast_parse" in r.failing_labels)
        assert "research_md_length" in r.failing_labels


class TestRunPreflightDefensive:
    def test_non_request_returns_failed(self):
        r = run_preflight({"not": "a request"})  # type: ignore[arg-type]
        assert not r.ok
        assert "type_check" in r.failing_labels


class TestToDict:
    def test_happy_to_dict(self, tmp_path):
        d = tmp_path / "data"
        d.mkdir()
        (d / "BTC_USDT-5m.feather").touch()
        r = run_preflight(_request(user_data_dir=str(tmp_path)))
        d_dict = r.to_dict()
        assert d_dict["ok"] is True
        assert d_dict["failing_labels"] == []

    def test_failure_to_dict(self):
        r = run_preflight(_request(research_md="x"))
        d_dict = r.to_dict()
        assert d_dict["ok"] is False
        assert "research_md_length" in d_dict["failing_labels"]


# ---------------------------------------------------------------------------
# Constants + dataclass helpers
# ---------------------------------------------------------------------------


class TestModuleConstants:
    def test_keys_present(self):
        c = module_constants()
        assert "ALLOWED_TIMEFRAMES" in c
        assert "REQUIRED_METHODS" in c
        assert "REQUIRED_IMPORTS" in c

    def test_timeframes(self):
        c = module_constants()
        assert c["ALLOWED_TIMEFRAMES"] == sorted(ALLOWED_TIMEFRAMES)

    def test_research_md_min_length(self):
        assert module_constants()["RESEARCH_MD_MIN_LENGTH"] == 200


class TestDataclassFrozen:
    def test_preflight_request_frozen(self):
        r = _request()
        with pytest.raises(Exception):
            r.strategy_text = "modified"  # type: ignore[misc]

    def test_preflight_check_frozen(self):
        c = PreflightCheck(label="x", passed=True)
        with pytest.raises(Exception):
            c.label = "modified"  # type: ignore[misc]
