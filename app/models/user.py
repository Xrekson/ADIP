import enum
from sqlalchemy import String, Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
import uuid

class UserRole(str, enum.Enum):
    ADMIN = "admin"
    AUCTIONEER = "auctioneer"
    BIDDER = "bidder"

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    full_name: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), default=UserRole.BIDDER)
    is_active: Mapped[bool] = mapped_column(default=True)

    auctions = relationship("Auction", back_populates="auctioneer")
    bids = relationship("Bid", back_populates="bidder")