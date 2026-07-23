from datetime import datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Index, MetaData

# Named constraints so Alembic can target them (e.g. drop/alter a foreign key)
# during a migration - SQLite reflects unnamed constraints as anonymous, which
# batch-mode ALTER can't reference without this convention.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

db = SQLAlchemy(metadata=MetaData(naming_convention=NAMING_CONVENTION))


def utcnow():
    return datetime.now(timezone.utc)


class User(db.Model, UserMixin):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False, index=True)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="analyst", index=True)
    email = db.Column(db.String(255), unique=True, index=True)
    email_notify = db.Column(db.Boolean, nullable=False, default=True)
    ai_enabled = db.Column(db.Boolean, nullable=False, default=True)
    avatar = db.Column(db.String(200))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)
    feedbacks = db.relationship("Feedback", backref="user", lazy="dynamic", cascade="all, delete-orphan")

    # Forgot-password flow. One active token per user (issuing a new one
    # implicitly invalidates any previous one) - DB-backed rather than an
    # in-memory dict so it survives a restart and works correctly even if
    # more than one server process ends up running.
    reset_token = db.Column(db.String(64), unique=True, index=True)
    reset_token_expires = db.Column(db.DateTime(timezone=True))


class Feedback(db.Model):
    __tablename__ = "feedbacks"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, default="Anonymous")
    phone = db.Column(db.String(24))
    service = db.Column(db.String(100), nullable=False, default="General", index=True)
    text = db.Column(db.Text, nullable=False)
    sentiment = db.Column(db.String(20), nullable=False, index=True)
    sentiment_score = db.Column(db.Float, nullable=False, default=0.0)
    emotion = db.Column(db.String(32), nullable=False, default="Neutral", index=True)
    emotion_score = db.Column(db.Float, nullable=False, default=0.0)
    topic = db.Column(db.String(80), nullable=False, default="General", index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    __table_args__ = (Index("ix_feedback_owner_created", "user_id", "created_at"),)


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action = db.Column(db.String(80), nullable=False, index=True)
    resource = db.Column(db.String(80), nullable=False)
    detail = db.Column(db.String(500))
    ip_address = db.Column(db.String(64))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow, index=True)


class AIInsight(db.Model):
    """Cached AI-generated insight for a user's feedback (or the admin 'all data' view).

    Regenerated only when the underlying feedback count changes, so page loads
    don't pay for a synchronous LLM call every time.
    """
    __tablename__ = "ai_insights"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), index=True)
    scope = db.Column(db.String(10), nullable=False, default="my")  # 'my' or 'all'
    feedback_count = db.Column(db.Integer, nullable=False, default=0)
    summary = db.Column(db.Text)
    pain_points = db.Column(db.JSON)
    positive_highlights = db.Column(db.JSON)
    recommendations = db.Column(db.JSON)
    action_items = db.Column(db.JSON)
    trend_analysis = db.Column(db.Text)
    predictive_insights = db.Column(db.Text)
    generated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utcnow)

    __table_args__ = (Index("ix_insight_owner_scope", "user_id", "scope", unique=True),)
