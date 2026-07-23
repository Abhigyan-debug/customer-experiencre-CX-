from collections import Counter

from flask import Flask, render_template, redirect, request, abort, flash, url_for, jsonify
from models import db, User, Feedback, AIInsight, AuditLog, utcnow
from sqlalchemy import func

MAX_CSV_ROWS = 5000        # safety cap on a single CSV import
TREND_WINDOW = 200         # points shown on the sentiment trend chart
EVAL_SAMPLE_LIMIT = 500    # rows sampled for the self-consistency widget (see evaluate_model)
ALLOWED_AVATAR_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
from flask_wtf import CSRFProtect
from flask_migrate import Migrate, upgrade
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from flask_mail import Mail, Message
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from textblob import TextBlob
from datetime import timedelta, timezone
import csv
from flask import Response
import io
import json
import logging
import secrets
import os
import sys
import uuid

from dotenv import load_dotenv
from groq import Groq
load_dotenv()

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

api_key = os.getenv("GROQ_API_KEY")

if not api_key:
    raise ValueError("GROQ_API_KEY not set")

client = Groq(api_key=api_key)

AI_ENABLED = True


def evaluate_model(feedbacks):
    """Self-consistency check, NOT accuracy against ground truth - there is
    no labeled validation dataset for this app's feedback. This re-runs the
    current classifier against each row's already-stored text and measures
    how often it agrees with the sentiment that was saved at write time.
    A low score means either the scoring logic has drifted since those rows
    were classified, or a lot of the underlying text sits right on a
    decision boundary - either way, it's a real, honest signal instead of
    the placeholder "does the word 'good' appear" heuristic this replaced."""
    from sklearn.metrics import accuracy_score, precision_score, recall_score

    y_stored = []
    y_fresh = []

    for f in feedbacks:
        if f.text:
            fresh_label, _ = get_sentiment(f.text)
            y_stored.append(f.sentiment)
            y_fresh.append(fresh_label)

    if not y_stored:
        return 0, 0, 0

    consistency = accuracy_score(y_stored, y_fresh)
    precision = precision_score(y_stored, y_fresh, average='macro', zero_division=0)
    recall = recall_score(y_stored, y_fresh, average='macro', zero_division=0)

    return round(consistency*100,2), round(precision*100,2), round(recall*100,2)


# In-memory cache for the self-consistency widget, same pattern as
# login_attempts below - keyed on (owner, scope) with the
# feedback count as the invalidation check (mirrors get_cached_insight's
# strategy). Without this, /api/dashboard_data's 30s auto-refresh was
# re-running TextBlob analysis over up to EVAL_SAMPLE_LIMIT rows on every
# single poll, which was pure wasted CPU since that number barely moves
# between two 30-second snapshots of the same data.
_eval_cache = {}


def get_cached_evaluation(owner_key, scope, count, base_query):
    cache_key = (owner_key, scope)
    cached = _eval_cache.get(cache_key)
    if cached and cached[0] == count:
        return cached[1]

    eval_sample = base_query.order_by(Feedback.created_at.desc()).limit(EVAL_SAMPLE_LIMIT).all()
    result = evaluate_model(eval_sample)
    _eval_cache[cache_key] = (count, result)
    return result


app = Flask(__name__)
app.logger.setLevel(logging.INFO)

#  CSRF PROTECTION
csrf = CSRFProtect(app)

#  CONFIG
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", secrets.token_hex(16))
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024  # 8MB upload cap (CSV / avatar)

# 📧 MAIL (forgot-password reset links)
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', '1') == '1'
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER') or app.config['MAIL_USERNAME']

mail = Mail(app)
# Not a hard requirement at startup (unlike GROQ_API_KEY) - the rest of the
# app works fine with no mail configured, forgot-password just tells the
# user plainly that it isn't set up yet instead of the app failing to boot.
MAIL_CONFIGURED = bool(app.config['MAIL_USERNAME'] and app.config['MAIL_PASSWORD'])
if not MAIL_CONFIGURED:
    logging.getLogger(__name__).warning(
        "MAIL_USERNAME/MAIL_PASSWORD not set - password reset emails will not be sent. "
        "See .env.example for the MAIL_* variables to configure."
    )

# 📦 STATIC FILE CACHING - Flask's default is effectively no-cache, which
# meant style.css and the self-hosted vendor JS (chart.js/lucide/three.js,
# ~1.2MB combined) were being re-validated on every single page navigation
# instead of served from the browser's cache. 1 hour for regular static
# assets (style.css/js) balances that against picking up future edits
# reasonably quickly; vendor/ is bumped much higher below since those files
# are pinned by version and never change in place.
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 3600


@app.after_request
def _cache_vendor_assets(response):
    if request.path.startswith('/static/vendor/'):
        response.headers['Cache-Control'] = 'public, max-age=2592000, immutable'  # 30 days
    return response

db_url = os.getenv("DATABASE_URL", 'sqlite:///database.db')
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=7)

# 🚀 CONNECTION POOLING (real pooling only applies to server DBs like Postgres;
# SQLite has no concurrent connection pool so we leave it on driver defaults)
if not db_url.startswith("sqlite"):
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        "pool_size": 10,
        "max_overflow": 20,
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    }

db.init_app(app)
migrate = Migrate(app, db, render_as_batch=True)

# SQLite doesn't enforce FK constraints (and therefore ondelete="CASCADE")
# unless explicitly told to per-connection - Postgres enforces them natively.
if db_url.startswith("sqlite"):
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    @event.listens_for(Engine, "connect")
    def _sqlite_enable_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

# 🗜️ GZIP COMPRESSION FOR API/HTML RESPONSES
try:
    from flask_compress import Compress
    app.config['COMPRESS_MIMETYPES'] = [
        'text/html', 'text/css', 'text/xml', 'application/json', 'application/javascript'
    ]
    Compress(app)
except ImportError:
    app.logger.warning("flask-compress not installed; responses will not be gzip-compressed")


# 🧯 CONSISTENT ERROR HANDLING (JSON for /api/*, rendered pages otherwise)
def _wants_json():
    return request.path.startswith('/api/') or request.accept_mimetypes.best == 'application/json'


@app.errorhandler(404)
def handle_404(e):
    if _wants_json():
        return jsonify({"error": "Not found"}), 404
    return render_template('error.html', code=404, message="Page not found"), 404


@app.errorhandler(403)
def handle_403(e):
    if _wants_json():
        return jsonify({"error": "Forbidden"}), 403
    return render_template('error.html', code=403, message="You don't have access to this page"), 403


@app.errorhandler(500)
def handle_500(e):
    app.logger.exception("Unhandled server error")
    if _wants_json():
        return jsonify({"error": "Internal server error"}), 500
    return render_template('error.html', code=500, message="Something went wrong on our end"), 500


# 🩹 SCHEMA SYNC
# Schema changes are tracked as Alembic migrations (see migrations/versions/)
# instead of ad hoc ALTER TABLE patches. This deployment has no separate
# release/migrate step, so the app applies any pending migrations itself on
# startup - a no-op once the DB is already at head. After changing models.py,
# run `flask db migrate -m "..."` to generate the migration and commit it;
# it will be picked up and applied automatically here on next start.
def sync_db_schema():
    if len(sys.argv) > 1 and sys.argv[1] == "db":
        # Being invoked as `flask db ...` (migrate/upgrade/stamp/...) - let
        # that command manage migrations directly instead of racing it.
        return

    with app.app_context():
        try:
            upgrade()
        except Exception as e:
            app.logger.error("MIGRATION ERROR: %s", e)


sync_db_schema()

#  LOGIN MANAGER
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# 🔥 LIVE SENTIMENT (TextBlob polarity analysis) - this is the one and only
# sentiment classifier in the app; every call site (live typing, manual
# entry, CSV import, the submit API, edits) routes through this same
# function via classify_and_log() below, so "always uses the primary
# model" is structural rather than incidental.
POLARITY_POSITIVE = 0.1
POLARITY_NEGATIVE = -0.1
# Below this confidence, the call is close enough to a classification
# boundary that it's worth a human glancing at it - see classify_and_log().
LOW_CONFIDENCE_THRESHOLD = 30.0


def get_sentiment(text):
    """Classify text and return (label, confidence). Confidence is not a
    probability - TextBlob doesn't produce one - it's the distance the
    polarity score sits from the nearest classification boundary (0.1 /
    -0.1), normalized to 0-100. A polarity of 0.35 is a confident
    Positive; a polarity of 0.11 is barely past the boundary and is
    reported as low-confidence even though the label is still "Positive"."""
    if not AI_ENABLED:
        return "Neutral", 0.0

    polarity = TextBlob(text).sentiment.polarity

    if polarity > POLARITY_POSITIVE:
        label = "Positive"
        confidence = min((polarity - POLARITY_POSITIVE) / 0.4, 1.0) * 100
    elif polarity < POLARITY_NEGATIVE:
        label = "Negative"
        confidence = min((abs(polarity) - abs(POLARITY_NEGATIVE)) / 0.4, 1.0) * 100
    else:
        label = "Neutral"
        confidence = min((POLARITY_POSITIVE - abs(polarity)) / POLARITY_POSITIVE, 1.0) * 100

    return label, round(confidence, 1)


# 🔥 EMOTION FUNCTION (same)
def detect_emotion(text):
    text = text.lower()

    if "happy" in text or "good" in text or "great" in text:
        return "Happy"
    elif "sad" in text or "bad" in text or "poor" in text:
        return "Sad"
    elif "angry" in text or "worst" in text or "frustrating" in text:
        return "Angry"
    else:
        return "Neutral"


def classify_and_log(text, user_id):
    """The single entry point every *persisted* feedback row's
    classification should go through - manual entry, CSV import, edits,
    and the submit API all call this instead of get_sentiment/
    detect_emotion directly, so low-confidence calls are logged to
    AuditLog in exactly one place. (The live-typing preview endpoint
    intentionally does NOT route through here - logging every
    in-progress keystroke would flood the audit log with noise from
    half-typed sentences; it calls get_sentiment directly instead.)"""
    sentiment, confidence = get_sentiment(text)
    emotion = detect_emotion(text)

    if confidence < LOW_CONFIDENCE_THRESHOLD:
        db.session.add(AuditLog(
            user_id=user_id,
            action="low_confidence_prediction",
            resource="feedback",
            detail=f"sentiment={sentiment} confidence={confidence} text_len={len(text)}",
        ))

    return sentiment, confidence, emotion


# AI INSIGHTS ENGINE
# Produces a structured, business-facing insight (not just a free-text blob)
# from real sentiment/emotion analysis results, with a safe fallback if the
# LLM call fails or returns something unparseable.
DEFAULT_INSIGHT = {
    "summary": "Not enough feedback yet to generate insights.",
    "pain_points": [],
    "positive_highlights": [],
    "recommendations": [],
    "action_items": [],
    "trend_analysis": "Insufficient data to establish a trend.",
    "predictive_insights": "Collect more feedback to unlock predictions.",
}


def summarize_feedback_stats(feedbacks):
    total = len(feedbacks)
    positive = sum(1 for f in feedbacks if f.sentiment == "Positive")
    negative = sum(1 for f in feedbacks if f.sentiment == "Negative")
    neutral = total - positive - negative
    emotion_counts = Counter(f.emotion for f in feedbacks)
    service_counts = Counter(f.service for f in feedbacks if f.service)
    return {
        "total": total,
        "positive": positive,
        "negative": negative,
        "neutral": neutral,
        "csat": round((positive / total) * 100, 2) if total else 0,
        "emotions": dict(emotion_counts),
        "top_services": dict(service_counts.most_common(5)),
    }


def top_feedback_examples(feedbacks, sentiment, limit=5):
    matches = [f for f in feedbacks if f.sentiment == sentiment and f.text]
    matches.sort(key=lambda f: f.created_at, reverse=True)
    return [
        {"name": f.name or "Anonymous", "service": f.service, "text": f.text}
        for f in matches[:limit]
    ]


def generate_ai_insights(feedbacks):
    """Call the LLM once with aggregated stats + real feedback samples and
    return a structured insight dict. Never raises - always returns a dict
    with every DEFAULT_INSIGHT key populated."""
    if not feedbacks:
        return dict(DEFAULT_INSIGHT)

    stats = summarize_feedback_stats(feedbacks)
    negative_samples = [f.text for f in feedbacks if f.sentiment == "Negative" and f.text][:10]
    positive_samples = [f.text for f in feedbacks if f.sentiment == "Positive" and f.text][:10]
    neutral_samples = [f.text for f in feedbacks if f.sentiment == "Neutral" and f.text][:5]

    prompt = f"""You are a senior customer-experience business analyst.
Analyze this customer feedback dataset and respond with ONLY a single valid JSON object
(no markdown fences, no commentary) with exactly these keys:

"summary": 2-3 sentence executive summary of overall customer sentiment,
"pain_points": array of up to 5 short strings naming the most frequent/severe customer problems,
"positive_highlights": array of up to 5 short strings naming what customers like most,
"recommendations": array of up to 5 concise, actionable business recommendations,
"action_items": array of up to 5 short, concrete next steps a team could act on this week,
"trend_analysis": 1-2 sentences describing how sentiment appears to be trending,
"predictive_insights": 1-2 sentences forecasting likely CX outcomes if nothing changes.

Aggregate stats (JSON): {json.dumps(stats)}
Sample negative feedback: {json.dumps(negative_samples)}
Sample positive feedback: {json.dumps(positive_samples)}
Sample neutral feedback: {json.dumps(neutral_samples)}
"""

    try:
        chat = client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are a professional business analyst AI. Always respond with valid JSON only, matching the requested schema exactly."},
                {"role": "user", "content": prompt},
            ],
            model="llama-3.3-70b-versatile",
            response_format={"type": "json_object"},
            temperature=0.4,
        )

        data = json.loads(chat.choices[0].message.content.strip())

        insight = dict(DEFAULT_INSIGHT)
        for key in insight:
            value = data.get(key)
            if value:
                insight[key] = value
        return insight

    except Exception as e:
        app.logger.error("GROQ INSIGHT ERROR: %s", e)
        fallback = dict(DEFAULT_INSIGHT)
        fallback["summary"] = "AI insight temporarily unavailable - showing live statistics only."
        return fallback


def get_cached_insight(user, scope, count, fetch_feedbacks, force_refresh=False):
    """Return a structured AI insight, regenerating via the LLM only when the
    underlying feedback count changed (or a refresh was explicitly requested).
    `fetch_feedbacks` is only called when we actually need to regenerate, so a
    normal page load that hits the cache never pulls the full feedback table.
    This is what keeps dashboard/report page loads fast - no LLM call (and no
    full-table fetch) on every request."""
    owner_id = None if scope == "all" else user.id

    record = AIInsight.query.filter_by(user_id=owner_id, scope=scope).first()

    if record and not force_refresh and record.feedback_count == count:
        insight = {
            "summary": record.summary,
            "pain_points": record.pain_points or [],
            "positive_highlights": record.positive_highlights or [],
            "recommendations": record.recommendations or [],
            "action_items": record.action_items or [],
            "trend_analysis": record.trend_analysis,
            "predictive_insights": record.predictive_insights,
        }
        insight["generated_at"] = record.generated_at
        return insight

    feedbacks = fetch_feedbacks()

    if not user.ai_enabled:
        insight = dict(DEFAULT_INSIGHT)
        insight["summary"] = "AI insights are disabled in Settings > Preferences."
    else:
        insight = generate_ai_insights(feedbacks)

    if record is None:
        record = AIInsight(user_id=owner_id, scope=scope)
        db.session.add(record)

    record.feedback_count = count
    record.summary = insight["summary"]
    record.pain_points = insight["pain_points"]
    record.positive_highlights = insight["positive_highlights"]
    record.recommendations = insight["recommendations"]
    record.action_items = insight["action_items"]
    record.trend_analysis = insight["trend_analysis"]
    record.predictive_insights = insight["predictive_insights"]
    record.generated_at = utcnow()
    db.session.commit()

    insight["generated_at"] = record.generated_at
    return insight
# 🏠 HOME
@app.route('/')
def home():
    if current_user.is_authenticated:
        return redirect('/dashboard')
    return render_template('landing.html')


# 🔐 REGISTER
import re

def is_strong_password(password):
    return (
        len(password) >= 8 and
        re.search(r"[A-Z]", password) and
        re.search(r"[a-z]", password) and
        re.search(r"[0-9]", password) and
        re.search(r"[!@#$%^&*]", password)
    )


def is_valid_name(name):
    """Letters and spaces only - a real name shouldn't contain digits.
    Also rejects obvious gibberish/keyboard-mash entries: no single letter
    may appear more than 3 times across the whole name, and no word may
    repeat (e.g. "aa aa" or "uigdsjcvahsv"-style mashing)."""
    name = (name or "").strip()
    if not name or not re.fullmatch(r"[A-Za-z ]+", name):
        return False

    letter_counts = Counter(name.lower().replace(" ", ""))
    if any(count > 3 for count in letter_counts.values()):
        return False

    words = name.lower().split()
    if len(words) != len(set(words)):
        return False

    return True


def is_valid_phone(phone):
    """Phone stays optional, but when provided it must be exactly 10
    digits - not arbitrary text like "uigdsjcvahsv"."""
    phone = (phone or "").strip()
    return not phone or bool(re.fullmatch(r"\d{10}", phone))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        email = (request.form.get('email') or '').strip().lower()

        if not username or not password:
            flash("⚠️ All fields required", "error")
            return redirect('/register')

        # 🔐 strong password check
        if not is_strong_password(password):
            flash("❌ Password must be 8+ chars, include A-Z, a-z, 0-9 & special char", "error")
            return redirect('/register')

        # Email is optional (existing accounts predate this field entirely),
        # but if given it has to look like an email and be free - it's what
        # forgot-password looks accounts up by, so silently accepting a
        # duplicate would mean two accounts fighting over the same reset link.
        if email:
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                flash("❌ That doesn't look like a valid email address", "error")
                return redirect('/register')
            if User.query.filter(func.lower(User.email) == email).first():
                flash("❌ That email is already registered to another account", "error")
                return redirect('/register')

        existing = User.query.filter_by(username=username).first()
        if existing:
            flash("❌ User already exists", "error")
            return redirect('/register')

        # 🔐 secure hashing
        hashed_password = generate_password_hash(
            password,
            method='pbkdf2:sha256',
            salt_length=16
        )

        # Every self-registered account starts as a plain user - admin
        # rights are granted afterwards by an existing admin from the Admin
        # panel (see /admin/set_role below), never through the public sign-up
        # form. The old approach took a hardcoded "SECRET123" string typed
        # into a visible, labeled field on the public registration page -
        # anyone could read the page source or just guess it and grant
        # themselves admin on day one.
        user = User(username=username, password=hashed_password, role='user', email=email or None)

        db.session.add(user)
        db.session.commit()

        flash("🎉 Account created successfully! Please login.", "success")
        return redirect('/login')

    return render_template('register.html')

# 🔐 LOGIN
login_attempts = {}

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect('/dashboard')

    error = False

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        ip = request.remote_addr

        if not username or not password:
            flash("⚠️ Fill all fields", "error")
            return redirect('/login')

        #  brute force protection
        if ip in login_attempts and login_attempts[ip] >= 5:
            flash("⚠️ Too many attempts. Try later.", "error")
            return redirect('/login')

        user = User.query.filter_by(username=username).first()

        if not user:
            flash("❌ User not found", "error")
            error = True
            login_attempts[ip] = login_attempts.get(ip, 0) + 1

        elif not check_password_hash(user.password, password):
            flash("❌ Wrong password", "error")
            error = True
            login_attempts[ip] = login_attempts.get(ip, 0) + 1

        else:
            login_user(user, remember=True)
            login_attempts[ip] = 0  
            flash("✅ Login successful", "success")
            return redirect('/dashboard')

    return render_template('login.html', error=error)


RESET_TOKEN_TTL_MINUTES = 60


def send_password_reset_email(user):
    """Issues a fresh token (invalidating any previous one) and emails the
    reset link. Raises on send failure - callers decide how to handle that,
    since the caller needs to keep the response identical whether or not
    the send actually worked (see forgot_password())."""
    token = secrets.token_urlsafe(32)
    user.reset_token = token
    user.reset_token_expires = utcnow() + timedelta(minutes=RESET_TOKEN_TTL_MINUTES)
    db.session.commit()

    reset_url = url_for('reset_password', token=token, _external=True)
    msg = Message(
        subject="Reset your PulseCX password",
        recipients=[user.email],
        body=(
            f"Hi {user.username},\n\n"
            f"Someone requested a password reset for your PulseCX account. "
            f"If this was you, click the link below to set a new password. "
            f"This link expires in {RESET_TOKEN_TTL_MINUTES} minutes.\n\n"
            f"{reset_url}\n\n"
            f"If you didn't request this, you can safely ignore this email - "
            f"your password won't change unless you click the link above."
        ),
    )
    mail.send(msg)


@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect('/dashboard')

    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()

        if email:
            user = User.query.filter(func.lower(User.email) == email).first()
            if user:
                if not MAIL_CONFIGURED:
                    app.logger.error(
                        "Password reset requested for %s but mail is not configured "
                        "(MAIL_USERNAME/MAIL_PASSWORD unset)", user.username
                    )
                else:
                    try:
                        send_password_reset_email(user)
                    except Exception as e:
                        app.logger.error("Failed to send password reset email: %s", e)

        # Identical response whether or not the email matched an account,
        # sending succeeded, or mail is even configured - otherwise this
        # endpoint becomes a way to enumerate which emails have accounts.
        flash("📧 If that email is on file, a password reset link has been sent.", "success")
        return redirect('/login')

    return render_template('forgot_password.html')


def _is_future(dt):
    """SQLite doesn't reliably round-trip tzinfo through SQLAlchemy's
    DateTime(timezone=True) - a value stored as UTC-aware can come back
    naive on read, which crashes a direct comparison against utcnow()'s
    aware value. Treat a naive read as UTC (that's the only thing this
    column is ever written as) instead of raising."""
    if dt is None:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt > utcnow()


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect('/dashboard')

    user = User.query.filter_by(reset_token=token).first()
    valid = user and _is_future(user.reset_token_expires)

    if not valid:
        flash("❌ This password reset link is invalid or has expired", "error")
        return redirect('/forgot-password')

    if request.method == 'POST':
        password = request.form.get('password')
        if not password or not is_strong_password(password):
            flash("❌ Password must be 8+ chars, include A-Z, a-z, 0-9 & special char", "error")
            return redirect(f'/reset-password/{token}')

        user.password = generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)
        user.reset_token = None
        user.reset_token_expires = None
        db.session.commit()

        flash("✅ Password reset - please log in with your new password", "success")
        return redirect('/login')

    return render_template('reset_password.html', token=token)


def _owns_or_admin(feedback):
    if feedback.user_id != current_user.id and current_user.role != 'admin':
        abort(403)


@app.route('/delete/<int:id>', methods=['POST'])
@login_required
def delete(id):
    feedback = Feedback.query.get_or_404(id)
    _owns_or_admin(feedback)

    db.session.delete(feedback)
    db.session.commit()
    flash("🗑 Record deleted", "success")

    return redirect('/customers')

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit(id):
    feedback = Feedback.query.get_or_404(id)
    _owns_or_admin(feedback)

    if request.method == 'POST':
        text = (request.form.get('text') or '').strip()
        name = (request.form.get('name') or '').strip()
        phone = (request.form.get('phone') or '').strip()

        if not text:
            flash("❌ Feedback text is required", "error")
            return redirect(f'/edit/{id}')
        if name and not is_valid_name(name):
            flash("❌ Name must be letters only - no numbers, and no repeated words or excessive repeated letters", "error")
            return redirect(f'/edit/{id}')
        if not is_valid_phone(phone):
            flash("❌ Phone must be exactly 10 digits", "error")
            return redirect(f'/edit/{id}')

        feedback.name = name or 'Anonymous'
        feedback.phone = phone
        feedback.service = request.form.get('service') or 'General'
        feedback.text = text
        # Re-run analysis so sentiment/emotion stay consistent with the edited text
        feedback.sentiment, feedback.sentiment_score, feedback.emotion = classify_and_log(text, current_user.id)

        db.session.commit()
        flash("✅ Record updated successfully", "success")
        return redirect('/customers')

    return render_template('edit.html', feedback=feedback)

def _dashboard_scope():
    """Resolve the current request's data scope: ('all', unfiltered query) for
    an admin explicitly asking for it, otherwise ('my', own-records query)."""
    view = request.args.get('view', 'my')
    if view == 'all' and current_user.role == 'admin':
        return 'all', view, Feedback.query
    return 'my', view, Feedback.query.filter_by(user_id=current_user.id)


def _import_csv_rows(file_storage):
    """Parse + insert an uploaded CSV of feedback rows. Returns (added, skipped)."""
    try:
        content = file_storage.stream.read().decode("UTF-8")
    except UnicodeDecodeError:
        return 0, 0, "encoding"

    reader = csv.DictReader(content.splitlines())
    if not reader.fieldnames or 'feedback' not in reader.fieldnames:
        return 0, 0, "header"

    added, skipped = 0, 0
    for row in reader:
        if added >= MAX_CSV_ROWS:
            skipped += 1
            continue
        text = (row.get('feedback') or '').strip()
        if not text:
            skipped += 1
            continue
        try:
            # Bulk data is messier than a single manual entry, so invalid
            # name/phone here fall back to "unknown" rather than skipping
            # the whole row - the feedback text is the valuable part, and
            # CSV import already treats a blank name the same way.
            csv_name = (row.get('name') or '').strip()
            name = csv_name if is_valid_name(csv_name) else 'Anonymous'
            csv_phone = (row.get('phone') or '').strip()
            phone = csv_phone if is_valid_phone(csv_phone) else None

            sentiment, confidence, emotion = classify_and_log(text, current_user.id)
            fb = Feedback(
                name=name,
                phone=phone,
                service=(row.get('service') or 'General').strip() or 'General',
                text=text,
                sentiment=sentiment,
                sentiment_score=confidence,
                emotion=emotion,
                user_id=current_user.id
            )
            db.session.add(fb)
            added += 1
        except Exception as e:
            app.logger.warning("CSV row skipped: %s", e)
            skipped += 1

    db.session.commit()
    return added, skipped, None


# 📊 DASHBOARD
@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():

    if request.method == 'POST' and 'file' in request.files and request.files['file'].filename:
        file = request.files['file']

        if not file.filename.lower().endswith('.csv'):
            flash("❌ Please upload a .csv file", "error")
            return redirect('/dashboard')

        added, skipped, error = _import_csv_rows(file)
        if error == "encoding":
            flash("❌ Could not read file - please upload a UTF-8 encoded CSV", "error")
        elif error == "header" or added == 0:
            flash("⚠️ No valid rows found - CSV needs a 'feedback' column", "error")
        else:
            msg = f"✅ Imported {added} feedback row(s)"
            if skipped:
                msg += f" ({skipped} skipped)"
            flash(msg, "success")
        return redirect('/dashboard')

    if request.method == 'POST':
        text = (request.form.get('feedback') or '').strip()
        name = (request.form.get('name') or '').strip()
        phone = (request.form.get('phone') or '').strip()

        if name and not is_valid_name(name):
            flash("❌ Name must be letters only - no numbers, and no repeated words or excessive repeated letters", "error")
            return redirect('/dashboard')
        if not is_valid_phone(phone):
            flash("❌ Phone must be exactly 10 digits", "error")
            return redirect('/dashboard')

        if text:
            sentiment, confidence, emotion = classify_and_log(text, current_user.id)
            fb = Feedback(
                name=name or 'Anonymous',
                phone=phone,
                service=(request.form.get('service') or 'General').strip() or 'General',
                text=text,
                sentiment=sentiment,
                sentiment_score=confidence,
                emotion=emotion,
                user_id=current_user.id
            )
            db.session.add(fb)
            db.session.commit()
            flash("✅ Feedback analyzed & saved successfully", "success")
        return redirect('/dashboard')

    scope, view, base_query = _dashboard_scope()
    count = base_query.count()
    insight = get_cached_insight(current_user, scope, count, fetch_feedbacks=base_query.all)

    return render_template('dashboard.html', view=view, insight=insight)


#  LIVE SENTIMENT
@app.route('/live_sentiment', methods=['POST'])
@csrf.exempt 
@login_required
def live_sentiment():
    data = request.get_json(silent=True)
    text = data.get('text') if data else None

    if not text:
        return jsonify({"error": "No text provided"}), 400

    # Live-typing preview only - deliberately calls get_sentiment directly
    # rather than classify_and_log, so partial/in-progress sentences don't
    # spam the low-confidence audit log (see classify_and_log's docstring).
    # Still the same primary model as everywhere else, just not logged here.
    sentiment, confidence = get_sentiment(text)
    emotion = detect_emotion(text)

    return jsonify({
        "sentiment": sentiment,
        "confidence": confidence,
        "emotion": emotion
    })

@app.route('/api/submit_feedback', methods=['POST'])
@csrf.exempt
@login_required
def submit_feedback():
    data = request.get_json(silent=True)
    if not data or not data.get('text'):
        return jsonify({"error": "No text"}), 400
        
    text = data.get('text')
    name = (data.get('name') or '').strip()
    phone = (data.get('phone') or '').strip()
    service = data.get('service', '')

    if name and not is_valid_name(name):
        return jsonify({"error": "Name must be letters only - no numbers, and no repeated words or excessive repeated letters"}), 400
    if not is_valid_phone(phone):
        return jsonify({"error": "Phone must be exactly 10 digits"}), 400

    sentiment, confidence, emotion = classify_and_log(text, current_user.id)

    fb = Feedback(
        name=name or 'Anonymous', phone=phone, service=service, text=text,
        sentiment=sentiment, sentiment_score=confidence, emotion=emotion, user_id=current_user.id
    )
    db.session.add(fb)
    db.session.commit()

    return jsonify({"success": True})

@app.route('/api/dashboard_data')
@login_required
def dashboard_data():
    scope, _, base_query = _dashboard_scope()

    total = base_query.count()

    sentiment_counts = dict(
        base_query.with_entities(Feedback.sentiment, func.count(Feedback.id))
        .group_by(Feedback.sentiment).all()
    )
    positive = sentiment_counts.get("Positive", 0)
    negative = sentiment_counts.get("Negative", 0)
    neutral = total - positive - negative

    positive_percent = round((positive / total) * 100, 2) if total > 0 else 0

    emotion_counts = dict(
        base_query.with_entities(Feedback.emotion, func.count(Feedback.id))
        .group_by(Feedback.emotion).all()
    )
    top_emotion = max(emotion_counts, key=emotion_counts.get) if emotion_counts else "None"

    # Bounded trend window - only pull the sentiment column, not full rows
    trend_rows = (
        base_query.order_by(Feedback.created_at.desc())
        .with_entities(Feedback.sentiment)
        .limit(TREND_WINDOW)
        .all()
    )
    trend_rows.reverse()
    data_values = [1 if s == "Positive" else 0 if s == "Negative" else 0.5 for (s,) in trend_rows]
    labels = list(range(1, len(data_values) + 1))

    owner_key = None if scope == "all" else current_user.id
    accuracy, precision, recall = get_cached_evaluation(owner_key, scope, total, base_query)

    recent = base_query.order_by(Feedback.created_at.desc()).limit(10).all()
    recent_feedbacks = [
        {"name": f.name, "phone": f.phone, "service": f.service, "text": f.text,
         "sentiment": f.sentiment, "confidence": f.sentiment_score, "emotion": f.emotion} for f in recent
    ]

    return jsonify({
        "total": total,
        "positive": positive,
        "negative": negative,
        "neutral": neutral,
        "positive_percent": positive_percent,
        "top_emotion": top_emotion,
        "labels": labels,
        "data_values": data_values,
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "recent_feedbacks": recent_feedbacks
    })

#  ADMIN
@app.route('/admin')
@login_required
def admin():
    if current_user.role != 'admin':
        abort(403)

    page = request.args.get('page', 1, type=int)
    users = User.query.order_by(User.username).all()
    feedbacks = Feedback.query.order_by(Feedback.created_at.desc()).paginate(page=page, per_page=20)

    # Real site-wide counts via SQL, not len(feedbacks)/selectattr over the
    # current page's 20 rows - .paginate() only holds one page of items, so
    # those would have silently under-counted everything past page 1.
    total_feedback = Feedback.query.count()
    total_positive = Feedback.query.filter_by(sentiment="Positive").count()

    return render_template(
        'admin.html',
        users=users,
        feedbacks=feedbacks,
        total_users=len(users),
        total_feedback=total_feedback,
        total_positive=total_positive,
    )

@app.route('/delete_feedback/<int:id>', methods=['POST'])
@login_required
def delete_feedback(id):
    if current_user.role != 'admin':
        abort(403)

    feedback = Feedback.query.get_or_404(id)
    db.session.delete(feedback)
    db.session.commit()
    flash("🗑 Feedback deleted", "success")

    return redirect('/admin')


@app.route('/admin/set_role/<int:user_id>', methods=['POST'])
@login_required
def set_role(user_id):
    """The only way to grant/revoke admin now - an existing admin acting on
    another user from the Admin panel. Replaces the old public sign-up
    "admin code" field, which let anyone self-promote."""
    if current_user.role != 'admin':
        abort(403)

    target = User.query.get_or_404(user_id)
    new_role = request.form.get('role')
    if new_role not in ('admin', 'user'):
        abort(400)

    if target.id == current_user.id:
        flash("❌ You can't change your own role", "error")
        return redirect('/admin')

    if target.role == 'admin' and new_role == 'user' and User.query.filter_by(role='admin').count() <= 1:
        flash("❌ Can't remove the last remaining admin", "error")
        return redirect('/admin')

    target.role = new_role
    db.session.commit()
    flash(f"✅ {target.username} is now {'an admin' if new_role == 'admin' else 'a regular user'}", "success")
    return redirect('/admin')


def build_report_context(feedbacks, insight):
    """Single source of truth for report data - used by both the on-screen
    Reports page and the downloaded PDF, so they never drift apart."""
    stats = summarize_feedback_stats(feedbacks)
    return {
        **stats,
        "insight": insight,
        "top_issues": top_feedback_examples(feedbacks, "Negative", limit=5),
        "top_positive": top_feedback_examples(feedbacks, "Positive", limit=5),
    }


def render_sentiment_chart_base64(positive, negative, neutral):
    """Render the sentiment donut chart to an in-memory PNG (base64) instead
    of a shared file on disk, so concurrent requests/users can't clobber each
    other's chart image."""
    import base64
    from io import BytesIO
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    total = positive + negative + neutral
    fig = plt.figure(figsize=(4.5, 4.5))
    plt.pie(
        [positive, negative, neutral] if total else [1],
        labels=['Positive', 'Negative', 'Neutral'] if total else ['No data'],
        autopct='%1.1f%%' if total else None,
        # Brand palette (--success/--danger/--warning) so the PDF's chart
        # matches the in-app dashboard/analytics/reports charts exactly.
        colors=['#00D084', '#ef4444', '#f59e0b'] if total else ['#334155'],
        wedgeprops={'width': 0.4}
    )
    plt.text(0, 0, f"{total}\nTotal", ha='center', va='center', fontsize=14)

    buf = BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', transparent=True)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode('ascii')


@app.route('/download_report')
@login_required
def download_report():
    from flask import send_file
    from io import BytesIO
    from datetime import datetime
    from xhtml2pdf import pisa

    scope, _, base_query = _dashboard_scope()
    feedbacks = base_query.all()
    count = len(feedbacks)

    insight = get_cached_insight(current_user, scope, count, fetch_feedbacks=lambda: feedbacks)
    ctx = build_report_context(feedbacks, insight)
    chart_b64 = render_sentiment_chart_base64(ctx["positive"], ctx["negative"], ctx["neutral"])

    html = render_template(
        'report_pdf.html',
        date=datetime.now().strftime("%B %d, %Y"),
        chart_b64=chart_b64,
        **ctx
    )

    pdf_buffer = BytesIO()
    result = pisa.CreatePDF(html, dest=pdf_buffer)
    if result.err:
        app.logger.error("PDF generation failed with %s error(s)", result.err)
        flash("❌ Could not generate PDF report", "error")
        return redirect('/reports')

    pdf_buffer.seek(0)
    filename = f"pulsecx-report-{datetime.now().strftime('%Y%m%d')}.pdf"
    return send_file(pdf_buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')


def _analytics_scope():
    if current_user.role == 'admin':
        return Feedback.query
    return Feedback.query.filter_by(user_id=current_user.id)


def compute_analytics(base_query):
    """SQL-aggregated analytics (COUNT/GROUP BY) instead of pulling every row
    into Python - shared by the page render and the 30s polling endpoint."""
    total = base_query.count()

    sentiment_counts = dict(
        base_query.with_entities(Feedback.sentiment, func.count(Feedback.id))
        .group_by(Feedback.sentiment).all()
    )
    positive = sentiment_counts.get("Positive", 0)
    negative = sentiment_counts.get("Negative", 0)
    neutral = sentiment_counts.get("Neutral", 0)

    emotions = dict(
        base_query.with_entities(Feedback.emotion, func.count(Feedback.id))
        .group_by(Feedback.emotion).all()
    )
    services = dict(
        base_query.filter(Feedback.service.isnot(None))
        .with_entities(Feedback.service, func.count(Feedback.id))
        .group_by(Feedback.service).all()
    )

    # Bounded window so the "All" trend option has real data to show instead
    # of silently duplicating "Last 10".
    trend_rows = (
        base_query.order_by(Feedback.created_at.desc())
        .with_entities(Feedback.sentiment)
        .limit(TREND_WINDOW)
        .all()
    )
    trend_rows.reverse()
    trend = [1 if s == "Positive" else 0 if s == "Negative" else 0.5 for (s,) in trend_rows]

    score = round((positive / total) * 100, 2) if total > 0 else 0

    return {
        "positive": positive,
        "negative": negative,
        "neutral": neutral,
        "total": total,
        "emotions": emotions,
        "services": services,
        "trend": trend,
        "score": score,
    }


# 📈 ANALYTICS
@app.route('/analytics')
@login_required
def analytics():
    data = compute_analytics(_analytics_scope())
    return render_template('analytics.html', **data)


@app.route('/api/analytics_data')
@login_required
def analytics_data():
    return jsonify(compute_analytics(_analytics_scope()))


# 👥 CUSTOMERS
@app.route('/customers')
@login_required
def customers():
    search = request.args.get('search', '').strip()
    sentiment = request.args.get('sentiment', '').strip()
    service = request.args.get('service', '').strip()
    page = request.args.get('page', 1, type=int)

    owned = Feedback.query.filter_by(user_id=current_user.id)

    query = owned
    if search:
        query = query.filter(
            Feedback.name.contains(search) | Feedback.service.contains(search)
        )
    if sentiment:
        query = query.filter(Feedback.sentiment == sentiment)
    if service:
        query = query.filter(Feedback.service == service)

    feedbacks = query.order_by(Feedback.created_at.desc()).paginate(page=page, per_page=10)

    sentiment_counts = dict(
        owned.with_entities(Feedback.sentiment, func.count(Feedback.id)).group_by(Feedback.sentiment).all()
    )
    service_options = [
        row[0] for row in
        owned.filter(Feedback.service.isnot(None))
        .with_entities(Feedback.service).distinct().order_by(Feedback.service).all()
    ]

    return render_template(
        'customers.html',
        feedbacks=feedbacks,
        positive=sentiment_counts.get("Positive", 0),
        negative=sentiment_counts.get("Negative", 0),
        neutral=sentiment_counts.get("Neutral", 0),
        service_options=service_options,
        search=search,
        selected_sentiment=sentiment,
        selected_service=service,
    )


@app.route('/reports')
@login_required
def reports():
    scope, _, base_query = _dashboard_scope()
    feedbacks = base_query.all()
    count = len(feedbacks)

    insight = get_cached_insight(current_user, scope, count, fetch_feedbacks=lambda: feedbacks)
    ctx = build_report_context(feedbacks, insight)

    return render_template('reports.html', **ctx)


@app.route('/refresh_ai')
@login_required
def refresh_ai():
    scope, _, base_query = _dashboard_scope()
    feedbacks = base_query.all()
    get_cached_insight(current_user, scope, len(feedbacks), fetch_feedbacks=lambda: feedbacks, force_refresh=True)
    flash("🔄 AI insights regenerated", "success")
    return redirect(request.referrer or '/reports')

# 📄 ABOUT PAGE
@app.route('/about')
@login_required
def about():
    return render_template('about.html')


# ⚙️ SETTINGS PAGE
@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():

    user = current_user

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password')
        old_password = request.form.get('old_password')

        username_changing = username and username != user.username
        if username_changing or password:
            if not old_password or not check_password_hash(user.password, old_password):
                flash("❌ Wrong current password", "error")
                return redirect('/settings')

        if username_changing:
            existing = User.query.filter_by(username=username).first()
            if existing:
                flash("❌ Username already taken", "error")
                return redirect('/settings')
            user.username = username

        email = (request.form.get('email') or '').strip().lower()
        if email:
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                flash("❌ That doesn't look like a valid email address", "error")
                return redirect('/settings')
            existing_email = User.query.filter(func.lower(User.email) == email, User.id != user.id).first()
            if existing_email:
                flash("❌ That email is already registered to another account", "error")
                return redirect('/settings')
        user.email = email or None

        if password:
            if not is_strong_password(password):
                flash("❌ Password must be 8+ chars, include A-Z, a-z, 0-9 & special char", "error")
                return redirect('/settings')

            user.password = generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)

        user.email_notify = 'email_notify' in request.form
        user.ai_enabled = 'ai_enabled' in request.form

        db.session.commit()

        flash("✅ Settings updated successfully", "success")
        return redirect('/settings')

    # Only needed for the GET render below - was previously computed
    # unconditionally, running 2 COUNT queries on every POST too even
    # though the POST branch always redirects before using them.
    total = Feedback.query.filter_by(user_id=user.id).count()
    positive = Feedback.query.filter_by(user_id=user.id, sentiment="Positive").count()
    ai_score = int((positive / total) * 100) if total > 0 else 0

    return render_template(
        'settings.html',
        ai_score=ai_score
    )


@app.route('/upload_avatar', methods=['POST'])
@login_required
def upload_avatar():
    file = request.files.get('avatar')

    if not file or not file.filename:
        flash("❌ No file selected", "error")
        return redirect('/settings')

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in ALLOWED_AVATAR_EXTENSIONS:
        flash("❌ Avatar must be a PNG, JPG or WEBP image", "error")
        return redirect('/settings')

    avatars_dir = os.path.join(app.root_path, 'static', 'avatars')
    os.makedirs(avatars_dir, exist_ok=True)

    old_avatar = current_user.avatar
    filename = secure_filename(f"user{current_user.id}_{uuid.uuid4().hex[:8]}.{ext}")
    file.save(os.path.join(avatars_dir, filename))

    current_user.avatar = filename
    db.session.commit()

    if old_avatar:
        old_path = os.path.join(avatars_dir, old_avatar)
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except OSError as e:
                app.logger.warning("Could not remove old avatar %s: %s", old_avatar, e)

    flash("✅ Avatar updated", "success")
    return redirect('/settings')
# 🗑 ACCOUNT DELETION
@app.route('/delete_account', methods=['POST'])
@login_required
def delete_account():
    user = current_user

    # delete all user data
    Feedback.query.filter_by(user_id=user.id).delete()

    # delete user
    db.session.delete(user)
    db.session.commit()

    logout_user()

    flash("🗑 Account deleted successfully", "success")
    return redirect('/login')

@app.route('/export_csv')
@login_required
def export_csv():
    feedbacks = Feedback.query.filter_by(user_id=current_user.id).all()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(['Name', 'Phone', 'Service', 'Feedback', 'Sentiment'])

    for f in feedbacks:
        writer.writerow([f.name, f.phone, f.service, f.text, f.sentiment])

    output.seek(0)

    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=feedback_data.csv"}
    )

# 🧹 CLEAR ALL FEEDBACK DATA
@app.route('/clear_data', methods=['POST'])
@login_required
def clear_data():
    Feedback.query.filter_by(user_id=current_user.id).delete()
    db.session.commit()

    flash("🧹 All feedback data cleared", "success")
    return redirect('/settings')


# 🚪 LOGOUT
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
        # Without this the dev server handles ONE request at a time - every
        # authenticated page needs ~8 resources (HTML, style.css, 3 vendor
        # JS bundles, 3 app JS files, fonts), so the browser's parallel
        # fetches were getting queued and served one-by-one instead, on
        # every single page. Public pages (login/landing) load far fewer
        # resources, which is exactly why only post-login pages felt slow.
        threaded=True
    )
