from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from extensions import db
from models import ScheduleTemplate

bp = Blueprint("doctor_templates", __name__, url_prefix="/doctor/templates")


@bp.get("/")
@login_required
def list_templates():
    templates = ScheduleTemplate.query.filter_by(
        doctor_id=current_user.id
    ).all()

    return jsonify([
        {"id": t.id, "name": t.name, "days": t.days_json}
        for t in templates
    ])


@bp.post("/")
@login_required
def create_template():
    data = request.json

    t = ScheduleTemplate(
        doctor_id=current_user.id,
        name=data["name"],
        days_json=data["days"]
    )
    db.session.add(t)
    db.session.commit()

    return jsonify({"status": "ok"})


@bp.put("/<int:template_id>")
@login_required
def update_template(template_id):
    t = ScheduleTemplate.query.filter_by(
        id=template_id,
        doctor_id=current_user.id
    ).first_or_404()

    data = request.json
    t.name = data["name"]
    t.days_json = data["days"]
    db.session.commit()

    return jsonify({"status": "ok"})


@bp.delete("/<int:template_id>")
@login_required
def delete_template(template_id):
    t = ScheduleTemplate.query.filter_by(
        id=template_id,
        doctor_id=current_user.id
    ).first_or_404()

    db.session.delete(t)
    db.session.commit()

    return jsonify({"status": "ok"})
