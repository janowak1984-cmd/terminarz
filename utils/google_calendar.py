from datetime import datetime
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from flask import current_app

from extensions import db
from utils.settings import get_setting, set_setting
from models import VisitType


# ======================================================
# 🎨 MAPOWANIE KOLORÓW VISIT TYPE → GOOGLE COLOR ID
# ======================================================

GOOGLE_COLOR_MAP = {
    "#4285F4": "1",
    "#1A73E8": "9",
    "#3367D6": "9",
    "#0D47A1": "9",
    "#5C9DED": "1",
    "#90CAF9": "1",

    "#5C6BC0": "3",
    "#7E57C2": "3",
    "#8E24AA": "3",
    "#A142F4": "3",
    "#6A1B9A": "3",
    "#B39DDB": "3",

    "#FBBC05": "5",
    "#FDD663": "5",
    "#FFC107": "5",
    "#FFB300": "5",

    "#EA4335": "4",
    "#D93025": "11",
    "#C5221F": "11",

    "#E91E63": "4",
    "#EC407A": "4",
    "#F06292": "4",
    "#AD1457": "11",

    "#9AA0A6": "8",
    "#607D8B": "8",
    "#455A64": "8",
}


# ======================================================
# ❌ BRAK POŁĄCZENIA
# ======================================================

class GoogleCalendarNotConnected(Exception):
    pass


# ======================================================
# 📅 GOOGLE CALENDAR SERVICE
# ======================================================

class GoogleCalendarService:

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
    # 📅 SYNC (CREATE / UPDATE) — BEZ DUPLIKATÓW
    # --------------------------------------------------

    @staticmethod
    def sync_appointment(appt, force_update=False):
        try:
            service = GoogleCalendarService.get_service()
        except GoogleCalendarNotConnected:
            return

        calendar_id = get_setting("google_calendar_id") or "primary"

        # ⛔ BLOKADA DUPLIKATÓW
        if appt.google_sync_status == "synced" and not force_update:
            return

        visit_type = VisitType.query.filter_by(code=appt.visit_type).first()
        color_id = visit_type.color if visit_type and visit_type.color else "1"

        event_body = {
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

        try:
            # UPDATE
            if appt.google_event_id:
                service.events().update(
                    calendarId=calendar_id,
                    eventId=appt.google_event_id,
                    body=event_body
                ).execute()

            # CREATE — TYLKO RAZ
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
    # ✅ JAWNY UPDATE (OPCJA 1)
    # --------------------------------------------------

    @staticmethod
    def sync_appointment_update(appt):
        """
        Używać PRZY KAŻDEJ ZMIANIE:
        - przesunięcie wizyty
        - zmiana godziny
        - edycja z panelu lekarza
        """
        GoogleCalendarService.sync_appointment(appt, force_update=True)

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
