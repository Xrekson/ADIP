"""
Producer: enqueue a document job message.
Consumer: used by the background worker loop.
"""
import json
import logging
from typing import Any

from azure.servicebus import ServiceBusClient, ServiceBusMessage
from azure.servicebus.aio import ServiceBusClient as AsyncServiceBusClient

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# ── Producer (called from the upload API route) ───────────────────────────────

def enqueue_document_job(payload: dict[str, Any]) -> None:
    """
    Synchronously enqueue a job message.
    payload should include: { "document_id": "...", "auction_id": "...", "blob_path": "..." }
    """
    with ServiceBusClient.from_connection_string(settings.AZURE_SB_CONNECTION_STRING) as client:
        with client.get_queue_sender(settings.AZURE_SB_QUEUE_NAME) as sender:
            message = ServiceBusMessage(
                body=json.dumps(payload),
                content_type="application/json",
                subject="document-processing",
            )
            sender.send_messages(message)
            logger.info("Enqueued document job: %s", payload.get("document_id"))


# ── Consumer (used inside the async worker) ───────────────────────────────────

class DocumentJobConsumer:
    """
    Async Service Bus receiver.
    Call `start()` once at startup, then iterate `receive_jobs()` in a loop.
    """

    def __init__(self):
        self._client: AsyncServiceBusClient | None = None
        self._receiver = None

    async def start(self) -> None:
        self._client = AsyncServiceBusClient.from_connection_string(
            settings.AZURE_SB_CONNECTION_STRING
        )
        self._receiver = self._client.get_queue_receiver(
            queue_name=settings.AZURE_SB_QUEUE_NAME,
            max_wait_time=5,     # seconds to wait for messages
        )
        logger.info("Service Bus consumer started, listening on '%s'", settings.AZURE_SB_QUEUE_NAME)

    async def receive_jobs(self) -> list[tuple[Any, dict]]:
        """
        Returns a list of (raw_message, payload_dict) tuples.
        The caller must call complete_job() or abandon_job() for each message.
        """
        if not self._receiver:
            raise RuntimeError("Consumer not started — call start() first")

        results = []
        async with self._receiver:
            async for msg in self._receiver:
                body = b"".join(msg.body)
                payload = json.loads(body)
                results.append((msg, payload))
                if len(results) >= 10:   # process in batches of up to 10
                    break
        return results

    async def complete_job(self, msg) -> None:
        await self._receiver.complete_message(msg)

    async def abandon_job(self, msg) -> None:
        await self._receiver.abandon_message(msg)

    async def stop(self) -> None:
        if self._client:
            await self._client.close()