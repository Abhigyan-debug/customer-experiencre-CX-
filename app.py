from flask import Flask, render_template, redirect, request, abort, flash, url_for, jsonify
from sympy import content
from models import db, User, Feedback
from flask_wtf import CSRFProtect
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
import matplotlib
matplotlib.use('Agg')
from groq import Groq
load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

from sklearn.metrics import accuracy_score, precision_score, recall_score

def evaluate_model(feedbacks):
    y_true = []
    y_pred = []

    for f in feedbacks:
        if f.text:
            # simple demo ground truth
            if "good" in f.text.lower():
                y_true.append("Positive")
            elif "bad" in f.text.lower():
                y_true.append("Negative")
            else:
                y_true.append("Neutral")

            y_pred.append(f.sentiment)

    if not y_true:
        return 0, 0, 0

    accuracy = accuracy_score(y_true, y_pred)
    precision = precision_score(y_true, y_pred, average='macro', zero_division=0)
    recall = recall_score(y_true, y_pred, average='macro', zero_division=0)

    return round(accuracy*100,2), round(precision*100,2), round(recall*100,2)
# 🤖 OPTIONAL AI MODEL (safe fallback)
try:
    from transformers import pipeline
    ai_model = pipeline("sentiment-analysis")
    AI_ENABLED = True
except:
    AI_ENABLED = False

app = Flask(__name__)

#  CSRF PROTECTION
csrf = CSRFProtect(app)

#  CONFIG
app.config['SECRET_KEY'] = 'secret123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=7)

db.init_app(app)

#  LOGIN MANAGER
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

        admin_code = request.form.get('admin_code')

        if admin_code == "SECRET123":
            role = 'admin'
        else:
            role = 'user'

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

@app.route('/delete/<int:id>')
def delete(id):
    feedback = Feedback.query.get_or_404(id)

    db.session.delete(feedback)
    db.session.commit()

    return redirect('/customers')  
 
@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    feedback = Feedback.query.get_or_404(id)

    if request.method == 'POST':
        feedback.name = request.form.get('name')
        feedback.phone = request.form.get('phone')
        feedback.service = request.form.get('service')
        feedback.text = request.form.get('text')

        db.session.commit()
        return redirect('/customers')

    return render_template('edit.html', feedback=feedback)

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

            from flask import flash
            flash("✅ CSV uploaded and analyzed successfully", "success")

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

            from flask import flash
            flash("✅ Feedback analyzed & saved successfully", "success")

            print("NEW FEEDBACK:", text)
            print("SENTIMENT:", sentiment)
            print("EMOTION:", emotion)

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

    #  Emotion Analysis
    from collections import Counter
    emotion_count = Counter(f.emotion for f in feedbacks)
    top_emotion = emotion_count.most_common(1)[0][0] if emotion_count else "None"

    #  AI INSIGHT
    if current_user.ai_enabled:
        raw = generate_insight(feedbacks)
        print("AI RAW OUTPUT:", raw)

        summary = ""
        problems = []
        suggestions = []

        section = None

        for line in raw.split("\n"):
            line = line.strip()

            if "Summary" in line:
                section = "summary"
                continue
            elif "Problems" in line:
                section = "problems"
                continue
            elif "Suggestions" in line:
                section = "suggestions"
                continue

            if section == "summary":
                if line:
                    summary += line.replace("-", "").strip() + " "

            elif section == "problems":
                if line.startswith("-"):
                    problems.append(line.replace("-", "").strip())

            elif section == "suggestions":
                if line.startswith("-"):
                    suggestions.append(line.replace("-", "").strip())

        # fallback
        if not summary.strip():
            summary = "Customer feedback shows mixed experiences."

        if not problems:
            problems = ["General issues detected"]

        if not suggestions:
            suggestions = ["Improve service quality"]

        from flask import session
        session["ai_summary"] = summary
        session["ai_problems"] = problems
        session["ai_suggestions"] = suggestions

        insight = {
            "summary": summary,
            "problems": problems,
            "suggestions": suggestions
        }
        accuracy, precision, recall = evaluate_model(feedbacks)
    else:
        insight = {"summary": "AI Disabled", "problems": [], "suggestions": []}
        accuracy, precision, recall = 0, 0, 0

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
        top_emotion=top_emotion,
         accuracy=accuracy,
         precision=precision,
         recall=recall
    )


#  LIVE SENTIMENT
@app.route('/live_sentiment', methods=['POST'])
@csrf.exempt 
@login_required
def live_sentiment():
    data = request.get_json(silent=True)
    text = data.get('text') if data else None

    if not text:
        return jsonify({"error": "No text provided"}), 400

    result = get_sentiment(text)

    if isinstance(result, (list, tuple)):
        sentiment = result[0]
        emotion = result[1] if len(result) > 1 else "Unknown"
    else:
        sentiment = result
        emotion = "Unknown"

    return jsonify({
        "sentiment": sentiment,
        "emotion": emotion
    })

#  ADMIN
from models import User, Feedback

@app.route('/admin')
@login_required
def admin():
    if current_user.role != 'admin':
        abort(403)

    users = User.query.all()
    feedbacks = Feedback.query.order_by(Feedback.id.desc()).all()  

    return render_template(
        'admin.html',
        users=users,
        feedbacks=feedbacks
    )

@app.route('/delete_feedback/<int:id>', methods=['POST'])
@login_required
def delete_feedback(id):
    if current_user.role != 'admin':
        abort(403)

    feedback = Feedback.query.get_or_404(id)
    db.session.delete(feedback)
    db.session.commit()

    return redirect('/admin')
   
from flask import send_file
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet
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

    plt.figure(figsize=(5,5))

    plt.pie(
        values,
        labels=labels,
        autopct='%1.1f%%',
        colors=['#22c55e','#ef4444','#eab308'],
        wedgeprops={'width': 0.4}
    )

    plt.text(0, 0, f"{total}\nTotal", ha='center', va='center', fontsize=14)

    plt.savefig(chart_path)
    plt.close()

    doc = SimpleDocTemplate("report.pdf")
    styles = getSampleStyleSheet()
    content = []

    # 🔥 TITLE
    content.append(Paragraph("AI REPORT", styles['Title']))
    content.append(Spacer(1, 10))

    # ✅ SUMMARY
    content.append(Paragraph("<b>Summary:</b>", styles['Heading3']))
    content.append(Paragraph(ai_summary, styles['Normal']))
    content.append(Spacer(1, 10))

    # ✅ PROBLEMS
    content.append(Paragraph("<b>Problems:</b>", styles['Heading3']))
    if ai_problems:
        for p in ai_problems:
            content.append(Paragraph(f"• {p}", styles['Normal']))
    else:
        content.append(Paragraph("No problems detected", styles['Normal']))

    content.append(Spacer(1, 10))

    # ✅ SUGGESTIONS
    content.append(Paragraph("<b>Suggestions:</b>", styles['Heading3']))
    if ai_suggestions:
        for s in ai_suggestions:
            content.append(Paragraph(f"• {s}", styles['Normal']))
    else:
        content.append(Paragraph("No suggestions available", styles['Normal']))

    content.append(Spacer(1, 20))

    # 📊 CHART TITLE
    content.append(Paragraph("<b>Sentiment Distribution</b>", styles['Heading2']))
    content.append(Spacer(1, 10))

    # 📊 STATS
    content.append(Paragraph(f"Total: {total}", styles['Normal']))
    content.append(Paragraph(f"Positive: {positive}", styles['Normal']))
    content.append(Paragraph(f"Negative: {negative}", styles['Normal']))
    content.append(Paragraph(f"Neutral: {neutral}", styles['Normal']))

    content.append(Spacer(1, 15))

    # 📊 DONUT CHART
    content.append(Image(chart_path, width=300, height=300))

    doc.build(content)

    return send_file("report.pdf", as_attachment=True)
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
from flask import session

from flask import session

@app.route('/reports')
@login_required
def reports():
    feedbacks = Feedback.query.filter_by(user_id=current_user.id).all()

    
    if "insight" not in session:
        session["insight"] = generate_insight(feedbacks)

    insight = session["insight"]

    # 📊 Stats
    positive = sum(1 for f in feedbacks if f.sentiment == "Positive")
    negative = sum(1 for f in feedbacks if f.sentiment == "Negative")
    neutral = len(feedbacks) - (positive + negative)

    return render_template(
        'reports.html',
        insight=insight,
        positive=positive,
        negative=negative,
        neutral=neutral
    )

@app.route('/refresh_ai')
@login_required
def refresh_ai():
    session.pop("insight", None)
    return redirect('/reports')

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

    feedbacks = Feedback.query.filter_by(user_id=user.id).all()

    total = len(feedbacks)
    positive = sum(1 for f in feedbacks if f.sentiment and f.sentiment.lower() == "positive")

    ai_score = int((positive / total) * 100) if total > 0 else 0

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        old_password = request.form.get('old_password')

        if (username or password):
            if not old_password or not check_password_hash(user.password, old_password):
                flash("❌ Wrong current password", "error")
                return redirect('/settings')

        if username and username != user.username:
            existing = User.query.filter_by(username=username).first()
            if existing:
                flash("❌ Username already taken", "error")
                return redirect('/settings')
            user.username = username

        if password:
            if not is_strong_password(password):
                flash("❌ Weak password", "error")
                return redirect('/settings')

            user.password = generate_password_hash(password)

        user.email_notify = 'email_notify' in request.form
        user.ai_enabled = 'ai_enabled' in request.form

        db.session.commit()

        flash("✅ Settings updated successfully", "success")
        return redirect('/settings')

    return render_template(
        'settings.html',
        ai_score=ai_score
    )
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
    with app.app_context():
        db.create_all()

    app.run(debug=True)