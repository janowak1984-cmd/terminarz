import requests
from datetime import datetime
from flask import current_app

from extensions import db
from models import Appointment
from utils.settings import get_setting


class EmailService:
    def __init__(self):
        # 🔌 GLOBALNY WŁĄCZNIK EMAIL
        self.enabled = get_setting("email_enabled", "0") == "1"

        # 🔐 SENDGRID
        self.sendgrid_api_key = current_app.config.get("SENDGRID_API_KEY")
        self.sender = current_app.config.get("MAIL_FROM")

        self.base_url = (
            current_app.config.get("BASE_URL")
            or get_setting("base_url", "")
        ).rstrip("/")

        current_app.logger.warning(
            f"[EMAIL CONFIG] enabled={self.enabled} "
            f"provider=sendgrid_api "
            f"api_key={'SET' if self.sendgrid_api_key else 'MISSING'} "
            f"sender={self.sender}"
        )

    # ───────────────────────────────────────
    # GUARD
    # ───────────────────────────────────────
    def _can_send(self) -> bool:
        return (
            self.enabled
            and bool(self.sender)
            and bool(self.sendgrid_api_key)
        )

    # ───────────────────────────────────────
    # CORE SEND (SENDGRID API)
    # ───────────────────────────────────────
    def _send_email(
        self,
        *,
        to_email: str,
        subject: str,
        body: str,
        html: bool = True,
        reply_to: str | None = None
    ):
        if not self._can_send():
            raise RuntimeError("Email sending disabled or SendGrid not configured")

        sender_email = self.sender.split("<")[-1].strip(">").strip()
        sender_name = self.sender.split("<")[0].strip()

        payload = {
            "personalizations": [{
                "to": [{"email": to_email}],
                **({"reply_to": {"email": reply_to}} if reply_to else {})
            }],
            "from": {
                "email": sender_email,
                "name": sender_name
            },
            "subject": subject,
            "content": [{
                "type": "text/html" if html else "text/plain",
                "value": body
            }]
        }

        response = requests.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={
                "Authorization": f"Bearer {self.sendgrid_api_key}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=10
        )

        if response.status_code >= 300:
            raise Exception(
                f"SendGrid API error {response.status_code}: {response.text}"
            )

    # ───────────────────────────────────────
    # 🆕 RAW EMAIL (CONTACT FORM, SYSTEM)
    # ───────────────────────────────────────
    def send_raw(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        reply_to: str | None = None
    ):
        if not to:
            raise ValueError("Missing recipient email")

        current_app.logger.warning(
            f"[EMAIL] raw SEND attempt to={to}"
        )

        if not self._can_send():
            current_app.logger.warning(
                "[EMAIL] raw SKIPPED – email disabled or SendGrid API not configured"
            )
            return False

        try:
            self._send_email(
                to_email=to,
                subject=subject,
                body=body,
                html=False,
                reply_to=reply_to
            )

            current_app.logger.warning(
                f"[EMAIL] raw SENT to={to}"
            )
            return True

        except Exception as e:
            current_app.logger.error(
                f"[EMAIL] raw FAILED: {e}"
            )
            raise

    # ───────────────────────────────────────
    # CONFIRMATION EMAIL
    # ───────────────────────────────────────
    def send_confirmation(self, appointment: Appointment):
        current_app.logger.warning(
            f"[EMAIL] confirmation START appt={appointment.id}"
        )

        if not self._can_send():
            current_app.logger.warning(
                "[EMAIL] confirmation SKIPPED – email disabled or SendGrid API not configured"
            )
            return None

        if not appointment.patient_email:
            current_app.logger.warning(
                f"[EMAIL] confirmation SKIPPED – no patient_email appt={appointment.id}"
            )
            return None

        subject, body = self._build_confirmation_content(appointment)

        try:
            self._send_email(
                to_email=appointment.patient_email,
                subject=subject,
                body=body,
                html=True
            )

            appointment.email_confirmation_sent_at = datetime.utcnow()
            db.session.commit()

            current_app.logger.warning(
                f"[EMAIL] confirmation SENT appt={appointment.id} "
                f"to={appointment.patient_email}"
            )

        except Exception as e:
            current_app.logger.error(
                f"[EMAIL] confirmation FAILED appt={appointment.id}: {e}"
            )

    # ───────────────────────────────────────
    # REMINDER EMAIL
    # ───────────────────────────────────────
    def send_reminder(self, appointment: Appointment):
        if not self._can_send():
            return None

        if not appointment.patient_email:
            return None

        subject, body = self._build_reminder_content(appointment)

        try:
            self._send_email(
                to_email=appointment.patient_email,
                subject=subject,
                body=body,
                html=True
            )

            appointment.email_reminder_sent_at = datetime.utcnow()
            db.session.commit()

        except Exception as e:
            current_app.logger.error(
                f"[EMAIL] reminder FAILED appt={appointment.id}: {e}"
            )

    # ───────────────────────────────────────
    # CONTENT BUILDERS
    # ───────────────────────────────────────
    def _build_confirmation_content(self, appointment: Appointment):
        date_str = appointment.start.strftime("%d.%m.%Y")
        time_str = appointment.start.strftime("%H:%M")

        cancel_url = f"{self.base_url}/c/{appointment.cancel_token}"

        subject = "Potwierdzenie wizyty"

        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif">
          <h2>Potwierdzenie wizyty</h2>

          <p>
            Termin wizyty:<br>
            <strong>{date_str} godz. {time_str}</strong>
          </p>

          <p>
            Jeśli chcesz anulować wizytę, kliknij poniżej:
          </p>

          <p>
            <a href="{cancel_url}"
               style="display:inline-block;
                      padding:10px 16px;
                      background:#d73930;
                      color:#fff;
                      text-decoration:none;
                      border-radius:6px;">
              Anuluj wizytę
            </a>
          </p>

          <p style="color:#666; font-size:12px;">
            Jeśli to nie Ty rezerwowałeś wizytę – zignoruj tę wiadomość.
          </p>
        </body>
        </html>
        """

        return subject, body

    def _build_reminder_content(self, appointment: Appointment):
        date_str = appointment.start.strftime("%d.%m.%Y")
        time_str = appointment.start.strftime("%H:%M")

        subject = "Przypomnienie o wizycie"

        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif">
          <h2>Przypomnienie o wizycie</h2>

          <p>
            Przypominamy o wizycie:
            <br><strong>{date_str} godz. {time_str}</strong>
          </p>

          <p>Do zobaczenia!</p>
        </body>
        </html>
        """

        return subject, body
