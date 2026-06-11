from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import get_db
from app.models.auction import Bid, Lot, AuctionStatus, Auction
from app.models.user import UserRole
from app.api.deps import require_role
from app.api.websockets.manager import ws_manager
from app.schemas.auction import BidCreate, BidOut

router = APIRouter(prefix="/api/bids", tags=["bids"])


@router.post("/{lot_id}", response_model=BidOut, status_code=201)
async def place_bid(
    lot_id: str,
    payload: BidCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role(UserRole.BIDDER)),
):
    # Fetch lot + its auction
    result = await db.execute(
        select(Lot, Auction)
        .join(Auction, Lot.auction_id == Auction.id)
        .where(Lot.id == lot_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Lot not found")
    lot, auction = row

    if auction.status != AuctionStatus.ACTIVE:
        raise HTTPException(status_code=400, detail="Auction is not active")

    if payload.amount <= lot.current_bid:
        raise HTTPException(
            status_code=400,
            detail=f"Bid must exceed current bid of {lot.current_bid}"
        )

    # Save bid and update lot's current_bid
    bid = Bid(lot_id=lot_id, bidder_id=current_user.id, amount=payload.amount)
    lot.current_bid = payload.amount
    db.add(bid)
    await db.commit()
    await db.refresh(bid)

    # Broadcast live bid notification to all subscribers of this auction
    await ws_manager.broadcast_to_auction(auction.id, {
        "event": "new_bid",
        "lot_id": lot_id,
        "lot_number": lot.lot_number,
        "amount": payload.amount,
        "bidder": current_user.full_name,
    })

    return bid