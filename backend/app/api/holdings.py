import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.holding import Holding
from app.models.user import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/holdings", tags=["holdings"])


class HoldingCreate(BaseModel):
    ticker: str
    shares: float


class HoldingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker: str
    shares: float
    added_at: datetime


@router.post("", response_model=HoldingOut)
def add_holding(
    payload: HoldingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    holding = Holding(user_id=current_user.id, ticker=payload.ticker.upper(), shares=payload.shares)
    db.add(holding)
    db.commit()
    db.refresh(holding)
    logger.info("User %d added holding %s x%s (id=%d)", current_user.id, holding.ticker, holding.shares, holding.id)
    return holding


@router.get("", response_model=list[HoldingOut])
def list_holdings(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Holding).filter(Holding.user_id == current_user.id).all()


@router.delete("/{holding_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_holding(
    holding_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    holding = (
        db.query(Holding)
        .filter(Holding.id == holding_id, Holding.user_id == current_user.id)
        .first()
    )
    if not holding:
        logger.info("User %d tried to delete missing holding id=%d", current_user.id, holding_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Holding not found")
    db.delete(holding)
    db.commit()
    logger.info("User %d deleted holding %s (id=%d)", current_user.id, holding.ticker, holding_id)
