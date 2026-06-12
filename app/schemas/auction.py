from pydantic import BaseModel
from datetime import datetime
from app.models.auction import AuctionStatus

# --- Existing Bid Schemas ---
class BidCreate(BaseModel):
    amount: float

class BidOut(BaseModel):
    id: str
    lot_id: str
    amount: float
    placed_at: datetime
    model_config = {"from_attributes": True}

# --- New Auction Schemas ---
class AuctionCreate(BaseModel):
    title: str
    starts_at: datetime
    ends_at: datetime

class AuctionOut(BaseModel):
    id: str
    title: str
    status: AuctionStatus
    starts_at: datetime
    ends_at: datetime
    auctioneer_id: str
    model_config = {"from_attributes": True}

# --- New Lot Schemas ---
class LotOut(BaseModel):
    id: str
    auction_id: str
    lot_number: str
    title: str
    description: str | None
    estimated_value: float | None
    current_bid: float
    model_config = {"from_attributes": True}