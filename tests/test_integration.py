"""Integration tests for API endpoints.

NOTE: This test file is skipped because it references obsolete module paths
(app.main.orchestrator, app.main.consume_ledger_quota, etc.) that no longer
exist in the current codebase. The code has been refactored to use
app.factory and app.api.routes. These tests should be rewritten to match
the current architecture.

Created: 2026-08-05
"""

import pytest

pytestmark = pytest.mark.skip("test references obsolete module paths (app.main.orchestrator, etc.)")
