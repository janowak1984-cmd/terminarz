import logging
from datetime import datetime, timedelta

from models import Appointment, Payment
from extensions import db
from utils.google_calendar import GoogleCalendarService


# ───────────────────────────────────────
# KONFIGURACJA
# ───────────────────────────────────────

EXPIRE_MINUTES = 30


# ───────────────────────────────────────
# LOGGING
# ───────────────────────────────────────

logger = logging.getLogger("expire_unpaid")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "[%(asctime)s] [EXPIRE] %(levelname)s: %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)


# ───────────────────────────────────────
# CORE LOGIC (BEZ FLASK)
# ───────────────────────────────────────

def _run():
    logger.info("Expire unpaid job started")

    now = datetime.utcnow()
    threshold = now - timedelta(minutes=EXPIRE_MINUTES)

    payments = (
        Payment.query
        .filter(
            Payment.provider == "przelewy24",   # 🔒 TYLKO P24
            Payment.status.in_(["init", "pending"]),
            Payment.created_at < threshold
        )
        .all()
    )

    logger.info(f"Payments to check: {len(payments)}")

    expired_count = 0

    for payment in payments:

        appointment = payment.appointment

        # bezpieczeństwo
        if not appointment:
            continue

        if appointment.status != "scheduled":
            continue

        logger.info(
            f"Expiring appointment {appointment.id} "
            f"(payment {payment.id})"
        )

        # 🔴 Anulowanie wizyty
        appointment.status = "cancelled"
        appointment.cancelled_by = "system"
        appointment.cancelled_at = datetime.utcnow()

        payment.status = "failed"

        expired_count += 1

        # 🗑 Usuń z Google Calendar
        try:
            GoogleCalendarService.delete_appointment(appointment)
        except Exception as e:
            logger.error(
                f"Google delete failed for appt {appointment.id}: {e}"
            )

    db.session.commit()

    logger.info(f"Job finished. Expired: {expired_count}")


# ───────────────────────────────────────
# ENTRYPOINT
# ───────────────────────────────────────

def run():
    _run()