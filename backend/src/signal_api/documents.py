import uuid
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from pypdf import PdfReader
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from signal_api.auth import CurrentUser
from signal_api.config import get_settings
from signal_api.database import get_db_session
from signal_api.models import (
    Document,
    DocumentPage,
    DocumentProcessingStatus,
    Membership,
    Organization,
    User,
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
    processing_error: str | None
    created_at: datetime
    uploaded_by_name: str


class DocumentSearchResult(BaseModel):
    document_id: uuid.UUID
    document_name: str
    page_number: int
    excerpt: str
    score: int


class DocumentSearchRequest(BaseModel):
    organization_id: uuid.UUID
    query: str
    document_ids: list[uuid.UUID] | None = None


def search_document_pages(
    db: Session,
    organization_id: uuid.UUID,
    query: str,
    document_ids: set[uuid.UUID] | None = None,
    limit: int = 5,
) -> list[DocumentSearchResult]:
    normalized = query.strip().casefold()
    if not normalized:
        return []
    statement = (
        select(Document, DocumentPage)
        .join(DocumentPage, DocumentPage.document_id == Document.id)
        .where(
            Document.organization_id == organization_id,
            Document.processing_status == DocumentProcessingStatus.READY,
        )
    )
    if document_ids is not None:
        statement = statement.where(Document.id.in_(document_ids))
    results: list[DocumentSearchResult] = []
    for document, page in db.execute(statement):
        content = page.content.casefold()
        score = content.count(normalized)
        if score:
            index = content.index(normalized)
            results.append(
                DocumentSearchResult(
                    document_id=document.id,
                    document_name=document.filename,
                    page_number=page.page_number,
                    excerpt=page.content[max(0, index - 80) : index + len(query) + 120],
                    score=score,
                )
            )
    return sorted(
        results,
        key=lambda result: (-result.score, str(result.document_id), result.page_number),
    )[:limit]


@router.post("/search", response_model=list[DocumentSearchResult])
def search_documents(
    request: DocumentSearchRequest, db: DatabaseSession, current_user: CurrentUser
) -> list[DocumentSearchResult]:
    require_membership(request.organization_id, current_user.id, db)
    return search_document_pages(
        db,
        request.organization_id,
        request.query,
        None if request.document_ids is None else set(request.document_ids),
    )


def to_document_response(document: Document, db: Session) -> DocumentResponse:
    uploader = db.get(User, document.uploaded_by_user_id)
    if uploader is None:
        raise RuntimeError("Document uploader is missing")
    return DocumentResponse(
        id=document.id,
        organization_id=document.organization_id,
        filename=document.filename,
        content_type=document.content_type,
        byte_size=document.byte_size,
        processing_status=document.processing_status,
        processing_error=document.processing_error,
        created_at=document.created_at,
        uploaded_by_name=uploader.name,
    )


@router.get("", response_model=list[DocumentResponse])
def list_documents(
    organization_id: uuid.UUID, db: DatabaseSession, current_user: CurrentUser
) -> list[DocumentResponse]:
    require_membership(organization_id, current_user.id, db)
    documents = db.scalars(
        select(Document)
        .where(Document.organization_id == organization_id)
        .order_by(Document.created_at.desc(), Document.id.desc())
    ).all()
    return [to_document_response(document, db) for document in documents]


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
        processing_error=document.processing_error,
        created_at=document.created_at,
        uploaded_by_name=current_user.name,
    )


@router.post("/{document_id}/extract", response_model=DocumentResponse)
def extract_document(
    document_id: uuid.UUID, db: DatabaseSession, current_user: CurrentUser
) -> DocumentResponse:
    document = db.scalar(
        select(Document).where(Document.id == document_id).with_for_update()
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    require_membership(document.organization_id, current_user.id, db)
    try:
        reader = PdfReader(
            BytesIO(
                (
                    get_settings().document_storage_dir / document.storage_key
                ).read_bytes()
            )
        )
        if reader.is_encrypted:
            raise ValueError("Encrypted PDF")
        if len(reader.pages) > get_settings().document_max_pages:
            raise ValueError("PDF exceeds page limit")
        pages = [
            (index + 1, page.extract_text() or "")
            for index, page in enumerate(reader.pages)
        ]
        if (
            sum(len(text.encode()) for _, text in pages)
            > get_settings().document_max_extracted_text_bytes
        ):
            raise ValueError("PDF text exceeds limit")
    except Exception:
        db.execute(delete(DocumentPage).where(DocumentPage.document_id == document.id))
        document.processing_status = DocumentProcessingStatus.FAILED
        document.processing_error = "PDF extraction failed"
        db.commit()
        return to_document_response(document, db)
    db.execute(delete(DocumentPage).where(DocumentPage.document_id == document.id))
    if not any(text.strip() for _, text in pages):
        document.processing_status = DocumentProcessingStatus.TEXT_UNAVAILABLE
        document.processing_error = "No extractable text"
    else:
        db.add_all(
            [
                DocumentPage(document_id=document.id, page_number=n, content=text)
                for n, text in pages
            ]
        )
        document.processing_status = DocumentProcessingStatus.READY
        document.processing_error = None
    db.commit()
    return to_document_response(document, db)
