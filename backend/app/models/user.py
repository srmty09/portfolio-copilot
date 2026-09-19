from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    # Nullable: a Google-only account has no local password.
    hashed_password = Column(String, nullable=True)
    auth_provider = Column(String, nullable=False, default="local")  # "local" or "google"
    google_id = Column(String, unique=True, nullable=True, index=True)
    role = Column(String, nullable=False, default="user")
    reset_token = Column(String, nullable=True, index=True)
    reset_token_expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    holdings = relationship("Holding", back_populates="owner", cascade="all, delete-orphan")
    reports = relationship("RiskReport", back_populates="owner", cascade="all, delete-orphan")
