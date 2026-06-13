# app/models/auction.py  — updated to carry new lot fields
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AuctionStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    CLOSED = "closed"


class Auction(Base):
    __tablename__ = "auctions"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[AuctionStatus] = mapped_column(
        SAEnum(AuctionStatus), default=AuctionStatus.DRAFT
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    auctioneer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    # Catalogue-level metadata extracted from the document
    catalogue_name: Mapped[str] = mapped_column(String, nullable=True)
    catalogue_code: Mapped[str] = mapped_column(String, nullable=True)
    mandate_number: Mapped[str] = mapped_column(String, nullable=True)
    auction_type: Mapped[str] = mapped_column(
        String, nullable=True
    )  # e.g. "Dynamic Sealbid"

    auctioneer = relationship("User", back_populates="auctions")
    lots = relationship("Lot", back_populates="auction", cascade="all, delete-orphan")


class Lot(Base):
    __tablename__ = "lots"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    auction_id: Mapped[str] = mapped_column(ForeignKey("auctions.id"))
    lot_number: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)

    # ── New fields from real mjunction catalogue format ───────────────────────
    quantity: Mapped[float] = mapped_column(Float, nullable=True)  # e.g. 11000.0
    unit_of_measure: Mapped[str] = mapped_column(
        String, nullable=True
    )  # "KG", "MT", "NOS"
    material_number: Mapped[str] = mapped_column(
        String, nullable=True
    )  # SAP material code
    location: Mapped[str] = mapped_column(String, nullable=True)  # yard / plant
    gst_percentage: Mapped[float] = mapped_column(Float, nullable=True)  # 18.0
    tcs_percentage: Mapped[float] = mapped_column(Float, nullable=True)  # 2.0 or 0.1
    emd_schedule: Mapped[str] = mapped_column(String, nullable=True)  # "1 Working day"
    instalment_1: Mapped[str] = mapped_column(
        String, nullable=True
    )  # "10% of lot value. 2 Working days"
    lifting_days_1: Mapped[str] = mapped_column(
        String, nullable=True
    )  # "5 Working Days"

    # ── Legacy / Western-catalogue fields (kept for compatibility) ───────────
    estimated_value: Mapped[float] = mapped_column(
        Float, nullable=True
    )  # None for mjunction
    seller_name: Mapped[str] = mapped_column(String, nullable=True)
    seller_contact: Mapped[str] = mapped_column(String, nullable=True)

    # ── Bidding state ────────────────────────────────────────────────────────
    current_bid: Mapped[float] = mapped_column(Float, default=0.0)

    auction = relationship("Auction", back_populates="lots")
    bids = relationship("Bid", back_populates="lot")


class Bid(Base):
    __tablename__ = "bids"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    lot_id: Mapped[str] = mapped_column(ForeignKey("lots.id"))
    bidder_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    placed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )

    lot = relationship("Lot", back_populates="bids")
    bidder = relationship("User", back_populates="bids")
