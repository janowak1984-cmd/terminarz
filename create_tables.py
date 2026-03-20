from app import create_app
from models import db, Doctor

app = create_app()

with app.app_context():
    db.create_all()

    # create default doctor account
    if not Doctor.query.filter_by(username='doctor').first():
        Doctor.create_default('doctor', 'doctorpass')
        print("Default doctor created: doctor / doctorpass")

    print("Tables created.")
