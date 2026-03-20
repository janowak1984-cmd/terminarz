import logging
from datetime import datetime

from models import Appointment
from utils.sms_service import SMSService
from utils.email_service import EmailService
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

    # 🔒 GLOBALNE WŁĄCZNIKI
    sms_enabled = get_setting("sms_reminders_enabled", "0") == "1"
    email_enabled = get_setting("email_reminders_enabled", "0") == "1"

    if not sms_enabled and not email_enabled:
        logger.info("All reminders disabled – skipping")
        return

    now = datetime.utcnow()

    appointments = (
        Appointment.query
        .filter(
            Appointment.status == "scheduled",
            Appointment.start > now,
            Appointment.created_by == "patient"
        )
        .all()
    )


    logger.info(f"Appointments to check: {len(appointments)}")

    sms_service = SMSService()
    email_service = EmailService()

    sent_sms = 0
    sent_email = 0

    for appt in appointments:
        hours_left = (appt.start - now).total_seconds() / 3600

        # 🪟 OKNO WYSYŁKI (48h ± bufor)
        if REMINDER_HOURS <= hours_left < REMINDER_HOURS + (CRON_WINDOW_MINUTES / 60):
            logger.info(
                f"Reminder window hit for appointment {appt.id} "
                f"(starts in {hours_left:.2f}h)"
            )

            # ───── SMS ─────
            if (
                sms_enabled
                and appt.sms_reminder_sent_at is None
            ):
                try:
                    sms_service.send_reminder(appt)
                    sent_sms += 1
                except Exception as e:
                    logger.error(
                        f"[SMS] Failed for appointment {appt.id}: {e}"
                    )

            # ───── EMAIL ─────
            if (
                email_enabled
                and appt.patient_email
                and appt.email_reminder_sent_at is None
            ):
                try:
                    email_service.send_reminder(appt)
                    sent_email += 1
                except Exception as e:
                    logger.error(
                        f"[EMAIL] Failed for appointment {appt.id}: {e}"
                    )

    logger.info(
        f"Job finished. SMS reminders sent: {sent_sms}, "
        f"Email reminders sent: {sent_email}"
    )



# ───────────────────────────────────────
# ENTRYPOINT DLA APSCHEDULERA
# ───────────────────────────────────────

def run():
    """
    Entrypoint dla APSchedulera.
    Flask app_context jest zapewniany WYŻEJ (w app.py).
    """
    _run()
