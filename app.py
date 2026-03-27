from flask import Flask, render_template, redirect, request, abort, flash, url_for, jsonify
from models import db, User, Feedback
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from textblob import TextBlob
from datetime import timedelta
import csv
import secrets
import os
from dotenv import load_dotenv
from groq import Groq
load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# 🤖 OPTIONAL AI MODEL (safe fallback)
try:
    from transformers import pipeline
    ai_model = pipeline("sentiment-analysis")
    AI_ENABLED = True
except:
    AI_ENABLED = False

app = Flask(__name__)

# 🔐 CONFIG
app.config['SECRET_KEY'] = 'secret123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=7)

db.init_app(app)

# 🔐 LOGIN MANAGER
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# 🔐 RESET TOKEN STORAGE
reset_tokens = {}


# 🔥 HYBRID SENTIMENT
def get_sentiment(text):
    if AI_ENABLED:
        try:
            result = ai_model(text[:512])[0]
            label = result['label']
            if label == "POSITIVE":
                return "Positive"
            elif label == "NEGATIVE":
                return "Negative"
        except:
            pass

    analysis = TextBlob(text)
    polarity = analysis.sentiment.polarity

    if polarity > 0.1:
        return "Positive"
    elif polarity < -0.1:
        return "Negative"
    else:
        return "Neutral"


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


# 🤖 🔥 REAL AI INSIGHT (OPENAI + FALLBACK)
def generate_insight(feedbacks):
    if not feedbacks:
        return "No feedback available."

    # Extract text
    texts = [f.text for f in feedbacks if f.text]
    combined_text = " ".join(texts[:15])

    if not combined_text.strip():
        return "No valid feedback text"

    try:
        chat = client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": "You are a professional business analyst AI."
                },
                {
                    "role": "user",
                    "content": f"""
Analyze these customer feedbacks and respond STRICTLY in this format:

Summary:
- Write 2-3 lines summary

Problems:
- List key problems
- Keep it short

Suggestions:
- Give actionable suggestions
- Keep it practical

Feedback:
{combined_text}
"""
                }
            ],
            model="llama-3.3-70b-versatile"
        )

        result = chat.choices[0].message.content.strip()

        return result

    except Exception as e:
        print("🔥 GROQ ERROR:", e)
        return """
Summary:
- AI insight unavailable

Problems:
- Could not analyze feedback

Suggestions:
- Please try again later
"""
# 🏠 HOME
@app.route('/')
def home():
    return redirect('/login')


# 🔐 REGISTER
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            flash("⚠️ All fields required", "error")
            return redirect('/register')

        if len(password) < 4:
            flash("⚠️ Password too short", "error")
            return redirect('/register')

        existing = User.query.filter_by(username=username).first()
        if existing:
            flash("❌ User already exists", "error")
            return redirect('/register')

        hashed_password = generate_password_hash(password)

        role = 'admin' if User.query.count() == 0 else 'user'

        user = User(username=username, password=hashed_password, role=role)

        db.session.add(user)
        db.session.commit()

        flash("🎉 Account created successfully! Please login.", "success")
        return redirect('/login')

    return render_template('register.html')


# 🔐 LOGIN
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect('/dashboard')

    error = False

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            flash("⚠️ Fill all fields", "error")
            return redirect('/login')

        user = User.query.filter_by(username=username).first()

        if not user:
            flash("❌ User not found", "error")
            error = True

        elif not check_password_hash(user.password, password):
            flash("❌ Wrong password", "error")
            error = True

        else:
            login_user(user, remember=True)
            flash("✅ Login successful", "success")
            return redirect('/dashboard')

    return render_template('login.html', error=error)


# 📊 DASHBOARD
@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():

    if request.method == 'POST' and 'file' in request.files:
        file = request.files['file']

        if file and file.filename.endswith('.csv'):
            reader = csv.DictReader(file.stream.read().decode("UTF-8").splitlines())

            for row in reader:
                text = row.get('feedback', '')

                sentiment = get_sentiment(text)
                emotion = detect_emotion(text)

                fb = Feedback(
                    name=row.get('name'),
                    phone=row.get('phone'),
                    service=row.get('service'),
                    text=text,
                    sentiment=sentiment,
                    emotion=emotion,
                    user_id=current_user.id
                )

                db.session.add(fb)

            db.session.commit()

    elif request.method == 'POST':
        text = request.form.get('feedback')

        if text:
            sentiment = get_sentiment(text)
            emotion = detect_emotion(text)

            fb = Feedback(
                name=request.form.get('name'),
                phone=request.form.get('phone'),
                service=request.form.get('service'),
                text=text,
                sentiment=sentiment,
                emotion=emotion,
                user_id=current_user.id
            )

            db.session.add(fb)
            db.session.commit()

    feedbacks = Feedback.query.filter_by(user_id=current_user.id).all()

    total = len(feedbacks)
    positive = sum(1 for f in feedbacks if f.sentiment == "Positive")
    negative = sum(1 for f in feedbacks if f.sentiment == "Negative")

    positive_percent = round((positive / total) * 100, 2) if total > 0 else 0

    labels = list(range(1, total + 1))
    data_values = [1 if f.sentiment == "Positive" else 0 if f.sentiment == "Negative" else 0.5 for f in feedbacks]

    alert = "⚠️ High negative feedback!" if negative > positive else None

    # 🔥 NEW AI INSIGHT
    insight = generate_insight(feedbacks)

    return render_template(
        'dashboard.html',
        feedbacks=feedbacks,
        total=total,
        positive=positive,
        negative=negative,
        positive_percent=positive_percent,
        labels=labels,
        data_values=data_values,
        alert=alert,
        insight=insight
    )


# ⚡ LIVE SENTIMENT
@app.route('/live_sentiment', methods=['POST'])
@login_required
def live_sentiment():
    text = request.json.get('text')
    return jsonify({"sentiment": get_sentiment(text)})


# 👑 ADMIN
@app.route('/admin')
@login_required
def admin():
    if current_user.role != 'admin':
        abort(403)

    users = User.query.all()
    return render_template('admin.html', users=users)


# 📈 ANALYTICS
@app.route('/analytics')
@login_required
def analytics():

    if current_user.role == 'admin':
        feedbacks = Feedback.query.all()
    else:
        feedbacks = Feedback.query.filter_by(user_id=current_user.id).all()

    positive = sum(1 for f in feedbacks if f.sentiment == "Positive")
    negative = sum(1 for f in feedbacks if f.sentiment == "Negative")
    neutral = sum(1 for f in feedbacks if f.sentiment == "Neutral")

    return render_template('analytics.html', positive=positive, negative=negative, neutral=neutral)


# 👥 CUSTOMERS
@app.route('/customers')
@login_required
def customers():
    search = request.args.get('search')
    page = request.args.get('page', 1, type=int)

    query = Feedback.query.filter_by(user_id=current_user.id)

    if search and search.strip() != "":
        query = query.filter(
            Feedback.name.contains(search) |
            Feedback.service.contains(search)
        )

    feedbacks = query.order_by(Feedback.id.desc()).paginate(page=page, per_page=5)

    return render_template('customers.html', feedbacks=feedbacks)
# report
@app.route('/reports')
@login_required
def reports():
    feedbacks = Feedback.query.filter_by(user_id=current_user.id).all()

    # Generate AI insight (already written in your code)
    insight = generate_insight(feedbacks)

    return render_template('reports.html', insight=insight)

from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from flask import send_file
import io

@app.route('/download_report')
@login_required
def download_report():
    feedbacks = Feedback.query.filter_by(user_id=current_user.id).all()
    insight = generate_insight(feedbacks)

    # ✅ Create PDF in memory (NO FILE SAVE)
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(buffer)
    styles = getSampleStyleSheet()

    content = []

    content.append(Paragraph("📊 AI Customer Feedback Report", styles['Title']))
    content.append(Spacer(1, 20))

    for line in insight.split("\n"):
        content.append(Paragraph(line, styles['Normal']))
        content.append(Spacer(1, 10))

    doc.build(content)

    buffer.seek(0)

    return send_file(buffer, as_attachment=True, download_name="AI_Report.pdf", mimetype='application/pdf')

# 🚪 LOGOUT
@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/login')


if __name__ == '__main__':
    with app.app_context():
        db.create_all()

    app.run(debug=True)