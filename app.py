from flask import Flask, render_template, redirect, request, abort, flash, url_for, jsonify
from sympy import content
from models import db, User, Feedback
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from textblob import TextBlob
from datetime import timedelta
import csv
from flask import Response
import io
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
import re

def is_strong_password(password):
    return (
        len(password) >= 8 and
        re.search(r"[A-Z]", password) and
        re.search(r"[a-z]", password) and
        re.search(r"[0-9]", password) and
        re.search(r"[!@#$%^&*]", password)
    )

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not username or not password:
            flash("⚠️ All fields required", "error")
            return redirect('/register')

        # 🔐 strong password check
        if not is_strong_password(password):
            flash("❌ Password must be 8+ chars, include A-Z, a-z, 0-9 & special char", "error")
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

        role = 'admin' if User.query.count() == 0 else 'user'

        user = User(username=username, password=hashed_password, role=role)

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

        # 🔐 brute force protection
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
            login_attempts[ip] = 0  # reset on success
            flash("✅ Login successful", "success")
            return redirect('/dashboard')

    return render_template('login.html', error=error)


# 📊 DASHBOARD
@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
   
    view = request.args.get('view', 'my')
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

    if view == 'all' and current_user.role == 'admin':
       feedbacks = Feedback.query.all()
    else:
       feedbacks = Feedback.query.filter_by(user_id=current_user.id).all()

    total = len(feedbacks)
    positive = sum(1 for f in feedbacks if f.sentiment == "Positive")
    negative = sum(1 for f in feedbacks if f.sentiment == "Negative")

    positive_percent = round((positive / total) * 100, 2) if total > 0 else 0

    labels = list(range(1, total + 1))
    data_values = [1 if f.sentiment == "Positive" else 0 if f.sentiment == "Negative" else 0.5 for f in feedbacks]

    alert = "⚠️ High negative feedback!" if negative > positive else None

    # 🧠 Emotion Analysis
    from collections import Counter
    emotion_count = Counter(f.emotion for f in feedbacks)
    top_emotion = emotion_count.most_common(1)[0][0] if emotion_count else "None"

    # 🔥 NEW AI INSIGHT
    if current_user.ai_enabled:
         insight = generate_insight(feedbacks)
    else:
         insight = "⚠️ AI Insights Disabled by user"

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
        insight=insight,
        view=view,
        top_emotion=top_emotion
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

from flask import send_file
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
import matplotlib.pyplot as plt

@app.route('/download_report')
@login_required
def download_report():

    from flask import session

    feedbacks = Feedback.query.filter_by(user_id=current_user.id).all()

    total = len(feedbacks)
    positive = sum(1 for f in feedbacks if f.sentiment == "Positive")
    negative = sum(1 for f in feedbacks if f.sentiment == "Negative")
    neutral = total - (positive + negative)

    ai_summary = session.get("ai_summary", "No summary available")
    ai_problems = session.get("ai_problems", [])
    ai_suggestions = session.get("ai_suggestions", [])

    labels = ['Positive', 'Negative', 'Neutral']
    values = [positive, negative, neutral]

    chart_path = "chart.png"

    plt.figure()
    plt.pie(values, labels=labels, autopct='%1.1f%%')
    plt.title("Sentiment Distribution")
    plt.savefig(chart_path)
    plt.close()

    pdf_path = "report.pdf"
    doc = SimpleDocTemplate(pdf_path)

    styles = getSampleStyleSheet()
    content = []

    content.append(Paragraph("CX ANALYTICS REPORT", styles['Title']))
    content.append(Spacer(1, 20))

    content.append(Paragraph(f"Total Feedback: {total}", styles['Normal']))
    content.append(Paragraph(f"Positive: {positive}", styles['Normal']))
    content.append(Paragraph(f"Negative: {negative}", styles['Normal']))
    content.append(Paragraph(f"Neutral: {neutral}", styles['Normal']))

    content.append(Spacer(1, 20))

    table_data = [
        ["Type", "Count"],
        ["Positive", positive],
        ["Negative", negative],
        ["Neutral", neutral]
    ]

    table = Table(table_data, colWidths=[200, 100])

    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.grey),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('BACKGROUND', (0,1), (-1,-1), colors.beige),
    ]))

    content.append(table)
    content.append(Spacer(1, 20))

    content.append(Paragraph("Sentiment Distribution", styles['Heading2']))
    content.append(Spacer(1, 10))
    content.append(Image(chart_path, width=350, height=250))

    content.append(Spacer(1, 25))

    if positive > negative:
        insight = "Customers are mostly satisfied 😊"
    elif negative > positive:
        insight = "Negative feedback is higher ⚠️ Improve service"
    else:
        insight = "Feedback is balanced ⚖️"

    content.append(Paragraph(f"AI Insight: {insight}", styles['Normal']))

    content.append(Spacer(1, 20))

    content.append(Paragraph("AI REPORT", styles['Heading2']))
    content.append(Spacer(1, 10))

    content.append(Paragraph("Summary:", styles['Heading3']))
    content.append(Paragraph(ai_summary, styles['Normal']))

    content.append(Spacer(1, 10))

    content.append(Paragraph("Problems:", styles['Heading3']))
    for p in ai_problems:
        content.append(Paragraph(f"- {p}", styles['Normal']))

    content.append(Spacer(1, 10))

    content.append(Paragraph("Suggestions:", styles['Heading3']))
    for s in ai_suggestions:
        content.append(Paragraph(f"- {s}", styles['Normal']))

    doc.build(content)

    return send_file(pdf_path, as_attachment=True)

# 📈 ANALYTICS
@app.route('/analytics')
@login_required
def analytics():

    if current_user.role == 'admin':
        feedbacks = Feedback.query.all()
    else:
        feedbacks = Feedback.query.filter_by(user_id=current_user.id).all()

    total = len(feedbacks)

    positive = sum(1 for f in feedbacks if f.sentiment == "Positive")
    negative = sum(1 for f in feedbacks if f.sentiment == "Negative")
    neutral = sum(1 for f in feedbacks if f.sentiment == "Neutral")

    emotions = {}
    for f in feedbacks:
        emotions[f.emotion] = emotions.get(f.emotion, 0) + 1

    services = {}
    for f in feedbacks:
        if f.service:
            services[f.service] = services.get(f.service, 0) + 1

    trend = [
        1 if f.sentiment == "Positive"
        else 0 if f.sentiment == "Negative"
        else 0.5
        for f in feedbacks[-10:]
    ]

    score = round((positive / total) * 100, 2) if total > 0 else 0

    data_values = [
        1 if f.sentiment == "Positive"
        else 0 if f.sentiment == "Negative"
        else 0.5
        for f in feedbacks
    ]

    if not data_values:
        data_values = [0]

    return render_template(
        'analytics.html',
        positive=positive,
        negative=negative,
        neutral=neutral,
        total=total,
        emotions=emotions,
        services=services,
        trend=trend,
        score=score,
        data_values=data_values
    )


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


# 📄 ABOUT PAGE
@app.route('/about')
def about():
    return render_template('about.html')


# ⚙️ SETTINGS PAGE
@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        old_password = request.form.get('old_password')

        user = current_user

        # 🔐 verify current password
        if not check_password_hash(user.password, old_password):
            flash("❌ Wrong current password", "error")
            return redirect('/settings')

        # username update
        if username:
            user.username = username

        # password update
        if password:
            if not is_strong_password(password):
                flash("❌ Weak password", "error")
                return redirect('/settings')

            user.password = generate_password_hash(password)

        user.email_notify = True if request.form.get('email_notify') == 'on' else False
        user.ai_enabled = True if request.form.get('ai_toggle') == 'on' else False

        db.session.commit()

        flash("✅ Settings updated successfully", "success")
        return redirect('/settings')

    return render_template('settings.html')
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
    return redirect('/login')


if __name__ == '__main__':
    with app.app_context():
        db.create_all()

    app.run(debug=True)