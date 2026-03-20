from extensions import db
from models import Setting


def init_default_settings():
    defaults = [
        {
            "key": "calendar_visible_days",
            "description": "Dni tygodnia widoczne w kalendarzu lekarza",
            "value": "mon,tue,wed,thu,fri"
        }
    ]

    for item in defaults:
        exists = Setting.query.filter_by(key=item["key"]).first()
        if not exists:
            db.session.add(Setting(
                key=item["key"],
                description=item["description"],
                value=item["value"]
            ))

    db.session.commit()
