import os, uuid, shutil
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.database import get_db
from app.models.document import ProcessedDocument, DocumentStatus
from app.models.user import UserRole
from app.api.deps import require_role, get_current_user
from app.services.service_bus import enqueue_document_job
from app.schemas.document import DocumentOut

router = APIRouter(prefix="/api/documents", tags=["documents"])

UPLOAD_DIR = "/tmp/auction_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/tiff"}


@router.post("/upload/{auction_id}", response_model=DocumentOut, status_code=201)
async def upload_document(
    auction_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_role(UserRole.AUCTIONEER, UserRole.ADMIN)),
):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}")

    doc_id = str(uuid.uuid4())
    blob_path = os.path.join(UPLOAD_DIR, f"{doc_id}_{file.filename}")

    # Save file to local disk (replace with Azure Blob Storage in production)
    with open(blob_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Create DB record with QUEUED status
    doc = ProcessedDocument(
        id=doc_id,
        auction_id=auction_id,
        uploaded_by=current_user.id,
        original_filename=file.filename,
        blob_path=blob_path,
        status=DocumentStatus.QUEUED,
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    # Enqueue to Azure Service Bus — non-blocking
    enqueue_document_job({
        "document_id": doc_id,
        "auction_id": auction_id,
        "blob_path": blob_path,
    })

    return doc


@router.get("/{document_id}/status", response_model=DocumentOut)
async def get_document_status(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    result = await db.execute(select(ProcessedDocument).where(ProcessedDocument.id == document_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc