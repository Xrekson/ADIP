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
    Call `stop()` on shutdown to cleanly close the receiver and client.
    """

    # How many messages to pull per batch and how long to wait for them.
    _BATCH_SIZE = 10
    _WAIT_SECONDS = 5

    def __init__(self):
        self._client: AsyncServiceBusClient | None = None
        self._receiver = None

    async def start(self) -> None:
        self._client = AsyncServiceBusClient.from_connection_string(
            settings.AZURE_SB_CONNECTION_STRING
        )
        # FIX: store the receiver but do NOT enter it as a context manager here.
        # The receiver is opened lazily on first use and must remain open across
        # multiple receive_jobs() calls.  It is closed explicitly in stop().
        self._receiver = self._client.get_queue_receiver(
            queue_name=settings.AZURE_SB_QUEUE_NAME,
            max_wait_time=self._WAIT_SECONDS,
        )
        logger.info(
            "Service Bus consumer started, listening on '%s'",
            settings.AZURE_SB_QUEUE_NAME,
        )

    async def receive_jobs(self) -> list[tuple[Any, dict]]:
        """
        Returns a list of (raw_message, payload_dict) tuples.
        The caller must call complete_job() or abandon_job() for each message.
        Returns an empty list when no messages arrive within the wait window.
        """
        if self._receiver is None:
            raise RuntimeError("Consumer not started — call start() first")

        # FIX: do NOT wrap in `async with self._receiver`.
        # That context manager calls receiver.close() on exit, permanently
        # killing the receiver.  We call receive_messages() directly instead
        # so the receiver stays alive for the next iteration and for
        # complete_job() / abandon_job() calls that follow.
        raw_messages = await self._receiver.receive_messages(
            max_message_count=self._BATCH_SIZE,
            max_wait_time=self._WAIT_SECONDS,
        )

        results: list[tuple[Any, dict]] = []
        for msg in raw_messages:
            body = b"".join(msg.body)
            payload = json.loads(body)
            results.append((msg, payload))

        return results

    async def complete_job(self, msg) -> None:
        """Mark a message as successfully processed (removes it from the queue)."""
        if self._receiver is None:
            raise RuntimeError("Consumer not started — call start() first")
        await self._receiver.complete_message(msg)

    async def abandon_job(self, msg) -> None:
        """Return a message to the queue so it can be retried."""
        if self._receiver is None:
            raise RuntimeError("Consumer not started — call start() first")
        await self._receiver.abandon_message(msg)

    async def stop(self) -> None:
        # FIX: close the receiver explicitly before closing the client,
        # otherwise the AMQP link is leaked.
        if self._receiver is not None:
            await self._receiver.close()
            self._receiver = None
        if self._client is not None:
            await self._client.close()
            self._client = None
        logger.info("Service Bus consumer stopped")