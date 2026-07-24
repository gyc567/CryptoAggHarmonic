from .openai_handler import parse_args, query_openai, FUNCTION_ROUTER  # Import parse_args from the appropriate module
from flask import Flask, jsonify, request, render_template
import os
import yaml
import logging
import uuid

# New SaaS API imports
from app.api.middleware import register_error_handlers, log_request_middleware
from app.api.auth import require_auth, check_quota, is_local_dev_mode
from app.api.vibe_routes import vibe_bp
from app.api.rsi_trend_routes import rsi_trend_bp
from app.domain.enums import Market, Interval, AnalysisType, ErrorCode
from app.domain.schemas import (
    AnalyzeRequest,
    SuccessResponse,
    ErrorResponse,
    HealthResponse,
    MarketsResponse,
)
from app.services.analysis import AnalysisOrchestrator
from app.infra.supabase_client import (
    create_analysis_record,
    update_analysis_record,
    consume_ledger_quota,
    release_ledger_quota,
    log_audit_event,
)
from app.api.errors import AppError

# Set up logging
logging.basicConfig(level=logging.INFO)

# Initialize Flask app
app = Flask(__name__)

# Register middleware
register_error_handlers(app)
log_request_middleware(app)

# Register vibe blueprint
app.register_blueprint(vibe_bp)

# Register trend-RSI strategy blueprint
app.register_blueprint(rsi_trend_bp)


# Simple CORS support for local dev / preview origins
@app.before_request
def before_request_cors():
    """Handle CORS preflight and stash origin for after_request headers."""
    origin = request.headers.get("Origin", "")
    allowed_origins = {
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5001",
        "http://127.0.0.1:5001",
    }
    if origin in allowed_origins:
        request._cors_origin = origin  # type: ignore[attr-defined]
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200


@app.after_request
def after_request_cors(response):
    """Add CORS headers to allow browser requests from localhost preview origins."""
    origin = getattr(request, "_cors_origin", None)
    if origin:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response

with open("prompt_intent.yaml", "r") as _prompt_intent_file:
    prompt_context = yaml.safe_load(_prompt_intent_file)
logging.debug("Loaded model context: %s", prompt_context)

# Initialize orchestrator
orchestrator = AnalysisOrchestrator(prompt_context=prompt_context)


# ---- New SaaS API Routes ----

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    import time
    return jsonify(
        HealthResponse(timestamp=str(int(time.time()))).model_dump()
    ), 200


@app.route('/api/markets', methods=['GET'])
def get_markets():
    """Return supported markets, intervals, and analysis types."""
    return jsonify(
        MarketsResponse(
            markets=[m.value for m in Market],
            intervals=[i.value for i in Interval],
            analysis_types=[a.value for a in AnalysisType],
        ).model_dump()
    ), 200


@app.route('/api/charts/<name>.png', methods=['GET'])
def serve_chart(name):
    """Serve a locally stored chart PNG (fallback when Storage is unavailable).

    Unauthenticated on purpose: charts are public market graphics addressed by
    an unguessable analysis id; the name whitelist blocks path traversal.
    """
    from flask import send_file
    from app.services.chart_store import chart_file_path

    path = chart_file_path(name)
    if path is None:
        return jsonify({"success": False, "error": {
            "code": "NOT_FOUND", "message": "Chart not found.",
            "retryable": False, "request_id": "",
        }}), 404
    return send_file(path, mimetype="image/png")



@app.route('/api/analyze', methods=['POST'])
@require_auth
def analyze(user):
    """Structured analysis endpoint with auth and quota.

    Expects JSON body matching AnalyzeRequest schema.
    Requires Authorization: Bearer <token> header.
    Returns structured analysis results.
    """
    user_id = user.get("id")

    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None

    if not data:
        return jsonify(
            ErrorResponse(
                error={
                    "code": "INVALID_PARAMS",
                    "message": "Request body must be valid JSON.",
                    "retryable": False,
                    "request_id": "",
                }
            ).model_dump()
        ), 400

    # Validate request
    try:
        req = AnalyzeRequest(**data)
    except Exception as e:
        logging.warning("Validation error: %s", e)
        return jsonify(
            ErrorResponse(
                error={
                    "code": "INVALID_PARAMS",
                    "message": f"Invalid request parameters: {str(e)}",
                    "retryable": False,
                    "request_id": "",
                }
            ).model_dump()
        ), 400

    # Reserve quota
    analysis_id = str(uuid.uuid4())
    if is_local_dev_mode():
        # Local dev mode: skip Supabase quota reservation
        reserved, remaining, ledger_id = True, 100, None
    else:
        reserved, remaining, ledger_id = check_quota(user_id, analysis_id, units=1)
    if not reserved:
        return jsonify(
            ErrorResponse(
                error={
                    "code": "QUOTA_EXCEEDED",
                    "message": f"Daily quota exceeded. Remaining: {remaining}",
                    "retryable": False,
                    "request_id": "",
                }
            ).model_dump()
        ), 429

    # Create analysis record
    create_analysis_record(user_id, {
        "input_mode": "form",
        "market": req.market.value,
        "symbol": req.symbol,
        "interval": req.interval.value,
        "analysis_type": req.analysis_type.value,
        "parameters": req.model_dump(),
        "status": "created",
    })

    # Run analysis
    try:
        result = orchestrator.analyze(req, user_id=user_id, analysis_id=analysis_id)

        # Consume quota
        if ledger_id:
            consume_ledger_quota(
                ledger_id,
                input_tokens=result.timing.get("input_tokens") if hasattr(result, "timing") else None,
                output_tokens=result.timing.get("output_tokens") if hasattr(result, "timing") else None,
            )

        # Log audit
        log_audit_event(
            actor_id=user_id,
            action="analysis_completed",
            target_type="analysis",
            target_id=analysis_id,
            details={"symbol": req.symbol, "market": req.market.value},
        )

        return jsonify(
            SuccessResponse(data=result.model_dump()).model_dump()
        ), 200

    except AppError as e:
        # Release quota on failure
        if ledger_id:
            release_ledger_quota(ledger_id)
        raise
    except Exception as e:
        # Release quota on unexpected failure
        if ledger_id:
            release_ledger_quota(ledger_id)
        logging.exception("Analysis failed")
        raise AppError(
            ErrorCode.INTERNAL_ERROR,
            "Analysis failed. Please try again.",
            retryable=True,
            original_error=e,
        )


@app.route('/api/history', methods=['GET'])
@require_auth
def history(user):
    """Return analysis history.

    Currently returns an empty placeholder list. Persisted history should be
    fetched from the database once the schema and RLS policies are ready.
    """
    return jsonify({"success": True, "data": {"items": [], "total": 0}}), 200


@app.route('/api/analysis/<analysis_id>', methods=['GET'])
@require_auth
def analysis_detail(user, analysis_id):
    """Return a single analysis record by ID.

    Currently returns a 404 placeholder. Real implementation should query the
    analyses table and verify ownership via RLS.
    """
    return jsonify({
        "success": False,
        "error": {
            "code": ErrorCode.NOT_FOUND.value,
            "message": "Analysis not found.",
            "retryable": False,
            "request_id": "",
        },
    }), 404


# ---- Existing Routes (Unchanged) ----

# Route to interact with OpenAI's GPT-3
@app.route('/query', methods=['POST'])
def query_openai_route():
    """
        Queries OpenAI's GPT* model to determine the how Pyharmonics API should be called.
        Calls the appropriate Pyharmonics API function and sends that response to OpenAI for further processing.
        Finally, returns the response from OpenAI to the client.
    """
    try:
        # Get JSON data from the request
        data = request.get_json(force=True, silent=True)
        if data is None:
            return jsonify({"error": "Invalid JSON"}), 400
        user_prompt = data.get('prompt')

        # User prompt isd required
        if not user_prompt:
            return jsonify({"error": "Prompt is required"}), 400

        # Determine the api call to make based on the user prompt
        function_name, args, kwargs = parse_args(
            query_openai(
                user_prompt,
                prompt_context['extract_args']
            )
        )

        # In this example we only want the user to interact with our Pyharmonics API.
        # If the user asks for something out of scope we explain to them what to ask first.
        # You may want to handle this differently in your application.
        if function_name not in FUNCTION_ROUTER:
            return jsonify({"response": prompt_context['extract_args_error']}), 200

        # Call the appropriate Pyharmonics API function and deal with any exceptions.
        symbol, interval = args
        try:
            harmonic_data = FUNCTION_ROUTER[function_name](symbol, interval, **kwargs)
            logging.info(f"Harmonic data: {harmonic_data.keys()}")
        except Exception as e:
            return jsonify({"response": f"Pyharmonics raised the following exception: {str(e)}"}), 200

        # Extract the plot and remove it from the harmonic data
        plot = harmonic_data.pop('plot', None)
        logging.info(f"harmonic data: {harmonic_data}")
        logging.info(f"base 64 image: {type(plot)}")

        # Prepare the response data. We only want to send the position or divergences to OpenAI.
        pyharmonics_response = str({
            "asset": symbol,
            "timeframe": interval,
            "found": harmonic_data.get('position', harmonic_data.get('divergences', {})),
        })
        logging.debug(f"Pyharmonics response is built as {type(pyharmonics_response)}\n{pyharmonics_response}")

        # Now we query OpenAI with the Pyharmonics response and the technical analysis context.
        model_response = query_openai(
            pyharmonics_response,
            prompt_context['technical_analysis']
        )
        logging.debug(f"OpenAI model response: {model_response}")

        # Return the OpenAI response with the Pyharmonics response and the plot
        response_data = {
            "response": {
                "model": model_response,
                "image": {
                    "data": plot,
                    "format": "image/png"
                }
            }
        }
        return jsonify(response_data), 200

    except Exception as e:
        logging.error(f"An error occurred: {str(e)}")
        return jsonify({"error": f"{str(e)}"}), 500

@app.route('/')
def index():
    """
        Renders the chat UI.
    """
    return render_template('chat_ui.html')

if __name__ == "__main__":
    # Run the app on the host and port specified in environment variables
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
