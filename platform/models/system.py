"""System configuration singleton model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Boolean, func
from sqlalchemy.orm import Mapped, Session, mapped_column

from database import Base


class SystemConfig(Base):
    __tablename__ = "system_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    default_llm_credential_id: Mapped[int | None] = mapped_column(
        ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True
    )
    default_llm_model_name: Mapped[str] = mapped_column(String(255), default="")
    default_timezone: Mapped[str] = mapped_column(String(50), default="UTC")
    max_workflow_execution_seconds: Mapped[int] = mapped_column(Integer, default=600)
    confirmation_timeout_seconds: Mapped[int] = mapped_column(Integer, default=300)
    sandbox_code_execution: Mapped[bool] = mapped_column(Boolean, default=False)
    feature_flags: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    @classmethod
    def load(cls, db: Session) -> SystemConfig:
        obj = db.query(cls).filter_by(id=1).first()
        if not obj:
            obj = cls(id=1)
            db.add(obj)
            db.commit()
            db.refresh(obj)
        return obj
