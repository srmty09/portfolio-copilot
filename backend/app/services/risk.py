import logging
import time

import numpy as np
import pandas as pd
import yfinance as yf

from app.services import volatility_model

try:
    from arch import arch_model

    ARCH_AVAILABLE = True
except ImportError:
    ARCH_AVAILABLE = False

logger = logging.getLogger(__name__)

TRADING_DAYS_PER_YEAR = 252
SIMULATION_PATHS = 1000
HORIZON_DAYS = 30
CONFIDENCE_LEVEL = 0.95
RANDOM_SEED = 42
# A forecast (LSTM or GARCH) further than this multiple from the historical estimate
# is treated as untrustworthy (e.g. an undertrained model, or a non-converged GARCH
# fit) and discarded in favor of the historical figure for that ticker.
SANITY_MULTIPLE = 5
# yfinance occasionally returns an empty result on a transient network/DNS hiccup
# (its "crumb" auth cookie fetch failing is one observed cause) and reports it with
# the same generic "possibly delisted" message as an actual bad ticker. Retrying a
# couple of times rides out the transient case instead of failing the whole request.
MAX_DOWNLOAD_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 2.0
# Daily closes don't change intraday, so a short cache both cuts latency for repeat
# analyses and reduces exposure to yfinance flakiness (fewer live calls, fewer chances
# to hit a bad one). Per-process, in-memory -- fine for a single-worker deployment;
# a multi-worker setup would just have each worker warm its own copy.
PRICE_CACHE_TTL_SECONDS = 900

_price_cache: dict[str, tuple[float, pd.Series]] = {}


def _get_cached_prices(ticker: str) -> pd.Series | None:
    entry = _price_cache.get(ticker)
    if entry is None:
        return None
    cached_at, series = entry
    if time.time() - cached_at > PRICE_CACHE_TTL_SECONDS:
        return None
    return series


def _download_price_history(tickers: list[str]) -> pd.DataFrame:
    series = {}
    for ticker in tickers:
        cached = _get_cached_prices(ticker)
        if cached is not None:
            logger.info("Using cached price history for %s (age < %ds)", ticker, PRICE_CACHE_TTL_SECONDS)
            series[ticker] = cached
            continue

        history = None
        for attempt in range(1, MAX_DOWNLOAD_ATTEMPTS + 1):
            logger.info("Downloading 2y price history for %s (attempt %d/%d)", ticker, attempt, MAX_DOWNLOAD_ATTEMPTS)
            try:
                history = yf.Ticker(ticker).history(period="2y", auto_adjust=True)
            except Exception:
                logger.warning("Price history request for %s raised an exception", ticker, exc_info=True)
                history = None

            if history is not None and not history.empty:
                break
            if attempt < MAX_DOWNLOAD_ATTEMPTS:
                logger.warning(
                    "Empty price history for %s on attempt %d/%d, retrying in %.0fs",
                    ticker,
                    attempt,
                    MAX_DOWNLOAD_ATTEMPTS,
                    RETRY_DELAY_SECONDS,
                )
                time.sleep(RETRY_DELAY_SECONDS)

        if history is None or history.empty:
            logger.warning("No price history found for ticker '%s' after %d attempts", ticker, MAX_DOWNLOAD_ATTEMPTS)
            raise ValueError(f"No price history found for ticker '{ticker}'")
        series[ticker] = history["Close"]
        _price_cache[ticker] = (time.time(), history["Close"])

    prices = pd.concat(series, axis=1, join="inner").dropna()
    if prices.empty:
        logger.warning("No overlapping trading history for tickers %s", tickers)
        raise ValueError("No overlapping trading history for the given tickers")
    return prices


def _log_returns(prices: pd.DataFrame) -> pd.DataFrame:
    return np.log(prices / prices.shift(1)).dropna()


def _fit_garch_daily_vol(returns: pd.Series) -> float | None:
    """
    Fits a GARCH(1,1) model (the standard classical volatility model, capturing
    volatility clustering that a flat historical std ignores) and returns its
    one-step-ahead forecasted daily volatility. Returns None if the `arch`
    package isn't installed or the fit fails to converge.
    """
    if not ARCH_AVAILABLE:
        return None
    try:
        # Returns are scaled by 100 before fitting -- the arch package's optimizer
        # is numerically unstable on raw daily-log-return magnitudes (~0.01-0.03).
        model = arch_model(returns.to_numpy() * 100, vol="Garch", p=1, q=1, dist="normal")
        fit_result = model.fit(disp="off")
        forecast = fit_result.forecast(horizon=1, reindex=False)
        variance = forecast.variance.to_numpy()[-1, 0]
        return float((variance**0.5) / 100)
    except Exception:
        logger.warning("GARCH fit failed", exc_info=True)
        return None


def _resolve_volatilities(
    returns: pd.DataFrame, tickers: list[str]
) -> tuple[dict[str, float], dict[str, str], dict[str, dict[str, float | None]]]:
    """
    Returns (daily_vol_per_ticker, source_per_ticker, all_estimates_per_ticker).
    Per ticker, prefers the trained LSTM's forecast when available and sane, then
    falls back to a GARCH(1,1) forecast when available and sane, then finally to
    plain historical daily std. `all_estimates` carries every method's annualized
    figure (where available) for side-by-side comparison, regardless of which one
    was actually used to drive the simulation.
    """
    historical_daily_vol = {t: float(returns[t].std()) for t in tickers}
    model = volatility_model.get_model()

    daily_vol: dict[str, float] = {}
    source: dict[str, str] = {}
    all_estimates: dict[str, dict[str, float | None]] = {}

    for ticker in tickers:
        historical = historical_daily_vol[ticker]
        series = returns[ticker]

        lstm_forecast = volatility_model.forecast_daily_volatility(model, series.to_numpy()) if model else None
        garch_forecast = _fit_garch_daily_vol(series)

        def annualized_pct(daily: float | None) -> float | None:
            return float(round(daily * np.sqrt(TRADING_DAYS_PER_YEAR) * 100, 2)) if daily is not None else None

        all_estimates[ticker] = {
            "historical": annualized_pct(historical),
            "garch": annualized_pct(garch_forecast),
            "lstm": annualized_pct(lstm_forecast),
        }

        if lstm_forecast is not None and 0 < lstm_forecast < historical * SANITY_MULTIPLE:
            daily_vol[ticker] = lstm_forecast
            source[ticker] = "lstm"
        elif garch_forecast is not None and 0 < garch_forecast < historical * SANITY_MULTIPLE:
            daily_vol[ticker] = garch_forecast
            source[ticker] = "garch"
        else:
            daily_vol[ticker] = historical
            source[ticker] = "historical"

    logger.info("Volatility sources: %s", source)
    logger.info("Volatility estimates (annualized %%): %s", all_estimates)
    return daily_vol, source, all_estimates


def run_monte_carlo(holdings: list[dict], shock_pct: float = 0.0) -> dict:
    """
    holdings: list of {"ticker": str, "shares": float}
    shock_pct: an optional immediate hypothetical price shock (e.g. -20 for a 20%
    market-wide drop) applied to every holding's starting price before simulating
    forward -- used for stress-test scenarios, 0.0 for a normal analysis.
    Returns annualized volatility per ticker, 30-day 95% VaR for the combined
    portfolio, and each ticker's percentage contribution to portfolio risk.
    """
    shares: dict[str, float] = {}
    for h in holdings:
        shares[h["ticker"]] = shares.get(h["ticker"], 0.0) + h["shares"]
    tickers = list(shares.keys())
    logger.info("Running Monte Carlo simulation for %s (shock_pct=%s)", tickers, shock_pct)

    prices = _download_price_history(tickers)
    prices = prices[tickers]
    returns = _log_returns(prices)

    daily_vol, volatility_source, volatility_estimates = _resolve_volatilities(returns, tickers)
    annual_vol = {t: daily_vol[t] * np.sqrt(TRADING_DAYS_PER_YEAR) for t in tickers}
    mean_daily_return = returns.mean()
    # Correlation is scale-free, so it's taken straight from history regardless of
    # which volatility source is used; only the per-ticker scale (the diagonal) can
    # come from the LSTM/GARCH forecast instead of the historical estimate.
    corr_matrix = returns.corr()
    vol_array = np.array([daily_vol[t] for t in tickers])
    vol_diag = np.diag(vol_array)
    cov_matrix_values = vol_diag @ corr_matrix.values @ vol_diag

    last_prices = prices.iloc[-1] * (1 + shock_pct / 100)
    shares_array = np.array([shares[t] for t in tickers])
    values = shares_array * last_prices.values
    portfolio_value = float(values.sum())
    weights = values / portfolio_value

    rng = np.random.default_rng(RANDOM_SEED)
    jitter = np.eye(len(tickers)) * 1e-12
    chol = np.linalg.cholesky(cov_matrix_values + jitter)

    portfolio_returns = np.empty(SIMULATION_PATHS)
    for path in range(SIMULATION_PATHS):
        z = rng.standard_normal((HORIZON_DAYS, len(tickers)))
        correlated_shocks = z @ chol.T
        daily_log_returns = mean_daily_return.values + correlated_shocks
        cumulative_log_return = daily_log_returns.sum(axis=0)
        end_prices = last_prices.values * np.exp(cumulative_log_return)
        end_value = float(np.sum(shares_array * end_prices))
        portfolio_returns[path] = (end_value - portfolio_value) / portfolio_value

    var_95 = -np.percentile(portfolio_returns, (1 - CONFIDENCE_LEVEL) * 100) * 100

    portfolio_variance = float(weights @ cov_matrix_values @ weights)
    marginal_contribution = cov_matrix_values @ weights
    component_contribution = weights * marginal_contribution
    risk_contributions = {
        tickers[i]: float(round((component_contribution[i] / portfolio_variance) * 100, 2))
        for i in range(len(tickers))
    }

    portfolio_annual_vol = float(np.sqrt(portfolio_variance * TRADING_DAYS_PER_YEAR))

    result = {
        "var_95": float(round(var_95, 2)),
        "risk_score": float(round(portfolio_annual_vol * 100, 2)),
        "portfolio_value": float(round(portfolio_value, 2)),
        "volatilities": {t: float(round(annual_vol[t] * 100, 2)) for t in tickers},
        "risk_contributions": risk_contributions,
        "allocation": {tickers[i]: float(round(weights[i] * 100, 2)) for i in range(len(tickers))},
        "values_usd": {tickers[i]: float(round(values[i], 2)) for i in range(len(tickers))},
        # Full simulated 30-day portfolio-return distribution (as %), for charting a histogram.
        "simulated_returns_pct": [float(round(r * 100, 4)) for r in portfolio_returns],
        # "lstm", "garch", or "historical" per ticker -- which estimate fed the simulation.
        "volatility_source": volatility_source,
        # Every method's annualized estimate per ticker, for side-by-side comparison.
        "volatility_estimates": volatility_estimates,
        "shock_pct": shock_pct,
    }
    logger.info(
        "Monte Carlo result: portfolio_value=%.2f var_95=%.2f%% risk_score=%.2f",
        portfolio_value,
        result["var_95"],
        result["risk_score"],
    )
    return result
