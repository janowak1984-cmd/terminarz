# utils/settings.py
import json
from extensions import db
from models import Setting


def get_setting(key, default=None, cast=None):
    """
    Pobiera ustawienie z tabeli settings.
    cast: list | int | bool | str | None
    """

    setting = Setting.query.filter_by(key=key).first()

    if not setting:
        return default

    value = setting.value

    try:
        if cast == list:
            return json.loads(value)
        if cast == int:
            return int(value)
        if cast == bool:
            return value.lower() in ("1", "true", "yes", "on")
    except Exception:
        return default

    return value


def set_setting(key, value):
    """
    Zapisuje / aktualizuje ustawienie w tabeli settings.
    BEZ zmiany istniejących zachowań get_setting().
    """

    setting = Setting.query.filter_by(key=key).first()

    if setting:
        setting.value = str(value)
    else:
        setting = Setting(
            key=key,
            value=str(value)
        )
        db.session.add(setting)

    db.session.commit()
