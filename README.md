# Portfolio Risk Copilot

Analyzes a stock portfolio's risk: per-stock volatility, 30-day Value at Risk via
Monte Carlo simulation, which holdings drive the most risk, relevant news via RAG,
and a plain-English summary from an LLM agent.

**Stack**: FastAPI + PostgreSQL backend, plain HTML/JS frontend, DeepSeek LLM,
LangGraph agent, PyTorch LSTM + GARCH volatility models, JWT + Google OAuth.

## Setup

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
createdb portfolio_copilot
cp .env.example .env   # fill in DATABASE_URL, JWT_SECRET_KEY, DEEPSEEK_API_KEY
alembic upgrade head
uvicorn main:app --reload
```

In another terminal:

```bash
cd frontend
python3 -m http.server 5500
```

Open `http://localhost:5500/index.html`.

## Optional

- **Google sign-in**: set `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` in `.env`
  (from [Google Cloud Console](https://console.cloud.google.com/apis/credentials),
  redirect URI `http://localhost:8000/auth/google/callback`)
- **Password reset emails**: set `SMTP_*` in `.env` -- without it, reset links are
  logged to `backend/logs/app.log` instead of sent
- **Train the volatility LSTM**: `cd training && pip install -r requirements.txt &&
  python3 train_lstm.py`

## Notes

- Admin role isn't self-service: `UPDATE users SET role = 'admin' WHERE email = '...'`
- Full API reference is auto-generated at `http://localhost:8000/docs`
