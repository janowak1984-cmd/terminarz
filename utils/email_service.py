import requests
from datetime import datetime
from flask import current_app

from extensions import db
from models import Appointment, EmailMessage
from utils.settings import get_setting


class EmailService:

    def __init__(self):
        self.enabled = get_setting("email_enabled", "1") == "1"

        self.sendgrid_api_key = current_app.config.get("SENDGRID_API_KEY")
        self.sender = current_app.config.get("MAIL_FROM")

        self.base_url = (
            current_app.config.get("BASE_URL")
            or get_setting("base_url", "")
        ).rstrip("/")

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
    def _send_email(self, *, to_email, subject, body, html=True):

        sender_email = self.sender.split("<")[-1].strip(">").strip()
        sender_name = self.sender.split("<")[0].strip()

        payload = {
            "personalizations": [{
                "to": [{"email": to_email}]
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
                f"SendGrid error {response.status_code}: {response.text}"
            )

    # ───────────────────────────────────────
    # CONFIRMATION EMAIL
    # ───────────────────────────────────────
    def send_confirmation(self, appointment: Appointment):

        if not self._can_send():
            return None

        if not appointment.patient_email:
            return None

        subject, body = self._build_confirmation_content(appointment)

        email_log = EmailMessage(
            appointment_id=appointment.id,
            email=appointment.patient_email,
            type="confirmation",
            subject=subject,
            content=body,
            status="pending"
        )

        db.session.add(email_log)
        db.session.commit()

        try:
            self._send_email(
                to_email=email_log.email,
                subject=subject,
                body=body,
                html=True
            )

            email_log.status = "sent"
            email_log.sent_at = datetime.utcnow()

            appointment.email_confirmation_sent_at = email_log.sent_at

        except Exception as e:
            email_log.status = "failed"
            email_log.error_message = str(e)

        db.session.commit()
        return email_log

    # ───────────────────────────────────────
    # REMINDER EMAIL
    # ───────────────────────────────────────
    def send_reminder(self, appointment: Appointment):

        if not self._can_send():
            return None

        if not appointment.patient_email:
            return None

        subject, body = self._build_reminder_content(appointment)

        email_log = EmailMessage(
            appointment_id=appointment.id,
            email=appointment.patient_email,
            type="reminder",
            subject=subject,
            content=body,
            status="pending"
        )

        db.session.add(email_log)
        db.session.commit()

        try:
            self._send_email(
                to_email=email_log.email,
                subject=subject,
                body=body,
                html=True
            )

            email_log.status = "sent"
            email_log.sent_at = datetime.utcnow()

            appointment.email_reminder_sent_at = email_log.sent_at

        except Exception as e:
            email_log.status = "failed"
            email_log.error_message = str(e)

        db.session.commit()
        return email_log

    # ───────────────────────────────────────
    # TRADITIONAL PAYMENT EMAIL
    # ───────────────────────────────────────
    def send_traditional_payment_info(self, appointment, amount):

        if not appointment.patient_email:
            return None

        subject = "Dane do przelewu – potwierdzenie rezerwacji"

        body = f"""
Dzień dobry {appointment.patient_first_name},

Data wizyty: {appointment.start.strftime('%d.%m.%Y %H:%M')}
Kwota: {amount:.2f} PLN

Numer konta:
70 1140 2004 0000 3502 5354 7449

Tytuł przelewu: Wizyta {appointment.id}

Po zaksięgowaniu płatności wizyta zostanie potwierdzona.
"""

        email_log = EmailMessage(
            appointment_id=appointment.id,
            email=appointment.patient_email,
            type="payment_retry",
            subject=subject,
            content=body,
            status="pending"
        )

        db.session.add(email_log)
        db.session.commit()

        try:
            self._send_email(
                to_email=email_log.email,
                subject=subject,
                body=body,
                html=False
            )

            email_log.status = "sent"
            email_log.sent_at = datetime.utcnow()

        except Exception as e:
            email_log.status = "failed"
            email_log.error_message = str(e)

        db.session.commit()
        return email_log

    # ───────────────────────────────────────
    # CONTENT BUILDERS
    # ───────────────────────────────────────
    def _build_confirmation_content(self, appointment):
        date_str = appointment.start.strftime("%d.%m.%Y")
        time_str = appointment.start.strftime("%H:%M")

        cancel_url = f"{self.base_url}/c/{appointment.cancel_token}"

        subject = "Potwierdzenie wizyty"

        body = f"""
    <div style="font-family: Arial, Helvetica, sans-serif; background:#f4f4f4; padding:30px 15px;">

    <div style="max-width:520px; margin:0 auto; background:#ffffff; border-radius:8px; padding:30px; border:1px solid #e6e6e6;">

        <h2 style="margin-top:0; color:#000000;">
        Potwierdzenie wizyty
        </h2>

        <p style="font-size:16px; color:#333;">
        Dzień dobry {appointment.patient_first_name},
        </p>

        <p style="font-size:16px; color:#333;">
        Dziękujemy za rezerwację wizyty.
        </p>

        <div style="background:#f8f9fa; padding:15px; border-radius:6px; border:1px solid #eee; margin:20px 0;">
        <p style="margin:0; font-size:18px; font-weight:bold; color:#000;">
            {date_str}
        </p>
        <p style="margin:5px 0 0 0; font-size:16px; color:#555;">
            godz. {time_str}
        </p>
        </div>

        <p style="font-size:14px; color:#666;">
        Jeśli nie możesz przyjść, prosimy o anulowanie wizyty z wyprzedzeniem:
        </p>

        <div style="text-align:center; margin:25px 0;">
        <a href="{cancel_url}"
            style="background:#d73930; color:#ffffff; text-decoration:none; padding:12px 22px; border-radius:6px; font-weight:bold; display:inline-block;">
            Anuluj wizytę
        </a>
        </div>

        <hr style="border:none; border-top:1px solid #eee; margin:25px 0;">

        <p style="font-size:12px; color:#999; text-align:center;">
        Gabinet Podologiczny<br>
        Ta wiadomość została wygenerowana automatycznie.
        </p>

    </div>

    </div>
    """

        return subject, body

    def _build_reminder_content(self, appointment):
        date_str = appointment.start.strftime("%d.%m.%Y")
        time_str = appointment.start.strftime("%H:%M")

        subject = "Przypomnienie o wizycie"

        body = f"""
    <div style="font-family: Arial, Helvetica, sans-serif; background:#f4f4f4; padding:30px 15px;">

    <div style="max-width:520px; margin:0 auto; background:#ffffff; border-radius:8px; padding:30px; border:1px solid #e6e6e6;">

        <h2 style="margin-top:0; color:#000000;">
        Przypomnienie o wizycie
        </h2>

        <p style="font-size:16px; color:#333;">
        Dzień dobry {appointment.patient_first_name},
        </p>

        <p style="font-size:16px; color:#333;">
        Przypominamy o nadchodzącej wizycie:
        </p>

        <div style="background:#f8f9fa; padding:15px; border-radius:6px; border:1px solid #eee; margin:20px 0;">
        <p style="margin:0; font-size:18px; font-weight:bold; color:#000;">
            {date_str}
        </p>
        <p style="margin:5px 0 0 0; font-size:16px; color:#555;">
            godz. {time_str}
        </p>
        </div>

        <p style="font-size:14px; color:#666;">
        W razie potrzeby prosimy o kontakt z gabinetem.
        </p>

        <hr style="border:none; border-top:1px solid #eee; margin:25px 0;">

        <p style="font-size:12px; color:#999; text-align:center;">
        Gabinet Podologiczny<br>
        Ta wiadomość została wygenerowana automatycznie.
        </p>

    </div>

    </div>
    """

        return subject, body