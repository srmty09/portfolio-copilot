import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.holding import Holding
from app.models.report import RiskReport
from app.models.user import User
from app.services.agent import answer_question, generate_report
from app.services.backtest import backtest_var

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analysis"])


class ReportSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    var_95: float
    risk_score: float
    created_at: datetime


class ReportOut(ReportSummaryOut):
    report_text: str
    risk_data: dict


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str


def _current_holdings_data(db: Session, current_user: User) -> list[dict]:
    holdings = db.query(Holding).filter(Holding.user_id == current_user.id).all()
    if not holdings:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Add holdings first")
    return [{"ticker": h.ticker, "shares": h.shares} for h in holdings]


@router.post("/analyze", response_model=ReportOut)
def analyze_portfolio(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    holdings_data = _current_holdings_data(db, current_user)
    logger.info("User %d starting analysis of %d holding(s)", current_user.id, len(holdings_data))

    try:
        report_text, risk_data = generate_report(holdings_data)
    except ValueError as exc:
        logger.warning("Analysis failed for user %d: %s", current_user.id, exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception:
        logger.exception("Analysis failed unexpectedly for user %d", current_user.id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Analysis failed, please try again")

    report = RiskReport(
        user_id=current_user.id,
        report_text=report_text,
        var_95=risk_data["var_95"],
        risk_score=risk_data["risk_score"],
        risk_data=risk_data,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    logger.info("Saved report id=%d for user %d (var_95=%.2f%%)", report.id, current_user.id, report.var_95)
    return report


@router.post("/analyze/ask", response_model=AskResponse)
def ask_about_portfolio(
    payload: AskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Ask a free-text follow-up about the current holdings (e.g. a "what if" stress
    scenario). Not persisted as a RiskReport -- this is ephemeral, unlike /analyze.
    """
    holdings_data = _current_holdings_data(db, current_user)
    logger.info("User %d asking: %s", current_user.id, payload.question[:200])

    try:
        answer = answer_question(holdings_data, payload.question)
    except ValueError as exc:
        logger.warning("Ask failed for user %d: %s", current_user.id, exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception:
        logger.exception("Ask failed unexpectedly for user %d", current_user.id)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Could not answer, please try again")

    return AskResponse(answer=answer)


@router.get("/reports", response_model=list[ReportSummaryOut])
def list_reports(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Deliberately excludes risk_data (which carries a 1000-element simulated-return
    # array per report) -- fine for a single report's charts, unbounded for a list
    # that grows with every analysis. Fetch the full report via /reports/{id}.
    query = db.query(RiskReport)
    if current_user.role != "admin":
        query = query.filter(RiskReport.user_id == current_user.id)
    return query.order_by(RiskReport.created_at.desc()).all()


# Registered before /reports/{report_id} -- a static path segment must come first,
# otherwise FastAPI would match "backtest" as a report_id path param and 422 on the
# int conversion before this handler is ever reached.
@router.get("/reports/backtest")
def backtest_reports(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    query = db.query(RiskReport)
    if current_user.role != "admin":
        query = query.filter(RiskReport.user_id == current_user.id)
    reports = query.all()

    report_dicts = [
        {"id": r.id, "created_at": r.created_at, "var_95": r.var_95, "allocation": r.risk_data.get("allocation", {})}
        for r in reports
        if r.risk_data and r.risk_data.get("allocation")
    ]
    logger.info("User %d running VaR backtest over %d report(s)", current_user.id, len(report_dicts))
    return backtest_var(report_dicts)


@router.get("/reports/{report_id}", response_model=ReportOut)
def get_report(
    report_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    report = db.query(RiskReport).filter(RiskReport.id == report_id).first()
    if not report:
        logger.info("User %d requested missing report id=%d", current_user.id, report_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")
    if current_user.role != "admin" and report.user_id != current_user.id:
        logger.warning(
            "User %d denied access to report id=%d owned by user %d",
            current_user.id,
            report_id,
            report.user_id,
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to view this report")
    return report
