<h1 align="center">🚀 CX Analytics</h1>

<p align="center">
  <b>AI-Powered Customer Experience Intelligence Platform</b><br>
  <i>Transforming Feedback → Insights → Decisions</i>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Backend-Flask-black?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/Frontend-Tailwind-blue?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/AI-NLP%20%7C%20LLM-purple?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/Database-SQLite-green?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/Status-Production%20Ready-success?style=for-the-badge"/>
</p>

---

## 🌌 Introduction

CX Analytics is a full-stack AI-powered platform that analyzes customer feedback and converts it into structured insights, analytics, and actionable recommendations.

It integrates:

* ⚡ Real-time sentiment analysis
* 🧠 AI-driven insights (LLM)
* 📊 Interactive dashboards
* 📄 Automated reporting

---

## 🎯 Objective

To build a system that:

* Understands customer sentiment instantly
* Detects emotions behind feedback
* Generates insights automatically
* Helps businesses improve decision-making

---

## 🧠 Core System Architecture

```
User Input (Text / CSV)
        ↓
Frontend (Tailwind UI + JS)
        ↓
Live API (/live_sentiment)
        ↓
Flask Backend
        ↓
AI Layer:
   ├── Transformer Model (HuggingFace)
   ├── TextBlob Fallback
   ├── Emotion Detection Engine
   └── Groq LLM Insight Generator
        ↓
Database (SQLite via SQLAlchemy)
        ↓
Dashboard + Reports + Analytics
```

---

## ⚙️ Features (Complete System)

### 🔥 1. Real-Time Sentiment Analysis

* Live typing detection (no page reload)
* API-based processing
* Instant UI updates

---

### 🧠 2. AI Sentiment Engine

* Transformer model (if available)
* TextBlob fallback (for reliability)
* Classifies:

  * Positive
  * Negative
  * Neutral

---

### 😊 3. Emotion Detection

* Rule-based emotion classification:

  * Happy
  * Sad
  * Angry
  * Neutral

---

### 📊 4. Advanced Dashboard

* Total feedback count
* Positive / Negative ratio
* CX Health Score
* Sentiment trend graphs
* Emotion distribution
* Model performance:

  * Accuracy
  * Precision
  * Recall

---

### ⚡ 5. Live Sentiment API

* Endpoint: `/live_sentiment`
* Async fetch integration
* Real-time response

---

### 📂 6. Data Processing

* Manual feedback entry
* CSV upload for bulk processing
* Automatic sentiment tagging
* Database storage

---

### 📈 7. Analytics Module

* Sentiment breakdown
* Emotion insights
* Service-wise analysis
* Trend filtering (last 5 / 10 / all)

---

### 🧠 8. AI Insight Generator

* Uses Groq LLM
* Generates:

  * Summary
  * Problems
  * Suggestions

---

### 📄 9. Automated Report Generation

* PDF report export
* Includes:

  * AI insights
  * Charts
  * Statistics

---

### 🔐 10. Authentication & Security

* User registration & login
* Password hashing (PBKDF2)
* Brute-force protection
* Role-based access:

  * User → personal data
  * Admin → full system

---

### 🧑‍💼 11. Admin Panel

* View all users
* View all feedback
* Delete feedback

---

### ⚙️ 12. Settings System

* Update username/password
* Toggle AI insights
* Email notifications toggle
* Data reset

---

### 📤 13. Export & Data Control

* Export feedback as CSV
* Clear all data
* Delete account

---

### 🎨 14. UI/UX Features

* Glassmorphism design
* Animated UI transitions
* Dark mode support
* Interactive charts (Chart.js)
* Responsive layout

---

## 🧩 Tech Stack

| Layer    | Technology                         |
| -------- | ---------------------------------- |
| Backend  | Flask                              |
| Frontend | HTML, Tailwind CSS, JavaScript     |
| AI/NLP   | HuggingFace Transformers, TextBlob |
| LLM      | Groq (LLaMA Model)                 |
| Database | SQLite + SQLAlchemy                |
| Charts   | Chart.js                           |
| Reports  | ReportLab                          |

---

## 📂 Project Structure

```
CX-Analytics/
│── app.py
│── models.py
│── requirements.txt
│── .env
│
├── templates/
│   ├── dashboard.html
│   ├── analytics.html
│   ├── admin.html
│   ├── reports.html
│   ├── settings.html
│   ├── login.html
│   ├── register.html
│   ├── about.html
│
├── static/
├── instance/
├── screenshots/
```

---

## 🚀 How to Run the Project

### 🔧 1. Clone Repository

```bash
git clone https://github.com/your-username/cx-analytics.git
cd cx-analytics
```

---

### 📦 2. Install Dependencies

```bash
pip install -r requirements.txt
```

---

### 🔐 3. Setup Environment Variables

Create a `.env` file:

```env
GROQ_API_KEY=your_api_key_here
```

---

### ▶️ 4. Run Application

```bash
python app.py
```

---

### 🌐 5. Open in Browser

```
http://127.0.0.1:5000
```

---

## 🔄 API Example

### POST `/live_sentiment`

**Request**

```json
{
  "text": "Service was very bad"
}
```

**Response**

```json
{
  "sentiment": "Negative",
  "emotion": "Angry"
}
```

---

## 📊 Example Output

| Feedback         | Sentiment | Emotion |
| ---------------- | --------- | ------- |
| Amazing service  | Positive  | Happy   |
| Worst experience | Negative  | Angry   |
| It's okay        | Neutral   | Neutral |

---

## 🔮 Future Enhancements

* 🌍 Multi-language sentiment detection
* 🎤 Voice-based feedback analysis
* 🤖 Deep learning emotion model
* ☁️ Cloud deployment (AWS / Render)

---

## 👨‍💻 Team

* Abhigyan Khare – Full Stack & AI
* Oshiva Singh – UI/UX
* Ashish Agarwal – Backend

---

## 🏁 Conclusion

CX Analytics is not just a dashboard —
it is a **complete feedback intelligence system** that converts customer opinions into meaningful business decisions.

---

<p align="center">
  ⭐ If you like this project, give it a star!
</p>
