# PulseCX — Customer Experience Analytics Platform

PulseCX is a Flask web application for collecting customer feedback and turning it into
sentiment analytics, emotion breakdowns, and business-facing reports. Feedback can be entered
manually, imported in bulk via CSV, or submitted through a small JSON API. Every entry is
classified for sentiment and emotion, stored, and rolled up into dashboards, analytics views,
and exportable PDF/CSV reports.

## Contents

- [Overview](#overview)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [API Reference](#api-reference)
- [Database](#database)
- [Team](#team)

## Overview

```
Browser (Tailwind UI + vanilla JS)
        |
        v
Flask routes (app.py)
        |
        +--> Sentiment classifier (TextBlob polarity)
        +--> Rule-based emotion detector
        +--> Insight engine (Groq LLM, cached per feedback count)
        |
        v
SQLite / PostgreSQL (SQLAlchemy models, Alembic migrations)
        |
        v
Dashboard, Analytics, Reports (HTML + Chart.js + PDF export)
```

Every persisted feedback row goes through the same classification path
(`classify_and_log` in `app.py`), so results are consistent whether the data came from the
manual entry form, a CSV import, an API call, or an edit. The live-typing preview on the
dashboard uses the same underlying classifier without writing to the audit log, since it runs
on every keystroke rather than on a saved submission.

## Features

**Sentiment & emotion analysis**
- Real-time sentiment preview while typing, served by `/live_sentiment`
- TextBlob polarity-based classification into Positive / Negative / Neutral, with a
  confidence score derived from distance to the classification boundary
- Rule-based emotion tagging (Happy / Sad / Angry / Neutral)
- Low-confidence classifications are written to an audit log for later review

**Insight generation**
- Aggregated feedback statistics and sample text are sent to a Groq-hosted LLM
  (`llama-3.3-70b-versatile`) to produce a structured summary: pain points, positive
  highlights, recommendations, action items, trend analysis, and a short predictive note
- Results are cached in the database and only regenerated when the underlying feedback
  count changes, so normal page loads don't trigger an LLM call
- Users can disable this feature per-account from Settings

**Dashboards & analytics**
- KPI summary (total feedback, sentiment mix, CX score), sentiment trend chart, emotion
  distribution, and top services, built with Chart.js
- A self-consistency check (not accuracy against labeled ground truth) that re-runs the
  classifier over recent rows and reports agreement, precision, and recall against what was
  originally stored
- CSV bulk import (capped at 5,000 rows per file) with per-row validation and a skipped-row
  count

**Reporting**
- On-screen report view and a downloadable PDF report (via xhtml2pdf), both built from the
  same context builder so the two never drift out of sync
- CSV export of a user's own feedback data

**Accounts & access control**
- Registration and login with PBKDF2-hashed passwords and a strong-password policy
- Brute-force login protection (attempt counter per IP)
- Email-based password reset with single-use, time-limited tokens
- Two roles: regular users see only their own data; admins can view all data, manage roles,
  and delete any feedback record
- Admin rights are granted from the Admin panel by an existing admin — there is no
  self-service admin code on the registration form

**Account settings**
- Change username, email, and password
- Toggle AI insight generation and email notifications
- Upload/replace an avatar
- Clear all feedback data or delete the account entirely

## Tech Stack

| Layer          | Technology                                    |
|----------------|------------------------------------------------|
| Backend        | Flask, Flask-Login, Flask-WTF (CSRF), Flask-Migrate |
| Sentiment/NLP  | TextBlob                                        |
| Insight engine | Groq API (LLaMA 3.3 70B)                        |
| Database       | SQLAlchemy ORM, SQLite (dev) / PostgreSQL (prod), Alembic migrations |
| Frontend       | Jinja2 templates, Tailwind CSS, vanilla JavaScript |
| Charts         | Chart.js                                        |
| PDF reports    | xhtml2pdf, matplotlib (chart rendering)         |
| Email          | Flask-Mail                                      |
| Deployment     | Gunicorn                                        |

## Project Structure

```
customer-experiencre-CX--main/
├── app.py                  Flask app: routes, auth, classification, insight engine, reports
├── models.py                SQLAlchemy models (User, Feedback, AuditLog, AIInsight)
├── requirements.txt
├── .env.example              Environment variable template
├── migrations/               Alembic migration history
├── templates/                 Jinja2 templates (dashboard, analytics, reports, admin, auth, ...)
├── static/
│   ├── js/                    custom-select.js, kpi-count.js, theme.js
│   └── vendor/                 chart.js, lucide, three.js (self-hosted)
└── instance/                    SQLite database file (created at runtime)
```

## Getting Started

### 1. Clone and enter the project

```bash
git clone <repository-url>
cd customer-experiencre-CX--main
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Copy `.env.example` to `.env` and fill in the required values:

```bash
cp .env.example .env
```

At minimum, `GROQ_API_KEY` is required — the app will not start without it. `SECRET_KEY`
and the `MAIL_*` variables are optional (see [Configuration](#configuration)).

### 4. Run the application

```bash
python app.py
```

Pending database migrations are applied automatically on startup. The app is then available at:

```
http://127.0.0.1:5000
```

## Configuration

| Variable              | Required | Purpose                                              |
|------------------------|----------|-------------------------------------------------------|
| `GROQ_API_KEY`          | Yes      | Groq API key used by the insight engine               |
| `SECRET_KEY`            | No       | Flask session signing key (a random one is generated if unset) |
| `DATABASE_URL`          | No       | Defaults to a local SQLite file; set for PostgreSQL in production |
| `MAIL_SERVER` / `MAIL_PORT` / `MAIL_USE_TLS` | No | SMTP settings for password-reset email |
| `MAIL_USERNAME` / `MAIL_PASSWORD` | No | SMTP credentials — without these, password reset logs a warning instead of sending |
| `MAIL_DEFAULT_SENDER`   | No       | From-address for outgoing mail                        |

## API Reference

### `POST /live_sentiment`

Real-time preview used by the dashboard's live-typing indicator. Requires an authenticated
session.

Request:
```json
{ "text": "Service was very bad" }
```

Response:
```json
{ "sentiment": "Negative", "confidence": 82.5, "emotion": "Angry" }
```

### `POST /api/submit_feedback`

Persists a feedback entry (equivalent to the dashboard's manual entry form).

```json
{ "text": "Great support", "name": "Jane", "phone": "9876543210", "service": "Support" }
```

### `GET /api/dashboard_data`

Returns the current scope's KPIs, sentiment trend, model self-consistency score, and the
most recent feedback rows, as consumed by the dashboard's auto-refresh.

### `GET /api/analytics_data`

Returns aggregated sentiment/emotion/service breakdowns for the analytics page.

## Database

Schema changes are managed with Alembic via Flask-Migrate. After changing `models.py`:

```bash
flask db migrate -m "describe the change"
flask db upgrade
```

The application also applies any pending migration automatically on startup, so a fresh
checkout only needs `python app.py` to end up on the latest schema.

## Team

- Abhigyan Khare — Full Stack & Backend
- Oshiva Singh — UI/UX
- Ashish Agarwal — Backend
