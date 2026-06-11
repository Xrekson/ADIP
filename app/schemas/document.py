from datetime import datetime
from pydantic import BaseModel
from app.models.document import DocumentStatus

class DocumentOut(BaseModel):
    id: str
    auction_id: str
    original_filename: str
    status: DocumentStatus
    lots_extracted: int
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
    model_config = {"from_attributes": True}