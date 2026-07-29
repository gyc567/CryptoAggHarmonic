"""Request-payload validation helper for Flask routes.

Most routes accept a JSON body and need to validate it against a Pydantic
``BaseModel`` (see ``app.domain.schemas``, ``app.domain.vibe_schemas``,
``app.domain.rsi_trend_schemas``). Doing this by hand at every route invites
the same five-line ``try / except / _error`` block repeated — and worse, the
``except Exception`` swallow hides the distinction between a malformed
payload, a missing required field, and a wrong-type field.

This module provides a single helper:

    req, err = parse_request(SomeModel, request.get_json(silent=True) or {})

If validation succeeds, ``req`` is a fully-populated model instance and
``err`` is ``None``. If validation fails, ``err`` is a Flask ``(jsonify(...),
status)`` tuple ready to be returned. The error payload uses the project's
standard ``ErrorResponse`` envelope and lists every offending field with
``loc`` (the path), ``msg`` (human readable), and ``type`` (Pydantic error
class name) — the same shape the FastAPI ecosystem already speaks, so the
frontend's existing parser can show field-level errors without new code.

Status code is **422** (Unprocessable Entity) — the request is
syntactically valid JSON, semantically rejected by the schema. 400 is
reserved for "couldn't even parse JSON" so the two cases stay distinct.
"""

from __future__ import annotations

import json
from typing import Any

from flask import jsonify
from pydantic import BaseModel, ValidationError

from app.domain.enums import ErrorCode
from app.domain.schemas import ErrorDetail, ErrorResponse, FieldError


class _InvalidJSONError(Exception):
    """Raised when the request body can't be decoded as JSON."""


def _coerce_json(raw: Any) -> dict:
    """Normalise whatever the caller passed into a dict for ``model_validate``.

    Accepts:
        * a dict (already parsed) — returned as-is
        * a JSON string — decoded; raises :class:`_InvalidJSONError` on failure
        * ``None`` or any other falsy value — returns ``{}``

    We do this once per request so each route doesn't have to repeat the
    ``request.get_json(force=True, silent=True) or {}`` dance.
    """
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str | bytes | bytearray):
        try:
            decoded = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise _InvalidJSONError(str(exc)) from exc
        if not isinstance(decoded, dict):
            # JSON arrays / scalars at the root aren't valid request bodies.
            raise _InvalidJSONError(
                "Request body must be a JSON object, got " f"{type(decoded).__name__}",
            )
        return decoded
    raise _InvalidJSONError(
        f"Unsupported body type: {type(raw).__name__}",
    )


def parse_request(
    model_cls: type[BaseModel],
    payload: Any,
) -> tuple[BaseModel | None, tuple[Any, int] | None]:
    """Validate ``payload`` against ``model_cls``.

    Returns ``(model_instance, None)`` on success and ``(None, error_response)``
    on failure. The error_response is a Flask ``(jsonify(...), status)``
    tuple — return it directly from your route handler.

    On success the model is the same instance the caller would get from
    ``Model.model_validate(payload)``; we just standardise the error path
    so routes don't write it by hand.

    Example::

        req, err = parse_request(AnalyzeRequest, request.get_json(silent=True))
        if err is not None:
            return err
        # ... req is now a validated AnalyzeRequest ...
    """
    try:
        data = _coerce_json(payload)
    except _InvalidJSONError as exc:
        return None, _invalid_json_response(str(exc))

    try:
        instance = model_cls.model_validate(data)
    except ValidationError as exc:
        return None, _validation_error_response(model_cls, exc)

    return instance, None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _invalid_json_response(detail: str) -> tuple[Any, int]:
    """400 — body isn't JSON at all (or isn't a JSON object)."""
    return (
        jsonify(
            ErrorResponse(
                success=False,
                error=ErrorDetail(
                    code=ErrorCode.INVALID_PARAMS,
                    message=f"Request body must be valid JSON: {detail}",
                    retryable=False,
                    request_id="",
                ),
            ).model_dump()
        ),
        400,
    )


def _validation_error_response(
    model_cls: type[BaseModel],
    exc: ValidationError,
) -> tuple[Any, int]:
    """422 — body is JSON but the schema rejects it.

    Populates the top-level ``details`` list with one ``FieldError`` per
    Pydantic error. The ``message`` is a short summary; consumers that need
    structured field paths should read ``details``.
    """
    field_errors = [
        FieldError(
            loc=".".join(str(part) for part in err["loc"]),
            msg=err["msg"],
            type=err["type"],
        )
        for err in exc.errors()
    ]
    summary = "; ".join(f"{e.loc}: {e.msg}" for e in field_errors[:3])
    if len(field_errors) > 3:
        summary += f" (and {len(field_errors) - 3} more)"

    return (
        jsonify(
            ErrorResponse(
                success=False,
                error=ErrorDetail(
                    code=ErrorCode.INVALID_PARAMS,
                    message=f"Invalid {model_cls.__name__}: {summary}",
                    retryable=False,
                    request_id="",
                ),
                details=field_errors,
            ).model_dump(exclude_none=False)
        ),
        422,
    )
