# app/workers/document_worker.py  — updated for ExtractionResult return type
import asyncio
import logging
from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.websockets.manager import ws_manager
from app.database import AsyncSessionLocal
from app.models.auction import Auction, Lot
from app.models.document import DocumentStatus, ProcessedDocument
from app.services.document_intelligence import ExtractionResult, extract_auction_data
from app.services.service_bus import DocumentJobConsumer

logger = logging.getLogger(__name__)
consumer = DocumentJobConsumer()


async def process_single_job(
    session: AsyncSession,
    document_id: str,
    blob_path: str,
    auction_id: str,
):
    # ① Mark PROCESSING + notify frontend
    await session.execute(
        update(ProcessedDocument)
        .where(ProcessedDocument.id == document_id)
        .values(status=DocumentStatus.PROCESSING)
    )
    await session.commit()
    await ws_manager.broadcast_to_auction(
        auction_id,
        {
            "event": "document_status",
            "document_id": document_id,
            "status": "processing",
        },
    )

    try:
        # ② Read file
        with open(blob_path, "rb") as f:
            file_bytes = f.read()
        content_type = (
            "application/pdf" if blob_path.lower().endswith(".pdf") else "image/jpeg"
        )

        # ③ Azure Document Intelligence — returns ExtractionResult(metadata, lots)
        extraction: ExtractionResult = await extract_auction_data(
            file_bytes, content_type
        )
        metadata = extraction.metadata
        lots = extraction.lots

        # ④ Backfill catalogue metadata onto the Auction row
        if any(
            [
                metadata.catalogue_name,
                metadata.catalogue_code,
                metadata.mandate_number,
                metadata.auction_type,
            ]
        ):
            await session.execute(
                update(Auction)
                .where(Auction.id == auction_id)
                .values(
                    catalogue_name=metadata.catalogue_name or None,
                    catalogue_code=metadata.catalogue_code or None,
                    mandate_number=metadata.mandate_number or None,
                    auction_type=metadata.auction_type or None,
                )
            )

        # ⑤ Insert extracted Lot rows
        lot_objects = [
            Lot(
                auction_id=auction_id,
                lot_number=lot.lot_number,
                title=lot.title,
                description=lot.description,
                quantity=lot.quantity,
                unit_of_measure=lot.unit_of_measure,
                material_number=lot.material_number,
                location=lot.location,
                gst_percentage=lot.gst_percentage,
                tcs_percentage=lot.tcs_percentage,
                emd_schedule=lot.emd_schedule,
                instalment_1=lot.instalment_1,
                lifting_days_1=lot.lifting_days_1,
                estimated_value=lot.estimated_value,
                seller_name=lot.seller_name,
                seller_contact=lot.seller_contact,
            )
            for lot in lots
        ]
        session.add_all(lot_objects)

        # ⑥ Mark COMPLETED
        await session.execute(
            update(ProcessedDocument)
            .where(ProcessedDocument.id == document_id)
            .values(
                status=DocumentStatus.COMPLETED,
                lots_extracted=len(lot_objects),
                completed_at=datetime.utcnow(),
            )
        )
        await session.commit()

        # ⑦ Broadcast success to WebSocket subscribers
        await ws_manager.broadcast_to_auction(
            auction_id,
            {
                "event": "document_status",
                "document_id": document_id,
                "status": "completed",
                "lots_extracted": len(lot_objects),
                # Catalogue metadata for the frontend to display immediately
                "metadata": {
                    "catalogue_name": metadata.catalogue_name,
                    "catalogue_code": metadata.catalogue_code,
                    "mandate_number": metadata.mandate_number,
                    "seller": metadata.seller,
                    "auction_date": metadata.auction_date,
                    "auction_type": metadata.auction_type,
                    "security_deposit": metadata.security_deposit,
                    "bid_increment": metadata.bid_increment,
                    "bid_duration": metadata.bid_duration,
                },
                # Preview of first 5 lots for the live feed
                "lots": [
                    {
                        "lot_number": l.lot_number,
                        "title": l.title,
                        "quantity": l.quantity,
                        "unit_of_measure": l.unit_of_measure,
                        "location": l.location,
                        "gst_percentage": l.gst_percentage,
                    }
                    for l in lots[:5]
                ],
            },
        )

    except Exception as exc:
        logger.exception("Failed to process document %s", document_id)
        await session.execute(
            update(ProcessedDocument)
            .where(ProcessedDocument.id == document_id)
            .values(status=DocumentStatus.FAILED, error_message=str(exc))
        )
        await session.commit()
        await ws_manager.broadcast_to_auction(
            auction_id,
            {
                "event": "document_status",
                "document_id": document_id,
                "status": "failed",
                "error": str(exc),
            },
        )


async def run_worker():
    await consumer.start()
    logger.info("Document worker started")

    while True:
        try:
            jobs = await consumer.receive_jobs()
            if not jobs:
                await asyncio.sleep(2)
                continue

            for raw_msg, payload in jobs:
                async with AsyncSessionLocal() as session:
                    try:
                        await process_single_job(
                            session=session,
                            document_id=payload["document_id"],
                            blob_path=payload["blob_path"],
                            auction_id=payload["auction_id"],
                        )
                        await consumer.complete_job(raw_msg)
                    except Exception:
                        logger.exception("Worker job failed, abandoning message")
                        await consumer.abandon_job(raw_msg)

        except asyncio.CancelledError:
            logger.info("Worker shutting down")
            await consumer.stop()
            break
        except Exception:
            logger.exception("Unexpected worker error, retrying in 5s")
            await asyncio.sleep(5)
