from pydantic import BaseModel
from datetime import datetime

class BidCreate(BaseModel):
    amount: float

class BidOut(BaseModel):
    id: str
    lot_id: str
    amount: float
    placed_at: datetime
    model_config = {"from_attributes": True}