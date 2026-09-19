from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship

from app.core.database import Base


class RiskReport(Base):
    __tablename__ = "risk_reports"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    report_text = Column(Text, nullable=False)
    var_95 = Column(Float, nullable=False)
    risk_score = Column(Float, nullable=False)
    # Full structured output of services.risk.run_monte_carlo (volatilities,
    # allocation, risk contributions, simulated return distribution) so the
    # frontend can redraw charts for past reports without recomputing.
    risk_data = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="reports")
