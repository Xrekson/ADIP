import enum, uuid
from datetime import datetime
from sqlalchemy import String, DateTime, ForeignKey, Enum as SAEnum, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class DocumentStatus(str, enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class ProcessedDocument(Base):
    __tablename__ = "processed_documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    auction_id: Mapped[str] = mapped_column(ForeignKey("auctions.id"))
    uploaded_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    original_filename: Mapped[str] = mapped_column(String)
    blob_path: Mapped[str] = mapped_column(String)          # local temp path or Azure Blob URL
    status: Mapped[DocumentStatus] = mapped_column(SAEnum(DocumentStatus), default=DocumentStatus.QUEUED)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    lots_extracted: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)