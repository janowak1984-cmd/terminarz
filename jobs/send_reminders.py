import logging
from datetime import datetime

from models import Appointment
from utils.sms_service import SMSService
from utils.settings import get_setting


# ───────────────────────────────────────
# KONFIGURACJA
# ───────────────────────────────────────

REMINDER_HOURS = 48
CRON_WINDOW_MINUTES = 20  # bufor na opóźnienia schedulera (job co 15 min)


# ───────────────────────────────────────
# LOGGING
# ───────────────────────────────────────

logger = logging.getLogger("send_reminders")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "[%(asctime)s] [REMINDER] %(levelname)s: %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)


# ───────────────────────────────────────
# CORE LOGIC (BEZ FLASK!)
# ───────────────────────────────────────

def _run():
    logger.info("Job started")

    # 🔒 GLOBALNY WŁĄCZNIK PRZYPOMNIEŃ
    if get_setting("sms_reminders_enabled", "0") != "1":
        logger.info("Reminders disabled in settings – skipping")
        return

    now = datetime.utcnow()

    appointments = (
        Appointment.query
        .filter(
            Appointment.status == "scheduled",
            Appointment.sms_reminder_sent_at.is_(None),
            Appointment.start > now
        )
        .all()
    )

    logger.info(f"Appointments to check: {len(appointments)}")

    sms_service = SMSService()
    sent_count = 0

    for appt in appointments:
        hours_left = (appt.start - now).total_seconds() / 3600

        # 🪟 OKNO WYSYŁKI (48h ± bufor)
        if REMINDER_HOURS <= hours_left < REMINDER_HOURS + (CRON_WINDOW_MINUTES / 60):
            logger.info(
                f"Sending reminder for appointment {appt.id} "
                f"(starts in {hours_left:.2f}h)"
            )

            try:
                sms_service.send_reminder(appt)
                sent_count += 1
            except Exception as e:
                logger.error(
                    f"Failed to send reminder for appointment {appt.id}: {e}"
                )

    logger.info(f"Job finished. Reminders sent: {sent_count}")


# ───────────────────────────────────────
# ENTRYPOINT DLA APSCHEDULERA
# ───────────────────────────────────────

def run():
    """
    Entrypoint dla APSchedulera.
    Flask app_context jest zapewniany WYŻEJ (w app.py).
    """
    _run()
