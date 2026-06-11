"""
Runs as an asyncio task started at app startup.
Dequeues messages → calls Azure Document Intelligence → saves lots to PostgreSQL
→ broadcasts status via WebSocket.
"""
import asyncio
import logging
from datetime import datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.document import ProcessedDocument, DocumentStatus
from app.models.auction import Lot
from app.services.document_intelligence import extract_auction_data
from app.services.service_bus import DocumentJobConsumer
from app.api.websockets.manager import ws_manager

logger = logging.getLogger(__name__)
consumer = DocumentJobConsumer()


async def process_single_job(session: AsyncSession, document_id: str, blob_path: str, auction_id: str):
    """Core processing logic for a single document job."""

    # ① Mark as PROCESSING and broadcast to WebSocket subscribers
    await session.execute(
        update(ProcessedDocument)
        .where(ProcessedDocument.id == document_id)
        .values(status=DocumentStatus.PROCESSING)
    )
    await session.commit()
    await ws_manager.broadcast_to_auction(auction_id, {
        "event": "document_status",
        "document_id": document_id,
        "status": "processing",
    })

    try:
        # ② Read file bytes from disk (or Azure Blob in production)
        with open(blob_path, "rb") as f:
            file_bytes = f.read()

        content_type = "application/pdf" if blob_path.endswith(".pdf") else "image/jpeg"

        # ③ Call Azure Document Intelligence
        extracted_lots = await extract_auction_data(file_bytes, content_type)

        # ④ Persist extracted lots to PostgreSQL
        lot_objects = [
            Lot(
                auction_id=auction_id,
                lot_number=lot.lot_number,
                title=lot.title,
                description=lot.description,
                estimated_value=lot.estimated_value,
                seller_name=lot.seller_name,
                seller_contact=lot.seller_contact,
            )
            for lot in extracted_lots
        ]
        session.add_all(lot_objects)

        # ⑤ Mark COMPLETED
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

        # ⑥ Broadcast success + extracted lot data
        await ws_manager.broadcast_to_auction(auction_id, {
            "event": "document_status",
            "document_id": document_id,
            "status": "completed",
            "lots_extracted": len(lot_objects),
            "lots": [
                {
                    "lot_number": l.lot_number,
                    "title": l.title,
                    "estimated_value": l.estimated_value,
                }
                for l in extracted_lots
            ],
        })

    except Exception as exc:
        logger.exception("Failed to process document %s", document_id)
        await session.execute(
            update(ProcessedDocument)
            .where(ProcessedDocument.id == document_id)
            .values(status=DocumentStatus.FAILED, error_message=str(exc))
        )
        await session.commit()
        await ws_manager.broadcast_to_auction(auction_id, {
            "event": "document_status",
            "document_id": document_id,
            "status": "failed",
            "error": str(exc),
        })


async def run_worker():
    """Main worker loop — runs indefinitely until cancelled."""
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