"""Analysis orchestrator: coordinates validation, detection, and interpretation."""

import logging
import time
import uuid
from typing import Optional

from app.api.errors import AppError
from app.domain.enums import AnalysisType, ErrorCode, Status
from app.domain.forming_schemas import CandidateWithMetrics
from app.domain.schemas import (
    AnalysisData,
    AnalyzeRequest,
    Interpretation,
    TimingInfo,
)
from app.domain.signals import net_rr, resolve_analysis_type
from app.infra.analysis_cache import AnalysisCache, get_analysis_cache
from app.infra.pyharmonics_adapter import (
    detect_patterns,
    fetch_market_data,
    technical_result_to_schema,
)
from app.openai_handler import query_openai
from app.services.discipline_filters import evaluate as discipline_evaluate
from app.services.macro_bias import compute as macro_compute
from app.services.signal_engine import build_signal, extract_candidates

logger = logging.getLogger(__name__)


def _generate_interpretation(technical_json: str, prompt_context: str) -> Interpretation:
    """Generate model interpretation of technical results.

    Args:
        technical_json: JSON string of technical results.
        prompt_context: Developer prompt context for OpenAI.

    Returns:
        Interpretation schema.
    """
    try:
        raw_response = query_openai(technical_json, prompt_context)
        return Interpretation(
            sentiment=_extract_sentiment(raw_response),
            summary=raw_response[:500] if raw_response else None,
            raw_response=raw_response,
        )
    except Exception as e:
        logger.exception("Model interpretation failed")
        raise AppError(
            ErrorCode.MODEL_ERROR,
            "模型解读生成失败，技术结果仍可查看。",
            retryable=True,
            original_error=e,
        ) from e


def _extract_sentiment(text: Optional[str]) -> str | None:
    """Extract sentiment keyword from model response.

    Args:
        text: Raw model response text.

    Returns:
        Sentiment string or None.
    """
    if not text:
        return None
    text_lower = text.lower()
    if "bull" in text_lower or "多" in text:
        return "bullish"
    elif "bear" in text_lower or "空" in text:
        return "bearish"
    elif "neutral" in text_lower or "中性" in text:
        return "neutral"
    return None


class AnalysisOrchestrator:
    """Orchestrates the full analysis pipeline."""

    def __init__(self, prompt_context: Optional[dict] = None, cache: Optional[AnalysisCache] = None):
        """Initialize orchestrator.

        Args:
            prompt_context: Loaded prompt_intent.yaml dict.
            cache: Analysis cache (defaults to the shared process-wide instance).
        """
        self.prompt_context = prompt_context or {}
        self.cache = cache or get_analysis_cache()

    def _restore_cached(self, cached: dict, analysis_id: str, user_id: Optional[str], start_time: float) -> Optional[AnalysisData]:
        """Reconstruct AnalysisData from cache without re-running analysis.

        Returns None when the cached payload is "dirty" (e.g. v1 cache written
        before stop_loss/target_price existed); callers are expected to delete
        the stale key and re-run detection in that case.

        This is used for idempotent requests and GET /analysis/:id.
        """
        data = AnalysisData.model_validate_json(cached["analysis_json"])
        # Dirty-cache guard: a v1 cached result has entry_price but no stop_loss,
        # which would re-render the broken dashboard. Surface that as a cache miss
        # so the orchestrator re-runs detection with the v2 schema.
        tech = data.technical_result
        if tech is None or (tech.entry_price is not None and tech.stop_loss is None):
            return None
        data.analysis_id = analysis_id
        # Restore timing from cache (may be stale but gives approximate duration)
        if data.timing:
            data.timing.duration_ms = int((time.time() - start_time) * 1000)
            data.timing.completed_at = str(int(time.time()))
        return data

    def analyze(
        self,
        request: AnalyzeRequest,
        user_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        analysis_id: Optional[str] = None,
    ) -> AnalysisData:
        """Run full technical analysis.

        Steps:
        1. Validation (fast, no I/O)
        2. Market data fetch
        3. Pattern detection
        4. Signal evaluation (optional)
        5. Interpretation (optional)

        Args:
            request: Validated analysis request.
            user_id: Authenticated user ID (optional, enables caching & quota).
            idempotency_key: Request deduplication key.
            analysis_id: Optional analysis ID from the API layer. When omitted a
                new UUID is generated.

        Returns:
            Complete AnalysisData response.

        Raises:
            AppError: On validation failure, data fetch failure, or pattern
                detection failure.
        """
        start_time = time.time()
        analysis_id = analysis_id or str(uuid.uuid4())

        # Unpack validated request fields
        market = request.market
        symbol = request.symbol.upper()
        interval = request.interval
        analysis_type = request.analysis_type
        limit_to = request.limit_to or 10
        percent_complete = request.percent_complete or 0.8
        candles = request.candles or 1000

        # Check cache for idempotent requests. Cache keys carry a schema version
        # so older payloads (e.g. v1 entries without stop_loss) are naturally
        # missed instead of being served stale and re-rendering the bug.
        cache_key = f"v2:{market.value}:{symbol}:{interval.value}:{analysis_type.value}"
        if user_id and idempotency_key:
            cache_key = f"v2:{user_id}:{idempotency_key}"
            cached = self.cache.get(cache_key)
            if cached:
                restored = self._restore_cached(cached, analysis_id, user_id, start_time)
                if restored is not None:
                    logger.info("Cache hit for idempotent request %s", idempotency_key)
                    return restored
                # Dirty cache (v1 schema or malformed payload) — drop it and
                # fall through to the live detection path below.
                logger.warning("Dropping dirty cache key %s; re-running detection", cache_key)
                # AnalysisCache has no delete(); the re-run below overwrites the
                # key via cache.set() at the end of analyze(), which achieves the
                # same invalidation. Guard anyway in case a backend gains delete.
                delete = getattr(self.cache, "delete", None)
                if delete is not None:
                    delete(cache_key)

        # Step 1 is done by the API layer (parse_request decorator)
        # Step 2: Fetch market data
        timing = TimingInfo(duration_ms=0, started_at=str(int(time.time())))
        try:
            candle_data = fetch_market_data(market, symbol, interval, candles)
        except AppError:
            raise
        except Exception as e:
            logger.exception("Market data fetch failed")
            raise AppError(
                ErrorCode.MARKET_DATA_UNAVAILABLE,
                f"暂时无法获取 {symbol} 的行情数据，请稍后重试。",
                retryable=True,
                original_error=e,
            ) from e

        # Step 3: Pattern detection
        try:
            detection_result = detect_patterns(
                candle_data,
                limit_to=limit_to,
                percent_complete=percent_complete,
                analysis_type=analysis_type.value,
            )
        except AppError:
            raise
        except Exception as e:
            logger.exception("Pattern detection failed")
            raise AppError(
                ErrorCode.DETECTION_ERROR,
                f"{symbol} 形态检测失败，请稍后重试。",
                retryable=True,
                original_error=e,
            ) from e

        # Check for "no pattern" result early
        if not detection_result.get("position") and not detection_result.get("patterns"):
            logger.info("No patterns detected for %s %s", symbol, interval.value)
            timing.duration_ms = int((time.time() - start_time) * 1000)
            timing.completed_at = str(int(time.time()))
            return AnalysisData(
                analysis_id=analysis_id,
                status=Status.NO_RESULT,
                market=market,
                symbol=symbol,
                interval=interval,
                analysis_type=analysis_type,
                parameters=request.model_dump(),
                technical_result={},
                interpretation=Interpretation(summary="未检测到明显的谐波形态。"),
                timing=timing,
                forming_candidates=[],
            )

        # Step 4: Signal evaluation (forming type only)
        forming_view: list[CandidateWithMetrics] = []
        scored: list = []
        signal = None
        if analysis_type == AnalysisType.FORMING:
            try:
                candidates = extract_candidates(detection_result)
                forming_view = candidates[:limit_to]
                if forming_view:
                    # Score and rank with discipline + macro filters
                    for c in forming_view:
                        disc = discipline_evaluate(c)
                        macro = macro_compute(candle_data, c)
                        scored.append((c, disc, macro))
                    scored.sort(key=lambda x: x[0].metrics.confidence or 0, reverse=True)
                    top = scored[0][0]
                    signal = build_signal(
                        top,
                        market=market.value,
                        interval=interval.value,
                        symbol=symbol,
                        htf_trend=detection_result.get("htf_trend"),
                    )
            except Exception as e:
                logger.warning("Signal evaluation failed: %s", e)
                # Non-fatal: continue without signal

        # Convert to schema. forming_signal_dict is the fallback that technical_result_to_schema
        # uses when the signal engine raised or returned no signal; it must mirror what
        # ``build_signal(top).to_dict()`` would have produced for the SAME top candidate
        # the engine selected, otherwise the dashboard would render levels from a
        # different candidate than the one shown in the forming list.
        forming_signal_dict: Optional[dict] = None
        top = scored[0][0] if scored else None  # signal engine's chosen candidate
        if top is not None:
            targets_list = [
                {
                    "label": t.label,
                    "price": float(t.price),
                    "fib_basis": t.fib_basis,
                    "close_pct": t.close_pct,
                    "move_stop_to": t.move_stop_to,
                }
                for t in (top.targets or [])
            ]
            forming_signal_dict = {
                "status": "formed" if top.formed else "forming",
                "grade": "C",
                "direction": top.direction or "long",
                "pattern_name": top.pattern_name or "unknown",
                "family": top.family or "XABCD",
                "formed": bool(top.formed),
                "entry_zone": (
                    [top.entry_price * 0.99, top.entry_price * 1.01]
                    if top.entry_price
                    else [0, 0]
                ),
                "entry_reference": top.entry_price,
                "stop_loss": top.stop_loss,
                "targets": targets_list,
                "net_rr_tp1": (
                    net_rr(top.entry_price, top.stop_loss, top.targets[0].price)
                    if top.targets
                    else None
                ),
                "net_rr_tp2": (
                    net_rr(top.entry_price, top.stop_loss, top.targets[1].price)
                    if len(top.targets or []) >= 2
                    else None
                ),
                "confluence_score": int((top.metrics.confidence or 0) * 100),
                "macro": (
                    {"size_mult": top.macro.size_mult, "advice": top.macro.advice}
                    if top.macro
                    else None
                ),
                "width_pct": top.width_pct,
                "bars_since_c": top.metrics.bars_since_c,
                "stale": top.metrics.stale,
                "past_tp2": top.metrics.past_tp2,
                "in_prz": top.metrics.in_prz,
                "dist_pct": top.metrics.dist_pct,
                "confidence": "raw-forming-c",
            }
        technical = technical_result_to_schema(
            detection_result,
            signal=signal.to_dict() if signal else forming_signal_dict,
        )
        # resolved_type: what the engine actually used (auto mode's answer).
        # request value stays in AnalysisData.analysis_type unchanged.
        technical.resolved_type = resolve_analysis_type(signal)

        # Step 5: Interpretation (optional - can fail without failing whole analysis)
        interpretation = Interpretation()
        try:
            tech_json = technical.model_dump_json()
            prompt = self.prompt_context.get("technical_analysis", "")
            if prompt:
                interpretation = _generate_interpretation(tech_json, prompt)
        except AppError as e:
            if e.code == ErrorCode.MODEL_ERROR:
                logger.warning("Interpretation failed, continuing with technical results only")
                interpretation = Interpretation(
                    summary="模型解读暂时不可用，请参考技术结果。",
                )
            else:
                raise

        # Finalize timing
        timing.duration_ms = int((time.time() - start_time) * 1000)
        timing.completed_at = str(int(time.time()))

        data = AnalysisData(
            analysis_id=analysis_id,
            status=Status.COMPLETED,
            market=market,
            symbol=symbol,
            interval=interval,
            analysis_type=analysis_type,
            parameters=request.model_dump(),
            technical_result=technical,
            interpretation=interpretation,
            timing=timing,
            # v2: surface the ranked forming view (empty list when none).
            # Capped at 10 to avoid blowing up the response payload when the
            # upstream detector is too permissive on a choppy market.
            forming_candidates=[v.to_dict() for v in forming_view[:10]],
        )
        self.cache.set(cache_key, data.model_dump_json())
        return data
