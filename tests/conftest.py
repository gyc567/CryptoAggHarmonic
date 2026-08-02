from unittest.mock import MagicMock, patch

import pytest

# Flask 2.x test_client references werkzeug.__version__, which was removed in
# Werkzeug 3.x. Provide a fallback so the test suite can run with the current
# dependency resolution. This is a test-only compatibility shim.
import werkzeug

if not hasattr(werkzeug, "__version__"):
    try:
        from importlib.metadata import version as _get_version

        werkzeug.__version__ = _get_version("werkzeug")
    except Exception:
        werkzeug.__version__ = "3.0.0"


@pytest.fixture(autouse=True)
def _reset_watchlist_memory_db():
    """Clear the process-local watchlist fallback dict between tests."""
    from app.infra.watchlist_store import _MEMORY_DB

    _MEMORY_DB.clear()
    yield
    _MEMORY_DB.clear()


@pytest.fixture
def mock_yahoo_candle_data():
    """Mock YahooCandleData with sample OHLC dataframe."""
    mock = MagicMock()
    mock.df = MagicMock()
    mock.symbol = "AAPL"
    mock.interval = "1d"
    return mock


@pytest.fixture
def mock_binance_candle_data():
    """Mock BinanceCandleData with sample OHLC dataframe."""
    mock = MagicMock()
    mock.df = MagicMock()
    mock.symbol = "BTCUSDT"
    mock.interval = "1d"
    return mock


@pytest.fixture
def mock_technicals():
    """Mock OHLCTechnicals."""
    mock = MagicMock()
    mock.df = MagicMock()
    return mock


@pytest.fixture
def mock_harmonic_search():
    """Mock HarmonicSearch with patterns."""
    mock = MagicMock()
    mock.XABCD = "XABCD"
    mock.ABCD = "ABCD"
    mock.ABC = "ABC"
    mock.get_patterns.return_value = {
        "XABCD": [],
        "ABCD": [],
        "ABC": [],
    }
    return mock


@pytest.fixture
def mock_divergence_search():
    """Mock DivergenceSearch."""
    mock = MagicMock()
    mock.get_patterns.return_value = {}
    return mock


@pytest.fixture
def mock_harmonic_plotter():
    """Mock HarmonicPlotter."""
    mock = MagicMock()
    mock.to_image.return_value = b"fake_image_bytes"
    return mock


@pytest.fixture
def mock_position_plotter():
    """Mock PositionPlotter."""
    mock = MagicMock()
    mock.to_image.return_value = b"fake_position_image_bytes"
    return mock


@pytest.fixture
def mock_position():
    """Mock Position."""
    mock = MagicMock()
    mock.to_dict.return_value = {
        "strike": 100.0,
        "direction": "long",
        "stop_loss": 95.0,
        "target": 110.0,
    }
    return mock


@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client."""
    with patch("app.openai_handler.client") as mock_client:
        mock_completion = MagicMock()
        mock_completion.choices = [MagicMock()]
        mock_completion.choices[0].message.content = '{"function_name": "forming_binance", "args": ["BTCUSDT", "1d"], "kwargs": {}}'
        mock_client.chat.completions.create.return_value = mock_completion
        yield mock_client


@pytest.fixture
def mock_yahoo_option_data():
    """Mock YahooOptionData."""
    mock = MagicMock()
    mock.ticker.options = ["2024-01-01"]
    return mock


@pytest.fixture
def mock_option_plotter():
    """Mock OptionPlotter."""
    mock = MagicMock()
    return mock
