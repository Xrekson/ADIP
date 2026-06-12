from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import get_db
from app.models.auction import Auction, Lot, AuctionStatus
from app.models.user import UserRole
from app.api.deps import require_role
from app.schemas.auction import AuctionCreate, AuctionOut, LotOut

router = APIRouter(prefix="/api/auctions", tags=["auctions"])


@router.post("/", response_model=AuctionOut, status_code=status.HTTP_201_CREATED)
async def create_auction(
    payload: AuctionCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_role(UserRole.AUCTIONEER, UserRole.ADMIN)),
):
    """Create a new draft auction (Restricted to Auctioneers and Admins)."""
    auction = Auction(
        title=payload.title,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
        auctioneer_id=current_user.id,
        status=AuctionStatus.DRAFT
    )
    db.add(auction)
    await db.commit()
    await db.refresh(auction)
    return auction


@router.get("/", response_model=list[AuctionOut])
async def list_auctions(
    status: AuctionStatus | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve all auctions, optionally filtered by status."""
    stmt = select(Auction)
    if status:
        stmt = stmt.where(Auction.status == status)
    
    # Order by soonest ending
    stmt = stmt.order_by(Auction.ends_at.asc())
    
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{auction_id}", response_model=AuctionOut)
async def get_auction(
    auction_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get the details of a specific auction."""
    result = await db.execute(select(Auction).where(Auction.id == auction_id))
    auction = result.scalar_one_or_none()
    
    if not auction:
        raise HTTPException(status_code=404, detail="Auction not found")
    
    return auction


@router.get("/{auction_id}/lots", response_model=list[LotOut])
async def get_auction_lots(
    auction_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get all lots belonging to a specific auction."""
    # First verify the auction exists
    auction_result = await db.execute(select(Auction).where(Auction.id == auction_id))
    if not auction_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Auction not found")

    # Fetch the lots, ordered by lot number
    stmt = select(Lot).where(Lot.auction_id == auction_id).order_by(Lot.lot_number)
    result = await db.execute(stmt)
    return result.scalars().all()