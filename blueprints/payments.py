import uuid
import json
import hashlib
import requests
import base64
from decimal import Decimal
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, current_app, render_template
from extensions import db
from models import Appointment, Payment, VisitType


payments_bp = Blueprint(
    "payments",
    __name__,
    url_prefix="/payments"
)

# ==================================================
# INIT PAYMENT – tworzy Payment (grosze)
# ==================================================
@payments_bp.route("/init", methods=["POST"])
def init_payment():
    data = request.get_json() or {}
    appointment_id = data.get("appointment_id")

    if not appointment_id:
        return jsonify({"error": "appointment_id required"}), 400

    appointment = Appointment.query.get_or_404(appointment_id)

    if appointment.status != "scheduled":
        return jsonify({"error": "Invalid appointment status"}), 400

    visit_type = VisitType.query.filter_by(
        code=appointment.visit_type,
        active=True
    ).first()

    if not visit_type or not visit_type.price or visit_type.price <= 0:
        return jsonify({"error": "Visit type not payable"}), 400

    # blokada duplikatów
    if Payment.query.filter(
        Payment.appointment_id == appointment.id,
        Payment.status.in_(("init", "pending"))
    ).first():
        return jsonify({"error": "Payment already started"}), 409

    if Payment.query.filter_by(
        appointment_id=appointment.id,
        status="paid"
    ).first():
        return jsonify({"error": "Appointment already paid"}), 409

    amount_int = int((visit_type.price * Decimal("100")).quantize(Decimal("1")))
    session_id = uuid.uuid4().hex

    payment = Payment(
        appointment_id=appointment.id,
        provider="przelewy24",
        provider_session_id=session_id,
        amount=amount_int,
        currency="PLN",
        status="init"
    )

    db.session.add(payment)
    db.session.commit()

    return jsonify({
        "payment_id": payment.id,
        "session_id": session_id
    })


# ==================================================
# REGISTER – transaction/register
# ==================================================
@payments_bp.route("/register", methods=["POST"])
def register_payment():
    data = request.get_json() or {}
    payment_id = data.get("payment_id")

    if not payment_id:
        return jsonify({"error": "payment_id required"}), 400

    payment = Payment.query.get_or_404(payment_id)

    if payment.status != "init":
        return jsonify({"error": "Invalid payment status"}), 400

    cfg = current_app.config
    payload = _build_p24_payload(payment)

    auth_raw = f"{cfg['P24_POS_ID']}:{cfg['P24_API_KEY']}"
    auth_b64 = base64.b64encode(auth_raw.encode()).decode()

    try:
        r = requests.post(
            cfg["P24_REGISTER_URL"],
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Basic {auth_b64}",
            },
            timeout=10
        )
    except Exception as e:
        current_app.logger.error(f"[P24] register exception: {e}")
        return jsonify({"error": "Payment provider error"}), 502

    if r.status_code != 200:
        current_app.logger.error(f"[P24] register HTTP {r.status_code} {r.text}")
        return jsonify({"error": "Payment provider error"}), 502

    resp = r.json()
    token = resp.get("data", {}).get("token")

    if not token:
        current_app.logger.error(f"[P24] no token response={resp}")
        return jsonify({"error": "No token from provider"}), 500

    payment.provider_order_id = token
    payment.status = "pending"
    db.session.commit()

    return jsonify({
        "redirect_url": f"{cfg['P24_REDIRECT_URL']}/{token}"
    })


# ==================================================
# STATUS CALLBACK (urlStatus)
# ==================================================
@payments_bp.route("/status", methods=["POST"])
def payment_status():
    data = request.form

    session_id = data.get("sessionId")
    order_id = data.get("orderId")
    amount = data.get("amount")

    if not all([session_id, order_id, amount]):
        return "ERROR", 400

    payment = Payment.query.filter_by(
        provider="przelewy24",
        provider_session_id=session_id
    ).first()

    if not payment:
        return "ERROR", 404

    if str(payment.amount) != str(amount):
        payment.status = "failed"
        db.session.commit()
        return "ERROR", 400

    payment.provider_order_id = order_id

    # ⚠️ VERIFY WYŁĄCZONE CELOWO (WIP)
    # TODO: włączyć _p24_verify_transaction po pełnym potwierdzeniu CRC

    payment.status = "pending"
    db.session.commit()

    return "OK", 200


# ==================================================
# RETURN (browser)
# ==================================================
@payments_bp.route("/return", methods=["GET"])
def payment_return():
    session_id = request.args.get("sessionId")

    if not session_id:
        return render_template("payments/fail.html")

    payment = Payment.query.filter_by(
        provider="przelewy24",
        provider_session_id=session_id
    ).first()

    if payment and payment.status == "paid":
        return render_template(
            "payments/success.html",
            appointment=payment.appointment,
            payment=payment
        )

    return render_template("payments/fail.html")


# ==================================================
# HELPERS
# ==================================================
def _build_p24_payload(payment: Payment):
    cfg = current_app.config
    amount_int = int(payment.amount)

    payload = {
        "merchantId": int(cfg["P24_MERCHANT_ID"]),
        "posId": int(cfg["P24_POS_ID"]),
        "sessionId": payment.provider_session_id,
        "amount": amount_int,
        "currency": "PLN",
        "description": "Rezerwacja wizyty",
        "email": payment.appointment.patient_email or "kontakt@kingabobinska.pl",
        "country": "PL",
        "language": "pl",
        "urlReturn": cfg["P24_RETURN_URL"],
        "urlStatus": cfg["P24_STATUS_URL"],
    }

    payload["sign"] = _p24_sign_v1(payload, cfg["P24_CRC"])
    return payload


def _p24_sign_v1(payload: dict, crc: str) -> str:
    payload_copy = payload.copy()
    payload_copy.pop("sign", None)

    raw = json.dumps(
        payload_copy,
        separators=(",", ":"),
        ensure_ascii=False
    ) + crc

    current_app.logger.warning(f"[P24 DEBUG] SIGN RAW JSON+CRC = {raw}")

    return hashlib.sha384(raw.encode("utf-8")).hexdigest()
