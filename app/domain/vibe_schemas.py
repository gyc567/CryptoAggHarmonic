"""Pydantic schemas for the AI Trading Assistant (Vibe) module."""

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class VibeSession(BaseModel):
    """A vibe session."""

    id: str
    user_id: str
    title: Optional[str] = None
    status: str = "active"
    context: dict = Field(default_factory=dict)
    summary: Optional[str] = None
    message_count: int = 0
    last_message_at: Optional[str] = None
    created_at: str
    updated_at: str


class VibeMessage(BaseModel):
    """A single message in a vibe session."""

    id: str
    session_id: str
    run_id: Optional[str] = None
    role: str  # system, user, assistant, tool
    content: Optional[str] = None
    tool_calls: Optional[list[dict]] = None
    tool_call_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_input: Optional[dict] = None
    tool_output_ref: Optional[str] = None
    tool_output_summary: Optional[dict] = None
    cards: Optional[list[dict]] = None
    event_id: Optional[str] = None
    created_at: str


class VibeRun(BaseModel):
    """A single agent run."""

    id: str
    session_id: str
    user_id: str
    status: str
    tool_trace: list[dict] = Field(default_factory=list)
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    duration_ms: Optional[int] = None
    user_prompt: Optional[str] = None
    system_prompt_version: Optional[str] = None
    model: Optional[str] = None
    decision_basis: Optional[dict] = None
    error: Optional[str] = None
    cancelled_by: Optional[str] = None
    created_at: str
    completed_at: Optional[str] = None


class CreateSessionRequest(BaseModel):
    """Request to create a new vibe session."""

    title: Optional[str] = Field(default=None, max_length=200)
    context: dict = Field(default_factory=dict)


class CreateSessionResponse(BaseModel):
    """Response after creating a session."""

    session: VibeSession


class SendMessageRequest(BaseModel):
    """Request to send a message in a session."""

    content: str = Field(..., min_length=1, max_length=4000)
    attachments: list[dict] = Field(default_factory=list)


class SendMessageResponse(BaseModel):
    """Response after sending a message (non-streaming)."""

    run_id: str
    status: str


# ---------------------------------------------------------------------------
# Vibe event stream (typed + discriminated)
# ---------------------------------------------------------------------------
#
# Every event written to ``VibeEventStore`` must validate against one of these
# seven typed subclasses. The discriminator is the ``type`` field, so callers
# like the frontend stay schema-agnostic: they look at ``event.type`` and only
# need to know which fields each type carries. ``model_config.extra="forbid"``
# stops typos from silently leaking into the timeline.


class _VibeEventBase(BaseModel):
    """Common fields shared by every vibe event."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    run_id: str
    ts: str
    # Per-run monotonic sequence (0-indexed). Polling clients use this to
    # resume from their last seen position without scanning by event_id.
    seq: Optional[int] = None


class RunStartedEvent(_VibeEventBase):
    """Emitted exactly once when a run starts."""

    type: Literal["run_started"]
    status: str = "running"


class ToolCallStartEvent(_VibeEventBase):
    """A tool invocation began. ``call_id`` correlates with the matching end event."""

    type: Literal["tool_call_start"]
    call_id: str
    tool: str
    input: dict


class ToolCallEndEvent(_VibeEventBase):
    """A tool invocation finished. ``status`` follows the tool contract."""

    type: Literal["tool_call_end"]
    call_id: str
    tool: str
    output: dict


class DeltaEvent(_VibeEventBase):
    """A streamed text fragment from the assistant."""

    type: Literal["delta"]
    content: str


class CardEvent(_VibeEventBase):
    """A structured card (e.g. trade signal, position check) ready to render."""

    type: Literal["card"]
    card_type: str
    payload: dict


class DoneEvent(_VibeEventBase):
    """Terminal success event with token accounting + wall-clock duration.

    Token/latency fields are optional so the schema accepts events written
    by short-circuited / cancelled runs where accounting was never collected.
    """

    type: Literal["done"]
    status: Optional[str] = "completed"
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    duration_ms: Optional[int] = None


class ErrorEvent(_VibeEventBase):
    """Terminal error event. ``retryable`` lets the UI distinguish transient failures."""

    type: Literal["error"]
    code: str
    message: str
    retryable: bool = False


VibeEvent = Annotated[
    RunStartedEvent | ToolCallStartEvent | ToolCallEndEvent | DeltaEvent | CardEvent | DoneEvent | ErrorEvent,
    Field(discriminator="type"),
]


class PollEventsResponse(BaseModel):
    """Response for polling run events."""

    run_id: str
    status: str
    events: list[dict]
    has_more: bool


class ToolRequest(BaseModel):
    """Request to invoke a tool directly."""

    input: dict = Field(default_factory=dict)


class ToolResponse(BaseModel):
    """Response from a direct tool invocation."""

    success: bool = True
    data: Optional[dict] = None
    error: Optional[dict] = None


class VibeErrorDetail(BaseModel):
    """Standard error detail for vibe APIs."""

    code: str
    message: str
    retryable: bool = False
    request_id: Optional[str] = None
