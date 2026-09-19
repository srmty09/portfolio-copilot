# Portfolio Risk Copilot

A web app that analyzes a user's stock portfolio and returns a risk report: per-stock
volatility (historical, GARCH(1,1), or a trained LSTM forecast -- whichever is most
sophisticated and passes a sanity check), portfolio-level 30-day Value at Risk (95%
confidence, via Monte Carlo simulation), which holdings drive the most risk, relevant
market-risk context and live per-holding news pulled via RAG, and a plain-English
summary written by an LLM agent. The agent can also answer free-text "what if"
questions (a market shock, a hypothetical new position) by re-running the simulation
without touching real saved holdings, and past reports can be backtested against what
actually happened afterward to check whether the VaR model is well-calibrated. The
dashboard renders this as charts (allocation, volatility, risk contribution,
simulated-return distribution, a historical/GARCH/LSTM comparison table) plus the
underlying data table, and the backend logs every request, auth event, risk
calculation, and agent/tool call to `backend/logs/app.log`.

## Tech stack

- **Backend**: FastAPI + Python, SQLAlchemy (sync) on PostgreSQL
- **Auth**: JWT (python-jose + passlib/bcrypt), roles `user` / `admin`, Google OAuth,
  and forgot/reset password
- **RAG**: LangChain + FAISS, local HuggingFace sentence-transformer embeddings, over a
  corpus of static risk-education text plus live per-ticker news (via `yfinance`)
- **Agent**: LangGraph ReAct agent (DeepSeek `deepseek-chat` as the LLM) with three
  tools: `calculate_risk`, `retrieve_context`, and `simulate_scenario`
- **Risk engine**: yfinance + numpy/pandas Monte Carlo simulation. Per-ticker
  volatility prefers a trained LSTM forecast, then a GARCH(1,1) fit (via the `arch`
  package), then falls back to historical std -- each one sanity-checked before use
- **Backtesting**: checks past reports' predicted VaR against what tickers actually
  did over the following 30 days, once that much time has passed
- **Training**: PyTorch LSTM script, wired into the risk engine as an optional forecast
- **Frontend**: plain HTML + vanilla JS, no framework

## A note on two deviations from a literal "OpenAI + as given" build

1. **Embeddings**: the original spec called for OpenAI embeddings, but only a
   DeepSeek API key was provided, and DeepSeek does not publish a public embeddings
   endpoint (only chat completions, via an OpenAI-compatible API). RAG embeddings
   here use a local, free HuggingFace model (`sentence-transformers/all-MiniLM-L6-v2`,
   downloaded once on first run, ~80MB) instead. The LLM agent itself (report
   generation) uses DeepSeek's `deepseek-chat` model through `langchain_openai.ChatOpenAI`
   pointed at DeepSeek's OpenAI-compatible base URL — this is the standard way to call
   DeepSeek from LangChain, no separate SDK needed.
2. **API key handling**: the DeepSeek key was pasted directly in chat. It has been
   placed only in `backend/.env` (already covered by `.gitignore`, never committed,
   never hardcoded into source) and is loaded via `python-dotenv`. Since the raw key
   was typed into this conversation, consider rotating it if that transcript is ever
   shared or logged anywhere you don't fully control.

## Project structure

```
portfolio-copilot/
  backend/
    app/
      api/          # auth (+ Google OAuth, forgot/reset password), holdings, analysis routes
      core/         # config, database, security
      models/       # SQLAlchemy models
      services/     # risk (Monte Carlo + GARCH/LSTM), rag, agent, backtest, email
    alembic/        # DB migrations
    main.py
    requirements.txt
    .env.example
  frontend/
    index.html            # login/register, Google sign-in, forgot password
    dashboard.html         # holdings + analyze + report + charts + ask
    oauth-callback.html    # receives the JWT after a Google sign-in
    reset-password.html    # set a new password from a reset link
    app.js
    style.css
  training/
    train_lstm.py   # standalone volatility LSTM training script
    lstm_weights.pt # trained weights (gitignored)
    requirements.txt
  README.md
```

## Setup

### 1. Prerequisites

- Python 3.11+ (tested on 3.14)
- PostgreSQL running locally

### 2. Create a virtual environment and install dependencies

```bash
cd portfolio-copilot/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Create the database

```bash
createdb portfolio_copilot
```

(Adjust for your local Postgres setup — user/password/host — and match whatever
you put in `DATABASE_URL` below.)

### 4. Configure environment variables

```bash
cp .env.example .env
```

Edit `backend/.env` and fill in:

- `DATABASE_URL` — your local Postgres connection string
- `JWT_SECRET_KEY` — a long random string (e.g. `openssl rand -hex 32`). The app
  refuses to start if this is missing, still the `.env.example` placeholder, or
  under 16 characters -- every protected endpoint depends on it being real.
- `DEEPSEEK_API_KEY` — your DeepSeek API key. Not required to start the app (auth
  and holdings work without it), but `/analyze` and `/analyze/ask` will fail as
  soon as they reach the LLM call, and a warning is logged at startup if it's unset.

### 5. Run database migrations

```bash
alembic upgrade head
```

### 6. Run the API

```bash
uvicorn main:app --reload
```

The API is now at `http://localhost:8000` (interactive docs at `/docs`).

### 7. Open the frontend

Serve the `frontend/` folder with any static server, e.g.:

```bash
cd ../frontend
python3 -m http.server 5500
```

Then open `http://localhost:5500/index.html`, register a user, log in, add a few
holdings (ticker + shares), and click **Analyze Portfolio**.

### Logs

Every request-level action (registration, login, holdings changes, risk calculations,
agent/tool calls, errors) is logged to `backend/logs/app.log` (rotated at 5MB, 3
backups kept) and echoed to the console. The file is gitignored.

### Admin role

There is no public endpoint to create an admin — that's intentional, to prevent
self-escalation. To promote a user manually:

```sql
UPDATE users SET role = 'admin' WHERE email = 'someone@example.com';
```

Admins see every user's reports via `GET /reports` / `GET /reports/{id}`; regular
users only see their own.

## API summary

| Method | Path              | Auth       | Description                          |
|--------|-------------------|------------|---------------------------------------|
| POST   | /auth/register    | none       | Create a user, returns a JWT          |
| POST   | /auth/login        | none       | Returns a JWT                         |
| POST   | /auth/forgot-password | none    | Request a reset link (always returns a generic message) |
| POST   | /auth/reset-password  | none    | Reset password given a valid token    |
| GET    | /auth/google/login | none       | Redirects to Google's consent screen  |
| GET    | /auth/google/callback | none    | Google redirects here; issues a JWT and redirects to the frontend |
| POST   | /holdings          | Bearer     | Add a holding                         |
| GET    | /holdings          | Bearer     | List current user's holdings          |
| DELETE | /holdings/{id}     | Bearer     | Remove a holding                      |
| POST   | /analyze           | Bearer     | Run the full risk pipeline, save + return a report |
| POST   | /analyze/ask       | Bearer     | Ask a free-text question (e.g. a stress scenario); not saved as a report |
| GET    | /reports           | Bearer     | List reports (own, or all if admin) -- summary shape only, no risk_data |
| GET    | /reports/backtest  | Bearer     | Backtest past reports' VaR against actual outcomes |
| GET    | /reports/{id}      | Bearer     | Get one report, full shape including risk_data |

`GET /reports` intentionally omits `report_text` and `risk_data` -- the latter carries
a 1,000-element simulated-return array per report, fine for one report's charts but
unbounded for a list that grows with every analysis. The frontend fetches the full
report via `/reports/{id}` when you click one in the Past Reports list.

## Google sign-in

Requires credentials from Google's own console -- there's no way around this step,
Google is the one issuing them:

1. Go to https://console.cloud.google.com/apis/credentials, create an OAuth client ID
   of type "Web application".
2. Under "Authorized redirect URIs", add exactly `http://localhost:8000/auth/google/callback`
   (or whatever you set `GOOGLE_REDIRECT_URI` to in `.env` -- it must match exactly,
   including trailing slashes and http vs https).
3. Copy the generated Client ID and Client Secret into `backend/.env` as
   `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`.
4. Restart the backend. Until these are set, `/auth/google/login` returns 503 rather
   than erroring deep inside the flow, and a warning is logged at startup.

**How it works**: `GET /auth/google/login` redirects to Google's consent screen with a
random `state` value (CSRF protection, held in a short-lived in-memory store -- same
pattern as the price-history cache). Google redirects back to
`/auth/google/callback` with a code; the backend exchanges it for a token, fetches the
verified email from Google's userinfo endpoint, and either creates a new
`auth_provider="google"` user or -- if a local-password account already exists with
that exact (Google-verified) email -- links the Google identity to the existing
account rather than creating a duplicate. The resulting JWT is passed back to the
frontend as a URL **fragment** (`oauth-callback.html#token=...`), not a query
parameter, since fragments are never sent to or logged by the server. A Google-only
account has no password: it can't use `/auth/login` or `/auth/forgot-password`,
consistently rejected the same way an unregistered email would be, so neither
endpoint leaks which accounts are Google-linked.

## Forgot / reset password

`POST /auth/forgot-password` always returns the same generic message regardless of
whether the email exists, belongs to a Google-only account, or is a real local
account -- otherwise the endpoint could be used to enumerate registered emails. For a
real local account, it generates a random token (30-minute expiry, single use,
stored on the `users` row) and calls `services/email.py`.

That service sends via SMTP if `SMTP_HOST` is configured in `.env` -- otherwise it
logs the reset link to `backend/logs/app.log` instead of emailing it. This means the
whole flow is fully testable right now with zero setup: trigger a reset, grep the log
for `reset-password.html?token=`, and use that link. To actually send email, set
`SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASSWORD`/`SMTP_FROM` in `.env` -- for
Gmail that's `smtp.gmail.com`, port 587, and an
[app password](https://myaccount.google.com/apppasswords) (not your normal password).

## Rate limiting on auth endpoints

`app/core/rate_limit.py` is a small in-memory limiter (same per-process pattern as
the price cache and OAuth state store) applied to the four unauthenticated auth
endpoints, since they're the ones either brute-forceable or abusable against a third
party:

| Endpoint | Limit | Keyed by |
|---|---|---|
| `/auth/login` | 5 / 5 min | IP **and** email (independently) |
| `/auth/register` | 5 / 10 min | IP |
| `/auth/forgot-password` | 3 / 15 min | IP **and** email (independently) |
| `/auth/reset-password` | 5 / 10 min | IP |

Login and forgot-password are checked against *both* an IP-scoped and an
email-scoped counter: the IP check stops one source hammering many target accounts,
the email check stops many sources (e.g. a botnet) hammering one target account --
either one alone misses half the threat model. Exceeding a limit returns `429` with
a `Retry-After` header. Every request counts toward the limit, not just failed ones
-- simpler to reason about than a failures-only counter, and the limits are generous
enough that normal typo-driven retries won't hit them. Like the other in-memory
stores in this app, this resets on restart and isn't shared across multiple worker
processes -- fine at this app's scale.

## Price history caching

`services/risk.py` caches each ticker's downloaded price history in memory for 15
minutes. This cuts latency on repeat analyses of the same tickers and, just as
importantly, reduces how often the app hits yfinance at all -- fewer live calls
means fewer chances to hit a transient failure like the DNS/cookie hiccup that could
otherwise make a perfectly fine ticker look "delisted" (see the retry logic below).
The cache is per-process and in-memory -- correct but not shared if you ever run
multiple worker processes; each would just warm its own copy.

## RAG: concepts + live news

`services/rag.py` combines two sources into one FAISS index, rebuilt fresh on every
`/analyze` call (cheap — a handful of short documents, and the embedding model itself
stays cached across calls): 4 static paragraphs on risk/VaR/volatility/diversification,
plus up to 4 recent news headlines per holding fetched live via `yfinance`'s `.news`.
If a ticker's news fetch fails (network issue, no news available), that ticker is
just skipped for this run rather than failing the whole analysis. The agent is
prompted to query this at least once for risk concepts and again for news on a
specific holding when relevant.

## Training the volatility LSTM

```bash
cd training
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 train_lstm.py --tickers AAPL,MSFT,GOOGL,AMZN,SPY --epochs 20
```

Downloads 5 years of daily prices per ticker, builds sequences of 30-day rolling
log returns as input with trailing realized volatility as the label, trains a
2-layer LSTM (Adam + MSE), prints train/val loss per epoch, and saves weights to
`training/lstm_weights.pt`. The `VolatilityLSTM` architecture lives in
`backend/app/services/volatility_model.py` so both sides load the exact same model —
`train_lstm.py` imports it from there rather than duplicating it.

**How the backend uses it**: `services/risk.py` checks for `training/lstm_weights.pt`
on the first `/analyze` call per process. If it's there, each ticker's most recent
30-day return window is fed through the model to forecast its volatility; that
forecast (if it passes a basic sanity check against the historical figure) replaces
the historical estimate as the diagonal of the covariance matrix used for the Monte
Carlo simulation — the correlation *structure* between holdings still comes from
history either way, since the LSTM is a single-ticker model and was never trained to
capture cross-asset correlation. If the weights file doesn't exist yet, everything
falls back to pure historical volatility with no error.

## Volatility: LSTM, GARCH, or historical

Per ticker, `_resolve_volatilities` in `services/risk.py` tries the LSTM forecast
first, then a GARCH(1,1) fit (the actual industry-standard classical volatility
model, fitted fresh per request via the `arch` package -- it captures volatility
clustering that a flat historical average ignores), then falls back to historical
daily std. Each candidate is sanity-checked (must be positive and within 5x the
historical figure) before being trusted, so a bad LSTM forecast or a non-converged
GARCH fit can't produce nonsense risk numbers. Every report's `risk_data` carries
both `volatility_source` (which method won, per ticker) and `volatility_estimates`
(every method's annualized figure, where available) so you can see all three
side by side -- rendered as a comparison table on the dashboard, with `*` marking
the one actually used in the simulation.

## Asking "what if" questions

`POST /analyze/ask` takes `{"question": "..."}` and runs the same LangGraph agent
used for `/analyze`, but with the question as the user message instead of the fixed
"analyze my portfolio" prompt, and a third tool available: `simulate_scenario`. That
tool re-runs `run_monte_carlo` with either an immediate price shock applied to every
holding (`shock_pct`, e.g. -20 for a 20% market-wide drop) and/or a hypothetical
additional position (`additional_ticker` + `additional_shares`) -- without writing
anything to the `holdings` table, since it's exploring a hypothetical, not the user's
real portfolio. The agent decides on its own whether a question warrants calling this
tool; a plain "how risky is my portfolio" question just uses `calculate_risk` as
before. Answers here aren't saved as `RiskReport` rows -- they're ephemeral, unlike
`/analyze`.

## Backtesting the VaR model

Every `/analyze` predicts a 95% VaR: "there's roughly a 5% chance of losing more than
X% over the next 30 days." `GET /reports/backtest` checks whether that's actually
true by looking at every past report at least 30 days old, computing what the
portfolio (at that report's allocation) actually returned over the following 30 days
using real price history, and counting how often the actual loss exceeded the
predicted VaR. A well-calibrated model should show a breach rate near 5% -- much
higher means the model understates risk, much lower means it's overly conservative.
This is a standard VaR-validation technique (a Kupiec-style backtest). Reports newer
than 30 days are skipped since there isn't enough forward data yet to judge them; if
none qualify, the endpoint says so rather than returning a misleading empty result.
