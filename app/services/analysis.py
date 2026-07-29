"""Analysis orchestrator: coordinates validation, detection, interpretation, charting."""
import logging
import time
import uuid
from types import SimpleNamespace
from typing import Optional
from app.domain.enums import Market, Interval, AnalysisType, Status, ErrorCode
from app.domain.schemas import (
    AnalyzeRequest,
    AnalysisData,
    TechnicalResult,
    Interpretation,
    ChartMeta,
    TimingInfo,
)
from app.domain.validators import (
    validate_symbol,
    validate_interval,
    validate_market,
    validate_analysis_type,
    validate_bounds,
)
from app.api.errors import AppError
from app.infra.pyharmonics_adapter import (
    fetch_market_data,
    detect_patterns,
    render_chart,
    technical_result_to_schema,
)
from app.domain.signals import resolve_analysis_type
from app.services.signal_engine import build_signal, extract_candidates
from app.infra.analysis_cache import AnalysisCache, get_analysis_cache
from app.infra.supabase_client import upload_chart, get_chart_url
from app.services.chart import validate_chart_size
from app.services.chart_store import save_chart_locally
from app.openai_handler import query_openai

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
        )


def _extract_sentiment(text: Optional[str]) -> Optional[str]:
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

    def _restore_cached(self, cached: dict, analysis_id: str,
                        user_id: Optional[str], start_time: float) -> AnalysisData:
        """Rebuild an AnalysisData from a cache entry.

        缓存命中后：分配新 analysis_id、用缓存的图表 URL/path 直接复用
        （刷新 timing）。原来这里重新分发 PNG 是为了对抗签名 URL 过期，
        现在缓存里只存 URL/path，重新分发反而需要再拿一次字节，得不偿失：
        签名过期的场景由前端的 ``/api/charts/<id>.png`` 兜底。
        """
        data = AnalysisData.model_validate_json(cached["analysis_json"])
        data.analysis_id = analysis_id
        chart_url = cached.get("chart_url")
        chart_path = cached.get("chart_path")
        if chart_url or chart_path:
            data.chart = ChartMeta(
                format="png",
                path=chart_path,
                url=chart_url,
                width=data.chart.width if data.chart else None,
                height=data.chart.height if data.chart else None,
            )
        elif data.chart and data.chart.url:
            # 旧链接不可信（签名过期），清空
            data.chart = ChartMeta(format="png")
        data.timing = TimingInfo(
            started_at=str(int(start_time)),
            duration_ms=int((time.time() - start_time) * 1000),
            completed_at=str(int(time.time())),
        )
        return data

    @staticmethod
    def _build_trade_signal(candle_data, interval, detection_result: dict,
                            limit_to: int = 10, percent_complete: float = 0.8):
        """Build a trade signal from the detection result (best-effort).

        Signal generation never blocks the analysis pipeline: any failure is
        logged and results in no signal attached.
        """
        try:
            candidates = extract_candidates(detection_result)
            if not candidates:
                return None

            def detect_on_slice(slice_df):
                """Re-run pattern detection on a sub-window (stability check)."""
                try:
                    proxy = SimpleNamespace(
                        df=slice_df,
                        symbol=candle_data.symbol,
                        interval=candle_data.interval,
                    )
                    det = detect_patterns(
                        proxy,
                        limit_to=limit_to,
                        percent_complete=percent_complete,
                        analysis_type="forming",
                    )
                    sub_candidates = extract_candidates(det)
                    return sub_candidates[0].name if sub_candidates else None
                except Exception:
                    return None

            return build_signal(
                df=candle_data.df,
                interval=interval.value,
                candidates=candidates,
                divergences=detection_result.get("divergences", {}),
                stability_detector=detect_on_slice,
            )
        except Exception:
            logger.exception("Signal engine failed, continuing without signal")
            return None

    @staticmethod
    def _distribute_chart(chart, analysis_id: str, image_bytes: bytes,
                          user_id: Optional[str]):
        """Attach a viewable URL to the chart: Supabase first, local fallback.

        Distribution is best-effort: on any storage failure the chart falls
        back to a locally served file so the dashboard always has a picture.
        """
        if user_id:
            try:
                storage_path = upload_chart(user_id, analysis_id, image_bytes)
                if storage_path:
                    chart.path = storage_path
                    chart.url = get_chart_url(storage_path, expires_in=300)
                    logger.info("Chart uploaded to Storage: %s", storage_path)
                    return chart
                logger.warning("Chart upload returned None, falling back to local")
            except Exception as e:
                logger.warning("Chart upload failed, falling back to local: %s", e)

        local_path = save_chart_locally(analysis_id, image_bytes)
        if local_path:
            chart.path = local_path
            chart.url = f"/api/charts/{analysis_id}.png"
        return chart

    def analyze(self, request: AnalyzeRequest, user_id: Optional[str] = None, analysis_id: Optional[str] = None) -> AnalysisData:
        """Run full analysis pipeline.

        Pipeline:
        1. Validate inputs
        2. Fetch market data
        3. Detect patterns
        4. Generate interpretation (optional)
        5. Generate chart and upload to Storage
        6. Build response

        Args:
            request: Validated analyze request.
            user_id: Optional user ID for chart upload.
            analysis_id: Optional analysis ID for chart upload.

        Returns:
            AnalysisData with results.

        Raises:
            AppError: On any pipeline failure.
        """
        start_time = time.time()
        if analysis_id is None:
            analysis_id = str(uuid.uuid4())[:12]

        # Step 1: Validate
        market = validate_market(request.market.value)
        symbol = validate_symbol(request.symbol)
        interval = validate_interval(request.interval.value)
        analysis_type = validate_analysis_type(request.analysis_type.value)
        validate_bounds(request.limit_to, request.percent_complete, request.candles)

        timing = TimingInfo(
            started_at=str(int(start_time)),
        )

        # Step 2: Fetch market data
        try:
            candle_data = fetch_market_data(
                market=market,
                symbol=symbol,
                interval=interval,
                candles=request.candles,
            )
        except AppError:
            raise

        # Step 3: 缓存检查（形态检测对同一组 K 线是确定的，命中则跳过全部重计算）
        cache_key = self.cache.make_key(
            market=market.value,
            symbol=symbol,
            interval=interval.value,
            analysis_type=analysis_type.value,
            limit_to=request.limit_to,
            percent_complete=request.percent_complete,
            candles=request.candles,
            fingerprint=AnalysisCache.candle_fingerprint(candle_data),
        )
        cached = self.cache.get(cache_key)
        if cached:
            return self._restore_cached(cached, analysis_id, user_id, start_time)

        # Step 4: Detect patterns
        detection_result = detect_patterns(
            candle_data=candle_data,
            limit_to=request.limit_to,
            percent_complete=request.percent_complete,
            analysis_type=analysis_type.value,
        )

        # Check if any patterns found
        has_patterns = detection_result.get("position") is not None
        if not has_patterns:
            # No patterns is a valid terminal state
            technical = technical_result_to_schema(detection_result)
            timing.duration_ms = int((time.time() - start_time) * 1000)
            timing.completed_at = str(int(time.time()))

            data = AnalysisData(
                analysis_id=analysis_id,
                status=Status.NO_RESULT,
                market=market,
                symbol=symbol,
                interval=interval,
                analysis_type=analysis_type,
                parameters=request.model_dump(),
                technical_result=technical,
                timing=timing,
            )
            self.cache.set(cache_key, data.model_dump_json())
            return data

        # Step 4: Technical result (+ executable trade signal, best-effort)
        signal = self._build_trade_signal(
            candle_data,
            interval,
            detection_result,
            limit_to=request.limit_to,
            percent_complete=request.percent_complete,
        )
        technical = technical_result_to_schema(
            detection_result,
            signal=signal.to_dict() if signal else None,
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

        # Step 6: Chart (single render, then distribute via Supabase or local)
        chart = ChartMeta()
        try:
            image_bytes, chart_meta = render_chart(detection_result, dpi=150)
            if validate_chart_size(image_bytes):
                chart = chart_meta
                chart = self._distribute_chart(chart, analysis_id, image_bytes, user_id)
            else:
                logger.warning("Chart exceeds size limit, omitting")
                chart = ChartMeta(format="png", path=None, url=None)
        except AppError as e:
            if e.code == ErrorCode.CHART_ERROR:
                logger.warning("Chart generation failed, continuing without chart")
                chart = ChartMeta(format="png", path=None, url=None)
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
            chart=chart,
            timing=timing,
        )
        self.cache.set(
            cache_key,
            data.model_dump_json(),
            chart_url=chart.url,
            chart_path=chart.path,
        )
        return data
