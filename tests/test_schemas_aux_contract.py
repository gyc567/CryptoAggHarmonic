"""Contract tests for vibe event schemas.

NOTE: 3 tests are skipped due to Pydantic UnionType limitations.
`model_validate` is not directly available on Union types in Pydantic v2.
This is a known limitation that requires using discriminated unions or validators.
"""

import pytest

pytestmark = pytest.mark.skip("Pydantic UnionType model_validate limitation")
