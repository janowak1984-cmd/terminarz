from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required

from extensions import db
from models import VisitType
from sqlalchemy import func
from flask import jsonify


# ✅ Oficjalne kolory Google Calendar (event.colorId → HEX)
GOOGLE_COLORS = {
    "1": "#7986CB",   # Lavender
    "2": "#33B679",   # Sage
    "3": "#8E24AA",   # Grape
    "4": "#E67C73",   # Flamingo
    "5": "#F6BF26",   # Banana
    "6": "#F4511E",   # Tangerine
    "7": "#039BE5",   # Peacock
    "8": "#616161",   # Graphite
    "9": "#3F51B5",   # Blueberry
    "10": "#0B8043",  # Basil
    "11": "#D50000",  # Tomato
}


bp = Blueprint(
    "doctor_visit_types",
    __name__,
    url_prefix="/doctor/visit-types"
)

# ===============================
# LISTA (HTML)
# ===============================
@bp.route("/", methods=["GET"])
@login_required
def list_view():
    visit_types = (
        VisitType.query
        .order_by(VisitType.display_order.asc(), VisitType.id.asc())
        .all()
    )

    return render_template(
        "doctor/visit_types.html",
        active_page="visit_types",
        visit_types=visit_types,
        google_colors=GOOGLE_COLORS   # ✅ tylko to jest potrzebne w Jinja
    )

# ===============================
# GET ONE (API – EDYCJA)
# ===============================
@bp.route("/api/<int:vt_id>", methods=["GET"])
@login_required
def get_one(vt_id):
    vt = VisitType.query.get_or_404(vt_id)

    return jsonify({
        "id": vt.id,
        "name": vt.name,
        "code": vt.code,
        "description": vt.description,
        "price": float(vt.price) if vt.price is not None else None,
        "duration_minutes": vt.duration_minutes,
        "color": vt.color,
        "active": vt.active,
        "display_order": vt.display_order,
        "display_order_doctor": vt.display_order_doctor
    })


# ===============================
# CREATE
# ===============================
@bp.route("/", methods=["POST"])
@login_required
def create():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Brak danych"}), 400

    # 🔒 WALIDACJA WYMAGANYCH PÓL
    for field in ("name", "code", "duration_minutes", "display_order", "display_order_doctor"):
        if data.get(field) in (None, ""):
            return jsonify({"error": f"Pole '{field}' jest wymagane"}), 400

    # 🔒 WALIDACJA UNIKALNOŚCI KODU (case-insensitive)
    existing = VisitType.query.filter(
        func.lower(VisitType.code) == data["code"].lower()
    ).first()

    if existing:
        return jsonify({
            "error": "Typ wizyty o takim kodzie już istnieje."
        }), 400

    # 🔢 KOLEJNOŚĆ WYŚWIETLANIA
    new_order = int(data.get("display_order", 100))
    new_order_doctor = int(data.get("display_order_doctor", 100))

    VisitType.query.filter(
        VisitType.display_order >= new_order
    ).update(
        {VisitType.display_order: VisitType.display_order + 1},
        synchronize_session=False
    )

    # 💰 PRICE – BEZPIECZNE PARSOWANIE
    price_raw = data.get("price")
    price = float(price_raw) if price_raw not in (None, "", []) else None

    if price is not None and price < 0:
        return jsonify({"error": "Cena nie może być ujemna"}), 400

    # ✅ UTWORZENIE TYPU WIZYTY
    vt = VisitType(
        name=data["name"],
        code=data["code"],
        description=data.get("description"),
        price=price,
        duration_minutes=int(data["duration_minutes"]),
        color=data.get("color", GOOGLE_COLORS["1"]),
        active=bool(data.get("active", True)),
        display_order=new_order,
        display_order_doctor=new_order_doctor
    )


    db.session.add(vt)
    db.session.commit()

    return jsonify({"status": "ok", "id": vt.id})


# ===============================
# UPDATE
# ===============================
@bp.route("/<int:vt_id>", methods=["PUT"])
@login_required
def update(vt_id):
    vt = VisitType.query.get_or_404(vt_id)
    data = request.get_json()
    if not data:
        return jsonify({"error": "Brak danych"}), 400

    # 🔒 WALIDACJA WYMAGANYCH PÓL
    for field in ("name", "code", "duration_minutes", "display_order", "display_order_doctor"):
        if data.get(field) in (None, ""):
            return jsonify({"error": f"Pole '{field}' jest wymagane"}), 400


    # 🔒 WALIDACJA UNIKALNOŚCI KODU (Z WYKLUCZENIEM BIEŻĄCEGO)
    existing = VisitType.query.filter(
        func.lower(VisitType.code) == data["code"].lower(),
        VisitType.id != vt.id
    ).first()

    if existing:
        return jsonify({
            "error": "Typ wizyty o takim kodzie już istnieje."
        }), 400

    old_order = vt.display_order
    new_order = int(data.get("display_order", old_order))

    if new_order != old_order:
        if new_order > old_order:
            VisitType.query.filter(
                VisitType.display_order > old_order,
                VisitType.display_order <= new_order,
                VisitType.id != vt.id
            ).update(
                {VisitType.display_order: VisitType.display_order - 1},
                synchronize_session=False
            )
        else:
            VisitType.query.filter(
                VisitType.display_order >= new_order,
                VisitType.display_order < old_order,
                VisitType.id != vt.id
            ).update(
                {VisitType.display_order: VisitType.display_order + 1},
                synchronize_session=False
            )

        vt.display_order = new_order

    vt.name = data["name"]
    vt.code = data["code"]
    vt.description = data.get("description")
    vt.price = data.get("price")
    vt.duration_minutes = int(data["duration_minutes"])
    vt.color = data.get("color", vt.color)
    vt.active = data.get("active", True)
    vt.display_order_doctor = int(data.get("display_order_doctor", vt.display_order_doctor)
)


    db.session.commit()
    return jsonify({"status": "ok"})


# ===============================
# TOGGLE ACTIVE
# ===============================
@bp.route("/toggle/<int:vt_id>", methods=["POST"])
@login_required
def toggle(vt_id):
    vt = VisitType.query.get_or_404(vt_id)
    vt.active = not vt.active
    db.session.commit()
    return redirect(url_for("doctor_visit_types.list_view"))

# ===============================
# DELETE
# ===============================
@bp.route("/delete/<int:vt_id>", methods=["POST"])
@login_required
def delete(vt_id):
    vt = VisitType.query.get_or_404(vt_id)

    VisitType.query.filter(
        VisitType.display_order > vt.display_order
    ).update(
        {VisitType.display_order: VisitType.display_order - 1},
        synchronize_session=False
    )

    db.session.delete(vt)
    db.session.commit()

    flash("🗑 Typ wizyty usunięty")
    return redirect(url_for("doctor_visit_types.list_view"))
    