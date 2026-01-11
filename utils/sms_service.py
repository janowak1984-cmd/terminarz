import requests
from datetime import datetime

from extensions import db
from models import SMSMessage, Appointment
from utils.settings import get_setting


class SMSService:
    SMSAPI_URL = "https://api.smsapi.pl/sms.do"

    def __init__(self):
        # 🔌 GLOBALNY WŁĄCZNIK SMS
        self.enabled = get_setting("sms_enabled", "0") == "1"

        # dane konfiguracyjne (ZAWSZE inicjalizowane)
        self.api_token = get_setting("smsapi_token")
        self.sender = get_setting("smsapi_sender", "SMSAPI")

        self.base_url = get_setting("base_url", "").rstrip("/")

    # ───────────────────────────────────────
    # GUARD
    # ───────────────────────────────────────
    def _can_send(self) -> bool:
        return self.enabled and bool(self.api_token)

    # ───────────────────────────────────────
    # CORE SEND
    # ───────────────────────────────────────
    def _send_sms(self, phone: str, content: str):
        payload = {
            "to": phone,
            "message": content,
            "from": self.sender,
            "format": "json"
        }

        headers = {
            "Authorization": f"Bearer {self.api_token}"
        }

        return requests.post(
            self.SMSAPI_URL,
            data=payload,
            headers=headers,
            timeout=10
        )

    # ───────────────────────────────────────
    # CONFIRMATION SMS
    # ───────────────────────────────────────
    def send_confirmation(self, appointment: Appointment):
        if not self._can_send():
            return None

        content = self._build_confirmation_content(appointment)

        sms = SMSMessage(
            appointment_id=appointment.id,
            phone=appointment.patient_phone,
            type="confirmation",
            content=content,
            status="pending"
        )

        # 🔴 zapis PRZED wysyłką
        db.session.add(sms)
        db.session.commit()

        try:
            response = self._send_sms(sms.phone, sms.content)
            data = response.json() if response.content else {}

            if response.status_code == 200 and data.get("count", 0) > 0:
                sms.status = "sent"
                sms.sent_at = datetime.utcnow()
                sms.provider_message_id = str(
                    data.get("list", [{}])[0].get("id")
                )

                appointment.sms_confirmation_sent_at = sms.sent_at
            else:
                sms.status = "failed"
                sms.error_message = data.get("message", "Unknown error")

        except Exception as e:
            sms.status = "failed"
            sms.error_message = str(e)

        db.session.commit()
        return sms

    # ───────────────────────────────────────
    # REMINDER SMS
    # ───────────────────────────────────────
    def send_reminder(self, appointment: Appointment):
        if not self._can_send():
            return None

        content = self._build_reminder_content(appointment)

        sms = SMSMessage(
            appointment_id=appointment.id,
            phone=appointment.patient_phone,
            type="reminder",
            content=content,
            status="pending"
        )

        db.session.add(sms)
        db.session.commit()

        try:
            response = self._send_sms(sms.phone, sms.content)
            data = response.json() if response.content else {}

            if response.status_code == 200 and data.get("count", 0) > 0:
                sms.status = "sent"
                sms.sent_at = datetime.utcnow()
                sms.provider_message_id = str(
                    data.get("list", [{}])[0].get("id")
                )

                appointment.sms_reminder_sent_at = sms.sent_at
            else:
                sms.status = "failed"
                sms.error_message = data.get("message", "Unknown error")

        except Exception as e:
            sms.status = "failed"
            sms.error_message = str(e)

        db.session.commit()
        return sms

    # ───────────────────────────────────────
    # CONTENT BUILDERS
    # ───────────────────────────────────────
    def _build_confirmation_content(self, appointment: Appointment) -> str:
        date_str = appointment.start.strftime("%d.%m.%Y")
        time_str = appointment.start.strftime("%H:%M")

        base_url = get_setting("base_url", "").rstrip("/")
        cancel_url = f"{base_url}/c/{appointment.cancel_token}"

        return (
            f"Wizyta {date_str} {time_str}. "
            f"Anuluj: {cancel_url}"
        )



    def _build_reminder_content(self, appointment: Appointment) -> str:
        date_str = appointment.start.strftime("%d.%m.%Y")
        time_str = appointment.start.strftime("%H:%M")

        return (
            f"Przypomnienie o wizycie:\n"
            f"{date_str} godz. {time_str}\n"
            f"Do zobaczenia."
        )
