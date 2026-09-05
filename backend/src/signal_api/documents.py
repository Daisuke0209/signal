import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from signal_api.auth import CurrentUser
from signal_api.config import get_settings
from signal_api.database import get_db_session
from signal_api.models import (
    Document,
    DocumentProcessingStatus,
    Membership,
    Organization,
)

router = APIRouter(prefix="/documents", tags=["documents"])
DatabaseSession = Annotated[Session, Depends(get_db_session)]


class DocumentResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    filename: str
    content_type: str
    byte_size: int
    processing_status: DocumentProcessingStatus


def require_membership(
    organization_id: uuid.UUID, user_id: uuid.UUID, db: Session
) -> None:
    if (
        db.get(Membership, {"organization_id": organization_id, "user_id": user_id})
        is None
    ):
        raise HTTPException(status_code=403, detail="Not a member of this organization")


@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_document(
    organization_id: Annotated[uuid.UUID, Form()],
    file: Annotated[UploadFile, File()],
    db: DatabaseSession,
    current_user: CurrentUser,
) -> DocumentResponse:
    require_membership(organization_id, current_user.id, db)
    settings = get_settings()
    organization = db.scalar(
        select(Organization).where(Organization.id == organization_id).with_for_update()
    )
    if organization is None:
        raise HTTPException(status_code=403, detail="Not a member of this organization")
    count = db.scalar(
        select(func.count())
        .select_from(Document)
        .where(Document.organization_id == organization_id)
    )
    if count is not None and count >= settings.document_max_count_per_organization:
        raise HTTPException(status_code=422, detail="Document limit reached")
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=422, detail="Only PDF files are accepted")
    contents = await file.read(settings.document_max_size_bytes + 1)
    if not contents:
        raise HTTPException(status_code=422, detail="Document must not be empty")
    if len(contents) > settings.document_max_size_bytes:
        raise HTTPException(status_code=422, detail="Document exceeds the size limit")
    if not contents.startswith(b"%PDF-"):
        raise HTTPException(status_code=422, detail="File is not a valid PDF")
    document = Document(
        organization_id=organization_id,
        uploaded_by_user_id=current_user.id,
        filename=Path(file.filename or "document.pdf").name,
        content_type="application/pdf",
        byte_size=len(contents),
        storage_key=str(uuid.uuid4()),
    )
    require_membership(organization_id, current_user.id, db)
    storage_path = settings.document_storage_dir / document.storage_key
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        storage_path.write_bytes(contents)
        db.add(document)
        db.commit()
    except Exception:
        storage_path.unlink(missing_ok=True)
        db.rollback()
        raise
    return DocumentResponse(
        id=document.id,
        organization_id=document.organization_id,
        filename=document.filename,
        content_type=document.content_type,
        byte_size=document.byte_size,
        processing_status=document.processing_status,
    )
