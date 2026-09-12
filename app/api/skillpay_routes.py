"""Alipay SkillPay webhook routes — 处理支付回调和履约通知.

Flask Blueprint 前缀: /api/skillpay

履约流程（参考 aipayapi.alipay.com 协议）:
  POST /api/skillpay/fulfill    — alipay-bot 购买请求
  GET  /api/skillpay/status/:id — 查询订单状态
  POST /api/skillpay/webhook    — 支付宝支付回调
  POST /api/skillpay/install    — 手动安装触发（用户点击"安装"按钮）

用户视角流程:
  1. 用户在 SkillPay 购买 → POST /api/skillpay/fulfill
  2. alipay-bot 收到 firsttimebuy → 返回支付二维码
  3. 用户扫码支付
  4. 支付宝回调 → POST /api/skillpay/webhook
  5. 用户再次访问 /fulfill → 下载地址 + 安装
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, g

logger = logging.getLogger(__name__)

skillpay_bp = Blueprint("skillpay", __name__, url_prefix="/api/skillpay")


# ---------------------------------------------------------------------------
# POST /api/skillpay/fulfill
# ---------------------------------------------------------------------------

@skillpay_bp.route("/fulfill", methods=["POST"])
def fulfill():
    """Handle skill purchase / fulfillment request.

    Expected JSON body:
      {
        "skill_id": "beautiful-article",    # optional
        "prompt": "firsttimebuy",           # alipay-bot prompt
        "merchant_id": "...",               # optional, overrides env
        "skill_id": "..."                   # optional, overrides env
      }

    Returns JSON:
      - 200 + fulfillment info (download URL or payment required)
      - 400 on validation error
      - 500 on server error
    """
    body = request.get_json(silent=True) or {}

    prompt     = body.get("prompt", "firsttimebuy")
    skill_id   = body.get("skill_id")    # skill name or alipay skill_id

    try:
        from app.infra.alipay_client import SkillPayClient, fulfill_skill

        client = SkillPayClient()
        result = client.fulfill_skill(prompt=prompt)

        response = {
            "success": result.success,
            "error":   result.error,
        }

        if result.order_no:
            response["order_no"] = result.order_no
        if result.payment_url:
            response["payment_url"] = result.payment_url
            response["message"] = "请扫码完成支付"
        if result.install_path:
            response["install_path"] = str(result.install_path)
        if result.skill_name:
            response["skill_name"] = result.skill_name
        if result.already_paid:
            response["message"] = "已购买，请刷新页面安装"

        status_code = 200 if result.success or result.payment_url else 400
        return jsonify(response), status_code

    except Exception as exc:
        logger.exception("fulfill endpoint error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# GET /api/skillpay/status/<order_id>
# ---------------------------------------------------------------------------

@skillpay_bp.route("/status/<order_id>", methods=["GET"])
def payment_status(order_id: str):
    """Query payment status for an order.

    Returns JSON with status (PAID/PENDING/REFUNDED/UNKNOWN).
    """
    try:
        from app.infra.alipay_client import AlipayClient

        client = AlipayClient()
        status = client.query_payment_status(order_id)

        return jsonify({
            "order_no": status.order_no,
            "status":   status.status,
            "paid_at":  status.paid_at,
            "skill_id":  status.skill_id,
            "skill_name": status.skill_name,
        })

    except Exception as exc:
        logger.exception("payment_status error for %s: %s", order_id, exc)
        return jsonify({"success": False, "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# POST /api/skillpay/webhook
# ---------------------------------------------------------------------------

@skillpay_bp.route("/webhook", methods=["POST"])
def webhook():
    """支付宝支付回调 — 付款成功后触发。

    验签逻辑由上游支付宝处理，此处仅记录到账事件。

    Expected POST params (application/x-www-form-urlencoded):
      out_trade_no   — 商户订单号
      trade_no       — 支付宝交易号
      trade_status   — TRADE_SUCCESS / TRADE_FINISHED
      total_amount   — 付款金额
      receipt_amount — 实收金额
      buyer_pay_amount — 买家付款金额
      gmt_payment    — 付款时间

    注意：生产环境必须验签！此为简化版日志记录。
    """
    params = request.form.to_dict() if request.form else request.get_json(silent=True) or {}

    order_no    = params.get("out_trade_no", "")
    trade_no    = params.get("trade_no", "")
    trade_status= params.get("trade_status", "")
    amount      = params.get("total_amount") or params.get("buyer_pay_amount", "0")

    logger.info(
        "SkillPay webhook: order=%s trade_no=%s status=%s amount=%s",
        order_no, trade_no, trade_status, amount,
    )

    # Log to Supabase scan_log as a payment event
    try:
        _log_payment_event(order_no, trade_no, trade_status, amount)
    except Exception as exc:
        logger.warning("Failed to log payment event: %s", exc)

    # Acknowledge to Alipay
    return "success", 200


# ---------------------------------------------------------------------------
# POST /api/skillpay/install
# ---------------------------------------------------------------------------

@skillpay_bp.route("/install", methods=["POST"])
def trigger_install():
    """用户点击「安装」按钮时触发 — 下载 + 安装 Skill。

    Expected JSON body:
      {
        "skill_zip_url": "https://..."   # 直接下载地址
        "skill_name": "beautiful-article" # 用于目录名
      }

    Returns JSON with install result.
    """
    body = request.get_json(silent=True) or {}
    zip_url  = body.get("skill_zip_url")
    skill_name = body.get("skill_name", "")

    if not zip_url:
        return jsonify({"success": False, "error": "skill_zip_url is required"}), 400

    try:
        from app.infra.alipay_client import SkillPayClient
        from pathlib import Path

        client = SkillPayClient()
        result = client._install_from_url(zip_url)

        return jsonify({
            "success":     result.success,
            "skill_name":  result.skill_name,
            "install_path": str(result.install_path) if result.install_path else None,
            "error":       result.error,
        })

    except Exception as exc:
        logger.exception("trigger_install error: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log_payment_event(
    order_no: str,
    trade_no: str,
    trade_status: str,
    amount: str,
) -> None:
    """Log a payment event to Supabase scan_log as payment evidence."""
    try:
        from app.infra.supabase_client import get_supabase_client

        client = get_supabase_client(use_service_role=True)
        if client is None:
            return

        client.table("scan_log").insert({
            "user_id":       order_no,       # reuse scan_log with order_no as user_id
            "symbol":        f"PAYMENT:{trade_status}",
            "scan_time":     datetime.now(timezone.utc).isoformat(),
            "timeframe":     "PAYMENT",
            "signals_found": 0,
            "top_score":     0,
            "top_pattern":   f"amount:{amount}",
            "top_direction": trade_no,
            "is_sent":       trade_status in ("TRADE_SUCCESS", "TRADE_FINISHED"),
            "sent_at":       datetime.now(timezone.utc).isoformat() if trade_status in ("TRADE_SUCCESS", "TRADE_FINISHED") else None,
        }).execute()
    except Exception as exc:
        logger.debug("Failed to log payment event to Supabase: %s", exc)
