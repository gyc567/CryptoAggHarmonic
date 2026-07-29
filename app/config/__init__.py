"""Configuration package.

Hosts runtime configuration objects. Currently:

* :mod:`app.config.tuning`  — frozen dataclass consolidating every tunable
  constant used by the harmonic-signal pipeline. Code under ``app/domain/`` and
  ``app/services/`` reads these values through the module-level ``TUNING``
  singleton rather than via local module constants, so the full search space
  for the loop-tuning project lives in one place.
"""
