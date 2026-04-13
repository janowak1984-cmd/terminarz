import requests
from datetime import datetime

from extensions import db
from models import SMSMessage, Appointment
from utils.settings import get_setting

from flask import current_app


class SMSService:
    SMSAPI_URL = "https://api.smsapi.pl/sms.do"

    def __init__(self):
        # 🔌 GLOBALNY WŁĄCZNIK SMS
        self.enabled = get_setting("sms_enabled", "0") == "1"

        self.api_token = (
            current_app.config.get("SMSAPI_TOKEN")
            or get_setting("smsapi_token")
        )

        self.sender = (
            current_app.config.get("SMSAPI_SENDER")
            or get_setting("smsapi_sender", "SMSAPI")
        )

        self.base_url = (
            current_app.config.get("BASE_URL")
            or get_setting("base_url", "")
        ).rstrip("/")


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
    # ONLINE VISIT LINK SMS
    # ───────────────────────────────────────
    def send_online_meet_link(self, appointment: Appointment):

        if not self._can_send():
            return None

        content = self._build_online_meet_content(appointment)

        sms = SMSMessage(
            appointment_id=appointment.id,
            phone=appointment.patient_phone,
            type="online_meet",
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
            else:
                sms.status = "failed"
                sms.error_message = data.get("message", "Unknown error")

        except Exception as e:
            sms.status = "failed"
            sms.error_message = str(e)

        db.session.commit()
        return sms
    
    def send_payment_notification(self, appointment: Appointment):
        if not self._can_send():
            return None

        phone = "+48608597050"

        content = self._build_payment_notification_content(appointment)

        sms = SMSMessage(
            appointment_id=appointment.id,
            phone=phone,
            type="payment_notification",
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

        cancel_url = f"{self.base_url}/c/{appointment.cancel_token}"

        return (
            f"{date_str} godz. {time_str}\n"
            f"Aby anulowac wizyte wejdz na: {cancel_url}\n"
            f"Auto-wiadomosc - prosimy nie odpowiadac"
        )

    def _build_reminder_content(self, appointment: Appointment) -> str:
        date_str = appointment.start.strftime("%d.%m.%Y")
        time_str = appointment.start.strftime("%H:%M")

        return (
            f"Przypomnienie o wizycie:\n"
            f"{date_str} godz. {time_str}\n"
            f"Do zobaczenia."
        )

    def _build_online_meet_content(self, appointment: Appointment) -> str:

        date_str = appointment.start.strftime("%d.%m.%Y")
        time_str = appointment.start.strftime("%H:%M")

        meet_link = "https://meet.google.com/eev-cxtv-ycq"

        return (
            f"Wizyta online {date_str} {time_str}. "
            f"Link do spotkania: {meet_link}. "
            f"Prosze dolaczyc kilka minut przed wizyta."
        )
    def _build_payment_notification_content(self, appointment: Appointment) -> str:
        return (
            f"Pacjent {appointment.patient_first_name} {appointment.patient_last_name}"
            f"({appointment.patient_phone}) "
            f"zarezerwowal i oplacil wizyte w P24."
        )