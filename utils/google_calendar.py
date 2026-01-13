from datetime import datetime
from flask import current_app
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

from extensions import db
from utils.settings import get_setting, set_setting
from models import VisitType


# ======================================================
# ❌ BRAK POŁĄCZENIA
# ======================================================

class GoogleCalendarNotConnected(Exception):
    pass


# ======================================================
# 📅 GOOGLE CALENDAR SERVICE
# ======================================================

class GoogleCalendarService:
    """
    JEDYNE miejsce w systemie, które:
    - zna Google API
    - zarządza tokenami
    - tworzy / aktualizuje / usuwa eventy
    """

    SCOPES = ["https://www.googleapis.com/auth/calendar"]

    # --------------------------------------------------
    # 🔌 CONNECT / AUTH
    # --------------------------------------------------

    @staticmethod
    def get_service():
        if get_setting("google_connected") != "1":
            raise GoogleCalendarNotConnected()

        access_token = get_setting("google_access_token")
        refresh_token = get_setting("google_refresh_token")

        if not access_token or not refresh_token:
            GoogleCalendarService.disconnect()
            raise GoogleCalendarNotConnected()

        creds = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=current_app.config["GOOGLE_CLIENT_ID"],
            client_secret=current_app.config["GOOGLE_CLIENT_SECRET"],
            scopes=GoogleCalendarService.SCOPES,
        )

        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                set_setting("google_access_token", creds.token)
            except Exception as e:
                current_app.logger.error(f"[GOOGLE] token refresh failed: {e}")
                GoogleCalendarService.disconnect()
                raise GoogleCalendarNotConnected()

        return build("calendar", "v3", credentials=creds)

    @staticmethod
    def disconnect():
        set_setting("google_connected", "0")
        set_setting("google_access_token", "")
        set_setting("google_refresh_token", "")
        set_setting("google_calendar_id", "")

    # --------------------------------------------------
    # 🧱 EVENT BUILDER (JEDNO ŹRÓDŁO PRAWDY)
    # --------------------------------------------------

    @staticmethod
    def _build_event(appt):
        visit_type = VisitType.query.filter_by(code=appt.visit_type).first()
        color_id = visit_type.color if visit_type and visit_type.color else "1"

        return {
            "summary": f"Wizyta: {appt.patient_first_name} {appt.patient_last_name}",
            "description": f"Telefon: {appt.patient_phone}",
            "start": {
                "dateTime": appt.start.isoformat(),
                "timeZone": "Europe/Warsaw",
            },
            "end": {
                "dateTime": appt.end.isoformat(),
                "timeZone": "Europe/Warsaw",
            },
            "colorId": color_id,
        }

    # --------------------------------------------------
    # 🔁 GŁÓWNA METODA (KOMPATYBILNA Z OBECNYM KODEM)
    # --------------------------------------------------

    @staticmethod
    def sync_appointment(appt, force_update=False):
        """
        Zachowana kompatybilność z istniejącym doctor.py
        """

        try:
            service = GoogleCalendarService.get_service()
        except GoogleCalendarNotConnected:
            return

        calendar_id = get_setting("google_calendar_id") or "primary"

        # ⛔ brak duplikatów (chyba że wymuszony update)
        if appt.google_sync_status == "synced" and not force_update:
            return

        event_body = GoogleCalendarService._build_event(appt)

        try:
            # UPDATE
            if appt.google_event_id:
                service.events().update(
                    calendarId=calendar_id,
                    eventId=appt.google_event_id,
                    body=event_body
                ).execute()

            # CREATE
            else:
                created = service.events().insert(
                    calendarId=calendar_id,
                    body=event_body
                ).execute()
                appt.google_event_id = created["id"]

            appt.google_sync_status = "synced"
            appt.google_last_sync_at = datetime.utcnow()
            db.session.commit()

        except Exception as e:
            appt.google_sync_status = "error"
            db.session.commit()
            current_app.logger.error(
                f"[GOOGLE] sync failed appt={appt.id}: {e}"
            )

    # --------------------------------------------------
    # 🟢 NOWE, JASNE METODY (DO UŻYCIA TERAZ / PÓŹNIEJ)
    # --------------------------------------------------

    @staticmethod
    def on_created(appt):
        GoogleCalendarService.sync_appointment(appt)

    @staticmethod
    def on_updated(appt):
        GoogleCalendarService.sync_appointment(appt, force_update=True)

    @staticmethod
    def on_deleted(appt):
        GoogleCalendarService.delete_appointment(appt)

    # --------------------------------------------------
    # ➕ MANUALNE: DODAJ PONOWNIE DO GOOGLE
    # --------------------------------------------------

    @staticmethod
    def add_again(appt):
        """
        Celowo NIE sprawdza duplikatów.
        Tworzy nowy event nawet jeśli powstanie duplikat.
        """
        try:
            service = GoogleCalendarService.get_service()
        except GoogleCalendarNotConnected:
            return

        calendar_id = get_setting("google_calendar_id") or "primary"
        event_body = GoogleCalendarService._build_event(appt)

        try:
            created = service.events().insert(
                calendarId=calendar_id,
                body=event_body
            ).execute()

            appt.google_event_id = created["id"]
            appt.google_sync_status = "synced"
            appt.google_last_sync_at = datetime.utcnow()
            db.session.commit()

        except Exception as e:
            current_app.logger.error(
                f"[GOOGLE] manual add failed appt={appt.id}: {e}"
            )

    # --------------------------------------------------
    # 🗑 DELETE
    # --------------------------------------------------

    @staticmethod
    def delete_appointment(appt):
        if not appt.google_event_id:
            return

        try:
            service = GoogleCalendarService.get_service()
        except GoogleCalendarNotConnected:
            return

        calendar_id = get_setting("google_calendar_id") or "primary"

        try:
            service.events().delete(
                calendarId=calendar_id,
                eventId=appt.google_event_id
            ).execute()
        except Exception as e:
            current_app.logger.warning(
                f"[GOOGLE] delete skipped appt={appt.id}: {e}"
            )

        appt.google_event_id = None
        appt.google_sync_status = "deleted"
        appt.google_last_sync_at = datetime.utcnow()
        db.session.commit()

    # --------------------------------------------------
    # 🧱 EVENT BUILDER (WSPÓLNY)
    # --------------------------------------------------
    @staticmethod
    def build_event(appt):
        visit_type = VisitType.query.filter_by(code=appt.visit_type).first()

        color_id = (
            visit_type.color
            if visit_type and visit_type.color
            else "1"
        )

        return {
            "summary": f"Wizyta: {appt.patient_first_name} {appt.patient_last_name}",
            "description": f"Telefon: {appt.patient_phone}",
            "start": {
                "dateTime": appt.start.isoformat(),
                "timeZone": "Europe/Warsaw",
            },
            "end": {
                "dateTime": appt.end.isoformat(),
                "timeZone": "Europe/Warsaw",
            },
            "colorId": color_id,
        }


    @staticmethod
    def force_create_event(appt):
        """
        🔥 JAWNE DODANIE EVENTU
        - ZAWSZE tworzy nowy event
        - NIE sprawdza google_event_id
        - MOŻE stworzyć duplikat
        """
        try:
            service = GoogleCalendarService.get_service()
        except GoogleCalendarNotConnected:
            return

        calendar_id = get_setting("google_calendar_id") or "primary"

        event_body = GoogleCalendarService.build_event(appt)

        created = service.events().insert(
            calendarId=calendar_id,
            body=event_body
        ).execute()

        # ⚠️ NADPISUJEMY ID — świadomie
        appt.google_event_id = created["id"]
        appt.google_sync_status = "synced"
        appt.google_last_sync_at = datetime.utcnow()
        db.session.commit()

