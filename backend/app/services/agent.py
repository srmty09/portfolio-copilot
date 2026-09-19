import json
import logging
import time

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from app.core.config import settings
from app.services import rag, risk

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a portfolio risk analyst. You have access to three tools: `calculate_risk`, which returns "
    "structured volatility, Value-at-Risk, and risk-contribution data for the user's current holdings; "
    "`retrieve_context`, which returns short reference passages about risk, diversification, or "
    "volatility, plus recent news headlines for the specific holdings in this portfolio; and "
    "`simulate_scenario`, which re-runs the simulation under a hypothetical market shock and/or a "
    "hypothetical added position, without changing the user's real saved holdings. Always call "
    "calculate_risk first, then call retrieve_context at least once with a query about the portfolio's "
    "biggest risk driver -- call it again with a query naming a specific holding if you want news on it. "
    "Only call simulate_scenario if the user is specifically asking about a hypothetical change (a market "
    "move, adding or removing a position); skip it for a plain portfolio analysis. Then write a "
    "plain-English answer for a non-expert investor: summarize the portfolio's volatility and 95 percent "
    "Value at Risk, name the holdings driving the most risk, mention any retrieved news that's relevant "
    "to those holdings' risk, and cite the retrieved context to explain any concept you reference. Keep "
    "it concise and avoid unexplained jargon. All volatility, VaR, and risk-contribution figures are "
    "percentages, not dollar amounts — e.g. a var_95_pct_of_portfolio of 10.79 means a 5% chance of "
    "losing more than 10.79% of total portfolio value, not $10.79. Convert to a dollar figure yourself "
    "using portfolio_value_usd if that is clearer for the reader, but never state the raw percentage "
    "number as a dollar amount. Some per-ticker volatility figures may come from a trained forecasting "
    "model or a GARCH model rather than plain historical data (see per_ticker_volatility_source) -- you "
    "can mention this in passing but don't dwell on it."
)


def _build_tools(holdings: list[dict], risk_data: dict) -> list:
    tickers = list(dict.fromkeys(h["ticker"] for h in holdings))

    @tool
    def calculate_risk(query: str = "portfolio risk") -> str:
        """Return structured risk metrics (volatilities, 95% VaR, risk contributions) for the user's portfolio."""
        logger.info("Agent tool call: calculate_risk(query=%r)", query)
        return json.dumps(
            {
                "portfolio_value_usd": risk_data["portfolio_value"],
                "var_95_pct_of_portfolio": risk_data["var_95"],
                "risk_score_annualized_volatility_pct": risk_data["risk_score"],
                "per_ticker_annualized_volatility_pct": risk_data["volatilities"],
                "per_ticker_risk_contribution_pct": risk_data["risk_contributions"],
                "per_ticker_volatility_source": risk_data["volatility_source"],
            }
        )

    @tool
    def retrieve_context(query: str) -> str:
        """Retrieve short reference passages about market risk, volatility, diversification, or recent
        news for the specific holdings in this portfolio."""
        logger.info("Agent tool call: retrieve_context(query=%r)", query)
        chunks = rag.retrieve(query, tickers=tickers)
        return "\n\n".join(chunks)

    @tool
    def simulate_scenario(shock_pct: float = 0.0, additional_ticker: str = "", additional_shares: float = 0.0) -> str:
        """Re-run the risk simulation under a hypothetical change, without altering the user's saved
        holdings. Use shock_pct for an immediate market-wide price shock applied to every current holding
        (e.g. -20 for a 20% drop, 10 for a 10% rally). Use additional_ticker together with
        additional_shares to see the effect of hypothetically adding a new position alongside the current
        holdings (e.g. additional_ticker="TSLA", additional_shares=10). Either or both may be used."""
        logger.info(
            "Agent tool call: simulate_scenario(shock_pct=%s, additional_ticker=%r, additional_shares=%s)",
            shock_pct,
            additional_ticker,
            additional_shares,
        )
        scenario_holdings = list(holdings)
        if additional_ticker and additional_shares:
            scenario_holdings = scenario_holdings + [{"ticker": additional_ticker.upper(), "shares": additional_shares}]
        try:
            scenario_result = risk.run_monte_carlo(scenario_holdings, shock_pct=shock_pct)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        return json.dumps(
            {
                "scenario_portfolio_value_usd": scenario_result["portfolio_value"],
                "scenario_var_95_pct_of_portfolio": scenario_result["var_95"],
                "scenario_risk_score_annualized_volatility_pct": scenario_result["risk_score"],
                "scenario_per_ticker_risk_contribution_pct": scenario_result["risk_contributions"],
                "baseline_portfolio_value_usd": risk_data["portfolio_value"],
                "baseline_var_95_pct_of_portfolio": risk_data["var_95"],
            }
        )

    return [calculate_risk, retrieve_context, simulate_scenario]


def _run_agent(holdings: list[dict], risk_data: dict, user_message: str) -> str:
    tools = _build_tools(holdings, risk_data)
    llm = ChatOpenAI(
        model=settings.DEEPSEEK_MODEL,
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
        temperature=0.3,
    )
    agent = create_react_agent(llm, tools, prompt=SYSTEM_PROMPT)

    logger.info("Invoking agent (model=%s): %s", settings.DEEPSEEK_MODEL, user_message[:200])
    start = time.monotonic()
    try:
        result = agent.invoke({"messages": [("user", user_message)]})
    except Exception:
        logger.exception("Agent invocation failed")
        raise
    elapsed = time.monotonic() - start
    answer = result["messages"][-1].content
    logger.info("Agent finished in %.1fs, response length=%d chars", elapsed, len(answer))
    return answer


def generate_report(holdings: list[dict]) -> tuple[str, dict]:
    """
    holdings: list of {"ticker": str, "shares": float}
    Returns (report_text, risk_data) where risk_data is the same structured
    dict produced by services.risk.run_monte_carlo.
    """
    risk_data = risk.run_monte_carlo(holdings)
    tickers_summary = ", ".join(f"{h['ticker']} ({h['shares']} shares)" for h in holdings)
    user_message = f"Analyze the risk of my portfolio: {tickers_summary}."
    report_text = _run_agent(holdings, risk_data, user_message)
    return report_text, risk_data


def answer_question(holdings: list[dict], question: str) -> str:
    """
    holdings: list of {"ticker": str, "shares": float} -- the user's real, saved holdings.
    question: a free-text question, e.g. "what if the market drops 20%?" or
    "what happens if I add 10 shares of TSLA?". Not persisted as a RiskReport --
    this is an ephemeral, ask-anything follow-up, not the primary saved analysis.
    """
    risk_data = risk.run_monte_carlo(holdings)
    tickers_summary = ", ".join(f"{h['ticker']} ({h['shares']} shares)" for h in holdings)
    user_message = (
        f"My current portfolio is: {tickers_summary}. {question}\n\n"
        "If this describes a hypothetical change (a market move, adding or removing a position), use "
        "simulate_scenario to actually compute it rather than guessing, and compare the result to the "
        "current baseline from calculate_risk."
    )
    return _run_agent(holdings, risk_data, user_message)
