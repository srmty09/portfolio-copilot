import logging
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

from app.services.risk import HORIZON_DAYS

logger = logging.getLogger(__name__)

CONFIDENCE_LEVEL = 0.95


def _price_on_or_after(series: pd.Series, target: pd.Timestamp) -> float | None:
    if series.index.tz is not None and target.tzinfo is None:
        target = target.tz_localize(series.index.tz)
    elif series.index.tz is None and target.tzinfo is not None:
        target = target.tz_localize(None)
    matches = series[series.index >= target]
    if matches.empty:
        return None
    return float(matches.iloc[0])


def backtest_var(reports: list[dict]) -> dict:
    """
    reports: list of {"id": int, "created_at": datetime, "var_95": float,
    "allocation": dict[str, float]} (allocation is % weight per ticker at report time).

    For each report at least HORIZON_DAYS old, checks whether the portfolio's actual
    return over the following HORIZON_DAYS breached the report's predicted 95% VaR --
    the standard way (a Kupiec-style backtest) to check whether a VaR model is
    well-calibrated: a 95% VaR should be breached roughly 5% of the time, not
    dramatically more or less often.
    """
    now = datetime.utcnow()
    eligible = [r for r in reports if (now - r["created_at"]).days >= HORIZON_DAYS]

    expected_rate = round((1 - CONFIDENCE_LEVEL) * 100, 1)
    if not eligible:
        return {
            "eligible_reports": 0,
            "breaches": 0,
            "breach_rate": None,
            "expected_rate": expected_rate,
            "details": [],
            "message": f"No reports are at least {HORIZON_DAYS} days old yet -- check back later.",
        }

    all_tickers = sorted({t for r in eligible for t in r["allocation"]})
    earliest = min(r["created_at"] for r in eligible) - timedelta(days=7)

    price_history: dict[str, pd.Series] = {}
    for ticker in all_tickers:
        try:
            hist = yf.Ticker(ticker).history(start=earliest.date(), auto_adjust=True)
            if not hist.empty:
                price_history[ticker] = hist["Close"]
        except Exception:
            logger.warning("Backtest: failed to fetch history for %s", ticker, exc_info=True)

    details = []
    breaches = 0
    for r in eligible:
        start_ts = pd.Timestamp(r["created_at"])
        end_ts = start_ts + timedelta(days=HORIZON_DAYS)

        portfolio_return = 0.0
        complete = True
        for ticker, weight_pct in r["allocation"].items():
            series = price_history.get(ticker)
            p0 = _price_on_or_after(series, start_ts) if series is not None else None
            p1 = _price_on_or_after(series, end_ts) if series is not None else None
            if p0 is None or p1 is None:
                complete = False
                break
            portfolio_return += (weight_pct / 100) * ((p1 / p0) - 1)

        if not complete:
            logger.warning("Backtest: skipping report id=%s, incomplete price data", r.get("id"))
            continue

        breached = portfolio_return < -(r["var_95"] / 100)
        if breached:
            breaches += 1
        details.append(
            {
                "report_id": r.get("id"),
                "date": r["created_at"].isoformat(),
                "predicted_var_95_pct": r["var_95"],
                "actual_return_pct": float(round(portfolio_return * 100, 2)),
                "breached": breached,
            }
        )

    n = len(details)
    result = {
        "eligible_reports": n,
        "breaches": breaches,
        "breach_rate": float(round(breaches / n * 100, 2)) if n else None,
        "expected_rate": expected_rate,
        "details": details,
    }
    logger.info("VaR backtest: %d eligible report(s), %d breach(es), rate=%s%%", n, breaches, result["breach_rate"])
    return result
