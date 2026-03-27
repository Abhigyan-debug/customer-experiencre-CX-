from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100))
    password = db.Column(db.String(100))
    role = db.Column(db.String(20), default='user')


class Feedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    service = db.Column(db.String(100))
    text = db.Column(db.Text)

    sentiment = db.Column(db.String(20))
    emotion = db.Column(db.String(20))

    # 🔥 ADD THIS LINE
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))