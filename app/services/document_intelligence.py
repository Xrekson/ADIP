"""
Wraps Azure AI Document Intelligence (formerly Form Recognizer).
Uses the prebuilt-layout model plus custom field extraction logic.
"""
import logging
from dataclasses import dataclass
from pathlib import Path

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from azure.core.credentials import AzureKeyCredential

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class ExtractedLot:
    lot_number: str
    title: str
    description: str
    estimated_value: float | None
    seller_name: str | None
    seller_contact: str | None


def _get_client() -> DocumentIntelligenceClient:
    return DocumentIntelligenceClient(
        endpoint=settings.AZURE_DI_ENDPOINT,
        credential=AzureKeyCredential(settings.AZURE_DI_KEY),
    )


async def extract_auction_data(file_bytes: bytes, content_type: str) -> list[ExtractedLot]:
    """
    Send a document to Azure Document Intelligence and return structured lot data.

    Strategy:
      1. Use `prebuilt-layout` to get the full key-value table structure.
      2. Parse tables looking for auction-specific column patterns.
      3. Fall back to a keyword scan over key-value pairs for loose documents.
    """
    import asyncio

    client = _get_client()

    # Run the blocking SDK call in a thread pool to stay async
    loop = asyncio.get_event_loop()
    poller = await loop.run_in_executor(
        None,
        lambda: client.begin_analyze_document(
            model_id="prebuilt-layout",
            analyze_request=AnalyzeDocumentRequest(bytes_source=file_bytes),
            content_type=content_type,           # "application/pdf" or "image/jpeg" etc.
        ),
    )
    result = await loop.run_in_executor(None, poller.result)

    lots: list[ExtractedLot] = []

    # ── Strategy 1: Parse structured tables ──────────────────────────────────
    if result.tables:
        for table in result.tables:
            header_map: dict[int, str] = {}   # col_index → header name (lowercased)
            row_data: dict[int, dict[str, str]] = {}

            for cell in table.cells:
                text = (cell.content or "").strip()
                if cell.row_index == 0:
                    header_map[cell.column_index] = text.lower()
                else:
                    row_data.setdefault(cell.row_index, {})
                    col_name = header_map.get(cell.column_index, f"col_{cell.column_index}")
                    row_data[cell.row_index][col_name] = text

            # Only process tables that look like auction lot tables
            if not any(k in header_map.values() for k in ("lot", "lot no", "lot number", "lot #")):
                continue

            for row in row_data.values():
                lot = _row_to_lot(row)
                if lot:
                    lots.append(lot)

    # ── Strategy 2: Key-value pairs fallback ────────────────────────────────
    if not lots and result.key_value_pairs:
        kv: dict[str, str] = {}
        for pair in result.key_value_pairs:
            if pair.key and pair.value:
                kv[pair.key.content.lower()] = pair.value.content

        lot = _kv_to_lot(kv)
        if lot:
            lots.append(lot)

    logger.info("Extracted %d lots from document", len(lots))
    return lots


# ── Helpers ──────────────────────────────────────────────────────────────────

def _row_to_lot(row: dict[str, str]) -> ExtractedLot | None:
    """Map a table row (header → value) to an ExtractedLot."""

    def _find(keys: list[str]) -> str | None:
        for k in keys:
            for row_key, val in row.items():
                if k in row_key:
                    return val.strip() or None
        return None

    lot_number = _find(["lot no", "lot #", "lot number", "lot"])
    title = _find(["title", "item", "description", "name"])

    if not lot_number or not title:
        return None

    raw_value = _find(["estimate", "value", "est.", "reserve"])
    estimated_value = _parse_currency(raw_value)

    return ExtractedLot(
        lot_number=lot_number,
        title=title,
        description=_find(["description", "details", "notes"]) or title,
        estimated_value=estimated_value,
        seller_name=_find(["seller", "vendor", "consignor"]),
        seller_contact=_find(["contact", "email", "phone"]),
    )


def _kv_to_lot(kv: dict[str, str]) -> ExtractedLot | None:
    lot_number = kv.get("lot") or kv.get("lot number") or kv.get("lot no")
    title = kv.get("title") or kv.get("item") or kv.get("description")
    if not lot_number or not title:
        return None
    return ExtractedLot(
        lot_number=lot_number,
        title=title,
        description=kv.get("description") or title,
        estimated_value=_parse_currency(kv.get("estimate") or kv.get("value")),
        seller_name=kv.get("seller") or kv.get("consignor"),
        seller_contact=kv.get("contact") or kv.get("email"),
    )


def _parse_currency(raw: str | None) -> float | None:
    if not raw:
        return None
    cleaned = raw.replace("$", "").replace(",", "").replace("£", "").strip()
    # Handle ranges like "500–1000" → take lower bound
    if "–" in cleaned or "-" in cleaned:
        cleaned = cleaned.replace("–", "-").split("-")[0].strip()
    try:
        return float(cleaned)
    except ValueError:
        return None