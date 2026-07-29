"""Regression tests: ensure existing functionality is unchanged."""

from unittest.mock import MagicMock, patch

import pytest

from app.main import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class TestExistingRoutes:
    """Verify existing routes behave exactly as before."""

    def test_index_returns_chat_ui(self, client):
        """GET / should return the chat UI HTML page."""
        resp = client.get("/")
        assert resp.status_code == 200
        assert b"Pyharmonics Chat" in resp.data
        assert b"chat-container" in resp.data

    def test_index_content_type(self, client):
        """GET / should return text/html."""
        resp = client.get("/")
        assert resp.content_type.startswith("text/html")

    @patch("app.main.query_openai")
    @patch("app.main.parse_args")
    @patch("app.main.FUNCTION_ROUTER")
    def test_query_endpoint_success(self, mock_router, mock_parse_args, mock_query_openai, client):
        """POST /query should work as before with valid prompt."""
        mock_parse_args.return_value = (
            "forming_binance",
            ["BTCUSDT", "1d"],
            {"limit_to": 10, "percent_complete": 0.8},
        )
        mock_query_openai.return_value = '{"function_name": "forming_binance", "args": ["BTCUSDT", "1d"], "kwargs": {}}'

        mock_func = MagicMock()
        mock_func.return_value = {
            "position": MagicMock(),
            "divergences": {},
            "plot": "base64encodedimage",
        }
        mock_router.__contains__ = MagicMock(return_value=True)
        mock_router.__getitem__ = MagicMock(return_value=mock_func)

        resp = client.post("/query", json={"prompt": "Check BTCUSDT on 1d"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "response" in data
        assert "model" in data["response"]
        assert "image" in data["response"]

    @patch("app.main.query_openai")
    def test_query_endpoint_missing_prompt(self, mock_query_openai, client):
        """POST /query without prompt should return 400."""
        resp = client.post("/query", json={})
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data
        assert "Prompt is required" in data["error"]

    @patch("app.main.query_openai")
    @patch("app.main.parse_args")
    @patch("app.main.FUNCTION_ROUTER")
    def test_query_endpoint_out_of_scope(self, mock_router, mock_parse_args, mock_query_openai, client):
        """POST /query with out-of-scope function should return error message."""
        mock_parse_args.return_value = (
            "unknown_function",
            ["BTCUSDT", "1d"],
            {},
        )
        mock_query_openai.return_value = '{"function_name": "unknown_function", "args": ["BTCUSDT", "1d"], "kwargs": {}}'
        mock_router.__contains__ = MagicMock(return_value=False)

        # The endpoint accesses prompt_context['extract_args'] before the not-in-router check
        # So we need both keys present. Modify module-level dict directly.
        import app.main as main_module

        original = dict(main_module.prompt_context)
        main_module.prompt_context = {
            "extract_args": "test prompt",
            "extract_args_error": "Please ask about harmonic patterns.",
            "technical_analysis": "test analysis",
        }
        try:
            resp = client.post("/query", json={"prompt": "What is the weather?"})
            assert resp.status_code == 200
            data = resp.get_json()
            assert "response" in data
        finally:
            main_module.prompt_context = original

    @patch("app.main.query_openai")
    @patch("app.main.parse_args")
    @patch("app.main.FUNCTION_ROUTER")
    def test_query_endpoint_pyharmonics_error(self, mock_router, mock_parse_args, mock_query_openai, client):
        """POST /query should handle pyharmonics exceptions gracefully."""
        mock_parse_args.return_value = (
            "forming_binance",
            ["BTCUSDT", "1d"],
            {},
        )
        mock_query_openai.return_value = '{"function_name": "forming_binance", "args": ["BTCUSDT", "1d"], "kwargs": {}}'

        mock_func = MagicMock()
        mock_func.side_effect = Exception("Network error")
        mock_router.__contains__ = MagicMock(return_value=True)
        mock_router.__getitem__ = MagicMock(return_value=mock_func)

        resp = client.post("/query", json={"prompt": "Check BTCUSDT"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "response" in data
        assert "Pyharmonics raised" in data["response"]


class TestPyharmonicsHandlerRegression:
    """Verify pyharmonics_handler fixes don't break existing functions."""

    @patch("app.pyharmonics_handler.YahooOptionData")
    @patch("app.pyharmonics_handler.OptionPlotter")
    def test_whats_options_interest_returns_tuple(self, mock_plotter, mock_yahoo):
        """whats_options_interest should return (plotter, option_data) tuple."""
        from app.pyharmonics_handler import whats_options_interest

        mock_yo = MagicMock()
        mock_yo.ticker.options = ["2024-01-01"]
        mock_yahoo.return_value = mock_yo

        mock_p = MagicMock()
        mock_plotter.return_value = mock_p

        result = whats_options_interest("AAPL")
        # Should return a tuple (plotter, yahoo_option_data)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert result[0] == mock_p
        assert result[1] == mock_yo

    @patch("app.pyharmonics_handler.YahooOptionData")
    @patch("app.pyharmonics_handler.OptionPlotter")
    def test_whats_options_volume_returns_tuple(self, mock_plotter, mock_yahoo):
        """whats_options_volume should return (plotter, option_data) tuple."""
        from app.pyharmonics_handler import whats_options_volume

        mock_yo = MagicMock()
        mock_yo.ticker.options = ["2024-01-01"]
        mock_yahoo.return_value = mock_yo

        mock_p = MagicMock()
        mock_plotter.return_value = mock_p

        result = whats_options_volume("AAPL")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_function_router_has_all_functions(self):
        """FUNCTION_ROUTER should contain expected functions."""
        from app.openai_handler import FUNCTION_ROUTER

        expected = {
            "forming_binance",
            "forming_yahoo",
            "options_interest",
            "options_volume",
        }
        assert set(FUNCTION_ROUTER.keys()) == expected

    def test_all_functions_are_callable(self):
        """All functions in FUNCTION_ROUTER should be callable."""
        from app.openai_handler import FUNCTION_ROUTER

        for name, func in FUNCTION_ROUTER.items():
            assert callable(func), f"{name} is not callable"
