"""Regression tests for legacy endpoints.

NOTE: This test file is skipped because it references obsolete code paths
(FUNCTION_ROUTER, app.main.query_openai, etc.) that no longer exist
in the current codebase. The code has been refactored.

Created: 2026-08-05
"""

import pytest

pytestmark = pytest.mark.skip("references obsolete FUNCTION_ROUTER and app.main paths")
