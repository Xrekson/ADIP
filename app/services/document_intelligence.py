# app/services/document_intelligence.py
"""
Azure AI Document Intelligence extraction service — SDK >= 1.0.0
Tuned for Indian industrial auction catalogues (mjunction / Tata Steel format).

Document structure observed in real catalogues:
  Page 1  : Cover page
  Page 2  : Basic Details  — 2-column KV table (Catalogue Name, Seller, Mandate No., Auction Date …)
  Page 3  : Material Details table  — SRNo. | LOT No. | Location | Batch | Material Description
                                      | QTY | UOM | Material No. | GST(%) | TCS
  Page 4+ : T&C, Payment Schedule, Lifting Schedule, Penalty Clause, Taxes…
  Payment Schedule table   : SR No. | LOT No. | EMD value/schedule | Instalment 1 | Instalment 2
  Lifting Schedule table   : SR No. | LOT No. | 1st Instalment Lifting days | …

Key differences vs. a Western auction catalogue:
  - NO pre-listed estimated value; reserve/floor prices are not published.
  - Seller is always in the Basic Details section, not in the lot row.
  - Lots carry quantity + unit-of-measure (weight in KG, MT, etc.)
  - Each lot has a GST rate and TCS rate (Indian tax fields).
  - Payment and lifting terms are per-lot, stored in separate tables.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
from dataclasses import dataclass, field

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# ── Data classes ─────────────────────────────────────────────────────────────


@dataclass
class ExtractedLot:
    """One auction lot parsed from the Material Details table."""

    lot_number: str
    title: str
    description: str
    quantity: float | None = None
    unit_of_measure: str | None = None
    material_number: str | None = None
    location: str | None = None
    gst_percentage: float | None = None
    tcs_percentage: float | None = None
    # Payment / lifting terms (enriched from separate per-lot tables)
    emd_schedule: str | None = None
    instalment_1: str | None = None
    lifting_days_1: str | None = None
    # Legacy field kept for backward-compat; always None for this doc format
    estimated_value: float | None = None
    seller_name: str | None = None
    seller_contact: str | None = None


@dataclass
class AuctionMetadata:
    """Catalogue-level fields extracted from the Basic Details section."""

    catalogue_name: str | None = None
    catalogue_code: str | None = None
    mandate_number: str | None = None
    seller: str | None = None
    auction_date: str | None = None
    auction_type: str | None = None
    auction_website: str | None = None
    security_deposit: str | None = None
    bid_increment: str | None = None
    bid_duration: str | None = None
    dealing_officers: list[str] = field(default_factory=list)


@dataclass
class ExtractionResult:
    metadata: AuctionMetadata
    lots: list[ExtractedLot]


# ── Azure DI client ───────────────────────────────────────────────────────────


def _get_client() -> DocumentIntelligenceClient:
    return DocumentIntelligenceClient(
        endpoint=settings.AZURE_DI_ENDPOINT,
        credential=AzureKeyCredential(settings.AZURE_DI_KEY),
    )


def _analyze_sync(file_bytes: bytes, content_type: str):
    """
    Blocking SDK call — runs in a thread pool via run_in_executor.

    SDK 1.0.0 breaking change: parameter renamed from `analyze_request=` to
    positional `body=`. Pass IO[bytes] directly; content_type carries the
    real MIME type ("application/pdf", "image/jpeg", ...).
    """
    client = _get_client()
    poller = client.begin_analyze_document(
        "prebuilt-layout",
        body=io.BytesIO(file_bytes),  # positional body, NOT analyze_request=
        content_type=content_type,
        pages="3",
    )
    return poller.result()


async def extract_auction_data(
    file_bytes: bytes, content_type: str
) -> ExtractionResult:
    """
    Async entry point. Offloads the blocking Azure DI call to a thread pool.
    Returns ExtractionResult containing catalogue metadata + list of lots.
    """
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _analyze_sync, file_bytes, content_type)

    # Flat dict of all KV pairs across the whole document
    kv_all = _collect_kv_pairs(result)

    # Classify every detected table
    material_rows: list[dict[str, str]] = []
    payment_rows: list[dict[str, str]] = []
    lifting_rows: list[dict[str, str]] = []
    basic_rows: list[dict[str, str]] = []

    if result.tables:
        for table in result.tables:
            header_map, row_data = _parse_table(table)
            logger.info("-----------")
            logger.info(header_map)
            logger.info("-----------")
            logger.info(row_data)
            table_type = _classify_table(header_map)
            logger.info("Data")
            logger.info(table)

            if table_type == "material":
                material_rows.extend(row_data.values())
            elif table_type == "payment":
                payment_rows.extend(row_data.values())
            elif table_type == "lifting":
                lifting_rows.extend(row_data.values())
            elif table_type == "basic_details":
                basic_rows.extend(row_data.values())

    # 1. Catalogue-level metadata
    metadata = _extract_metadata(kv_all, basic_rows)

    # 2. Lots from Material Details table
    lots: list[ExtractedLot] = []
    for row in material_rows:
        lot = _row_to_lot(row)
        if lot:
            lot.seller_name = metadata.seller
            lot.seller_contact = _pick_dealing_officer_email(metadata.dealing_officers)
            lots.append(lot)

    # Fallback to KV pairs if no table matched
    if not lots:
        lot = _kv_to_lot(kv_all)
        if lot:
            lot.seller_name = metadata.seller
            lots.append(lot)

    # 3. Enrich with per-lot payment / lifting data
    _enrich_payment(lots, payment_rows)
    _enrich_lifting(lots, lifting_rows)

    logger.info(
        "Extracted %d lots | seller=%s | auction_date=%s",
        len(lots),
        metadata.seller,
        metadata.auction_date,
    )
    return ExtractionResult(metadata=metadata, lots=lots)


# ── Table parsing ─────────────────────────────────────────────────────────────


def _parse_table(table) -> tuple[dict[int, str], dict[int, dict[str, str]]]:
    header_map: dict[int, str] = {}
    row_data: dict[int, dict[str, str]] = {}

    # 1. Identify which rows constitute the header.
    header_rows = set()
    for cell in table.cells:
        # Azure DI often explicitly tags header cells
        if getattr(cell, "kind", None) == "columnHeader":
            header_rows.add(cell.row_index)

    # Fallback: If Azure didn't tag headers, find the first row containing common header keywords
    if not header_rows:
        row_texts = {}
        for cell in table.cells:
            row_texts.setdefault(cell.row_index, []).append(
                (cell.content or "").lower()
            )

        for r_idx in sorted(row_texts.keys()):
            joined = " ".join(row_texts[r_idx])
            if any(
                k in joined
                for k in ["lot", "description", "instalment", "emd", "sr no"]
            ):
                header_rows.add(r_idx)
                break

        # Absolute fallback to row 0
        if not header_rows:
            header_rows.add(0)

    # 2. Build the header map and extract data
    for cell in table.cells:
        text = (cell.content or "").strip()

        # Normalize internal line breaks (e.g., "LOT\n No." becomes "LOT No.")
        text = re.sub(r"\s+", " ", text)

        if cell.row_index in header_rows:
            existing = header_map.get(cell.column_index, "")
            # Concatenate multi-row headers cleanly
            header_map[cell.column_index] = (
                f"{existing} {text}".strip().lower() if existing else text.lower()
            )
        else:
            row_data.setdefault(cell.row_index, {})
            col_name = header_map.get(cell.column_index, f"_col{cell.column_index}")
            row_data[cell.row_index][col_name] = text

    return header_map, row_data


def _classify_table(header_map: dict[int, str]) -> str:
    headers_joined = " ".join(header_map.values())
    has_lot = any("lot" in h for h in header_map.values())
    has_material = any(
        k in headers_joined
        for k in ("material description", "qty", "uom", "material no")
    )
    has_payment = any(k in headers_joined for k in ("instalment", "installment", "emd"))
    has_lifting = "lifting" in headers_joined

    if has_lot and has_material:
        return "material"
    if has_lot and has_payment:
        return "payment"
    if has_lot and has_lifting:
        return "lifting"
    if len(header_map) <= 2:
        return "basic_details"
    return "unknown"


# ── Metadata extraction ───────────────────────────────────────────────────────

_METADATA_FIELD_MAP: dict[str, str] = {
    "catalogue name": "catalogue_name",
    "catalog name": "catalogue_name",
    "catalogue code": "catalogue_code",
    "catalog code": "catalogue_code",
    "mandate no": "mandate_number",
    "seller": "seller",
    "vendor": "seller",
    "consignor": "seller",
    "e-auction date": "auction_date",
    "auction date": "auction_date",
    "eauction date": "auction_date",
    "auction type": "auction_type",
    "eauction type": "auction_type",
    "auction website": "auction_website",
    "security deposit": "security_deposit",
    "bid increment": "bid_increment",
    "bid duration": "bid_duration",
}


def _collect_kv_pairs(result) -> dict[str, str]:
    kv: dict[str, str] = {}
    if result.key_value_pairs:
        for pair in result.key_value_pairs:
            if pair.key and pair.value:
                kv[pair.key.content.strip().lower()] = pair.value.content.strip()
    return kv


def _extract_metadata(
    kv_all: dict[str, str], basic_rows: list[dict[str, str]]
) -> AuctionMetadata:
    meta = AuctionMetadata()

    # Source 1: KV pairs
    for raw_key, val in kv_all.items():
        for pattern, attr in _METADATA_FIELD_MAP.items():
            if pattern in raw_key:
                if not getattr(meta, attr):
                    setattr(meta, attr, val)
                break
        if "dealing officer" in raw_key:
            meta.dealing_officers.append(val)

    # Source 2: 2-column Basic Details table rows
    for row in basic_rows:
        keys = sorted(row.keys())
        if len(keys) < 2:
            continue
        label = row.get(keys[0], "").strip().lower()
        value = row.get(keys[1], "").strip()
        if not label or not value:
            continue
        for pattern, attr in _METADATA_FIELD_MAP.items():
            if pattern in label:
                if not getattr(meta, attr):
                    setattr(meta, attr, value)
                break
        if "dealing officer" in label and value not in meta.dealing_officers:
            meta.dealing_officers.append(value)

    return meta


# ── Lot extraction ────────────────────────────────────────────────────────────

_LOT_FIELD_SYNONYMS: dict[str, list[str]] = {
    "lot_number": ["lot no", "lot #", "lot number", "lotno", "lot"],
    "title": [
        "material description",
        "description",
        "item description",
        "title",
        "item",
        "name",
    ],
    "quantity": ["qty", "quantity"],
    "unit_of_measure": ["uom", "unit of measure", "unit"],
    "material_number": ["material no", "material number", "mat no"],
    "location": ["location", "yard", "site"],
    "gst_percentage": ["gst", "cgst", "igst"],
    "tcs_percentage": ["tcs"],
}


def _find_in_row(row: dict[str, str], synonyms: list[str]) -> str | None:
    for col_key, val in row.items():
        col_lower = col_key.lower()
        for syn in synonyms:
            if syn in col_lower:
                stripped = val.strip()
                return stripped if stripped and stripped.upper() != "NA" else None
    return None


def _row_to_lot(row: dict[str, str]) -> ExtractedLot | None:
    lot_number = _find_in_row(row, _LOT_FIELD_SYNONYMS["lot_number"])
    raw_title = _find_in_row(row, _LOT_FIELD_SYNONYMS["title"])
    if not lot_number or not raw_title:
        return None

    title = _strip_lot_prefix(raw_title, lot_number)
    raw_qty = _find_in_row(row, _LOT_FIELD_SYNONYMS["quantity"])

    return ExtractedLot(
        lot_number=lot_number,
        title=title,
        description=title,
        quantity=_parse_float(raw_qty),
        unit_of_measure=_find_in_row(row, _LOT_FIELD_SYNONYMS["unit_of_measure"]),
        material_number=_find_in_row(row, _LOT_FIELD_SYNONYMS["material_number"]),
        location=_find_in_row(row, _LOT_FIELD_SYNONYMS["location"]),
        gst_percentage=_parse_float(
            _find_in_row(row, _LOT_FIELD_SYNONYMS["gst_percentage"])
        ),
        tcs_percentage=_parse_float(
            _find_in_row(row, _LOT_FIELD_SYNONYMS["tcs_percentage"])
        ),
    )


def _kv_to_lot(kv: dict[str, str]) -> ExtractedLot | None:
    """Last-resort fallback when no Material Details table was detected."""
    lot_number = kv.get("lot") or kv.get("lot number") or kv.get("lot no")
    title = (
        kv.get("material description")
        or kv.get("description")
        or kv.get("title")
        or kv.get("item")
    )
    if not lot_number or not title:
        return None
    return ExtractedLot(
        lot_number=lot_number,
        title=_strip_lot_prefix(title, lot_number),
        description=_strip_lot_prefix(title, lot_number),
        quantity=_parse_float(kv.get("qty") or kv.get("quantity")),
        unit_of_measure=kv.get("uom") or kv.get("unit"),
        material_number=kv.get("material no") or kv.get("material number"),
        location=kv.get("location"),
        gst_percentage=_parse_float(kv.get("gst")),
        tcs_percentage=_parse_float(kv.get("tcs")),
        seller_name=kv.get("seller") or kv.get("consignor"),
    )


# ── Payment & Lifting enrichment ──────────────────────────────────────────────


def _enrich_payment(
    lots: list[ExtractedLot], payment_rows: list[dict[str, str]]
) -> None:
    lot_index = {lot.lot_number: lot for lot in lots}
    for row in payment_rows:
        lot_no = _find_in_row(row, ["lot no", "lot #", "lot number", "lot"])
        if not lot_no:
            continue
        target = lot_index.get(lot_no) or _fuzzy_match_lot(lot_no, lots)
        if not target:
            continue
        if emd := _find_in_row(row, ["emd"]):
            target.emd_schedule = emd
        if ins := _find_in_row(row, ["instalment 1", "installment 1", "instalment1"]):
            target.instalment_1 = ins


def _enrich_lifting(
    lots: list[ExtractedLot], lifting_rows: list[dict[str, str]]
) -> None:
    lot_index = {lot.lot_number: lot for lot in lots}
    for row in lifting_rows:
        lot_no = _find_in_row(row, ["lot no", "lot #", "lot number", "lot"])
        if not lot_no:
            continue
        target = lot_index.get(lot_no) or _fuzzy_match_lot(lot_no, lots)
        if not target:
            continue
        if lifting := _find_in_row(
            row, ["1st instalment lifting", "lifting days", "lifting"]
        ):
            target.lifting_days_1 = lifting


def _fuzzy_match_lot(lot_no: str, lots: list[ExtractedLot]) -> ExtractedLot | None:
    """Match "47.0" to a lot with lot_number "47" (strips trailing .0)."""
    clean = lot_no.rstrip("0").rstrip(".").strip()
    return next((l for l in lots if l.lot_number.startswith(clean)), None)


# ── String utilities ──────────────────────────────────────────────────────────


def _strip_lot_prefix(text: str, lot_number: str) -> str:
    """
    "47 Flux skimming (Stock + Arising)"  →  "Flux skimming (Stock + Arising)"
    Handles "47.0 ", "47. " prefixes.
    """
    clean_lot = lot_number.rstrip("0").rstrip(".").strip()
    return re.sub(rf"^{re.escape(clean_lot)}\.?\s*", "", text).strip() or text


def _parse_float(raw: str | None) -> float | None:
    if not raw:
        return None
    cleaned = re.sub(r"[₹$£,\s]", "", raw)
    cleaned = re.split(r"[–\-]", cleaned)[0].strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _pick_dealing_officer_email(officers: list[str]) -> str | None:
    """
    "Mohit Raj -- NA -- mohit.raj@tatasteel.com"  →  "mohit.raj@tatasteel.com"
    """
    for o in officers:
        m = re.search(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", o, re.IGNORECASE)
        if m:
            return m.group(0)
    return None
