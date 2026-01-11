from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required
from models import Doctor

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/doctor/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        user = Doctor.query.filter_by(username=username).first()

        if user and user.check_password(password):
            login_user(user)  # zapis do sesji
            return redirect(url_for("doctor.dashboard"))

        flash("Błędny login lub hasło", "danger")

    return render_template("doctor_login.html")


@auth_bp.route("/doctor/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
