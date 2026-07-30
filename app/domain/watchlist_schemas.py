"""Pydantic request/response schemas for the watchlist API.

Kept tiny on purpose: each model exists to validate one request body and
give the route a typed handle. Anything richer belongs on the frontend.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints


# Reusable constrained types ---------------------------------------------------

SymbolStr = Annotated[
    str,
    StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Z0-9]+$"),
]
"""Binance-style symbol: uppercase letters and digits only (e.g. ``MUUSDT``)."""

NoteStr = Annotated[
    str,
    StringConstraints(min_length=0, max_length=280),
]
"""Watchlist note; empty string allowed."""


# Add -----------------------------------------------------------------------


class WatchlistAddRequest(BaseModel):
    """Body for ``POST /api/watchlist``."""

    symbol: SymbolStr
    note: NoteStr = ""


# Update ---------------------------------------------------------------------


class WatchlistUpdateRequest(BaseModel):
    """Body for ``PATCH /api/watchlist/<id>``.

    Either ``note`` or ``sort_index`` (or both) must be supplied. The route
    enforces that.
    """

    note: NoteStr | None = None
    sort_index: int | None = Field(default=None, ge=0, le=1_000_000)


# Reorder --------------------------------------------------------------------


class WatchlistReorderItem(BaseModel):
    id: str
    sort_index: int = Field(ge=0, le=1_000_000)


class WatchlistReorderRequest(BaseModel):
    """Body for ``POST /api/watchlist/reorder``.

    The array order is the desired sort order; ``sort_index`` is recomputed
    server-side from the array position so the client only needs to
    preserve order, not assign numbers.
    """

    items: list[WatchlistReorderItem] = Field(min_length=1, max_length=200)


# Admin refresh --------------------------------------------------------------


class WatchlistRefreshRequest(BaseModel):
    """Body for ``POST /api/admin/markets/futures/refresh``.

    Empty body is fine; the field exists so future flags (force=true, etc.)
    have a place to land.
    """

    force: bool = False