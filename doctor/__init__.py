from .appointments import bp as appointments_bp
from .availability_list import bp as availability_list_bp
from .availability_cal import bp as availability_cal_bp
from .generate import bp as generate_bp
from .vacations import doctor_vacations_bp


def init_app(app):
    app.register_blueprint(appointments_bp)
    app.register_blueprint(availability_list_bp)
    app.register_blueprint(availability_cal_bp)
    app.register_blueprint(generate_bp)
    app.register_blueprint(doctor_vacations_bp)