import enum, uuid
from datetime import datetime
from sqlalchemy import String, Float, DateTime, ForeignKey, Enum as SAEnum, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

class AuctionStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    CLOSED = "closed"

class Auction(Base):
    __tablename__ = "auctions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[AuctionStatus] = mapped_column(SAEnum(AuctionStatus), default=AuctionStatus.DRAFT)
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    auctioneer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))

    auctioneer = relationship("User", back_populates="auctions")
    lots = relationship("Lot", back_populates="auction", cascade="all, delete-orphan")

class Lot(Base):
    __tablename__ = "lots"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    auction_id: Mapped[str] = mapped_column(ForeignKey("auctions.id"))
    lot_number: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String)
    estimated_value: Mapped[float] = mapped_column(Float, nullable=True)
    seller_name: Mapped[str] = mapped_column(String, nullable=True)
    seller_contact: Mapped[str] = mapped_column(String, nullable=True)
    current_bid: Mapped[float] = mapped_column(Float, default=0.0)

    auction = relationship("Auction", back_populates="lots")
    bids = relationship("Bid", back_populates="lot")

class Bid(Base):
    __tablename__ = "bids"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    lot_id: Mapped[str] = mapped_column(ForeignKey("lots.id"))
    bidder_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    placed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lot = relationship("Lot", back_populates="bids")
    bidder = relationship("User", back_populates="bids")