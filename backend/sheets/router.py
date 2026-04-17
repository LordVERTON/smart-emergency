"""FastAPI router for medical sheets."""

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sheets.models import MedicalSheet
from sheets.parser import parse_transcript
from sheets.storage import get_sheet, list_sheets, save_sheet

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sheets", tags=["sheets"])


class FromTranscriptBody(BaseModel):
    transcriptId: str
    text: str


@router.post("/from-transcript")
def create_sheet_from_transcript(body: FromTranscriptBody) -> MedicalSheet:
    """
    Parse transcript, save sheet, return it.
    body: { transcriptId: str, text: str }
    """
    transcript_id = body.transcriptId or ""
    text = body.text or ""

    try:
        sheet = parse_transcript(text, transcript_id)
        save_sheet(sheet)
        return sheet
    except Exception as e:
        logger.exception("Sheet creation failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/")
def list_all_sheets() -> list:
    """List all sheets (id, motif, createdAt)."""
    try:
        return list_sheets()
    except Exception as e:
        logger.exception("List sheets failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{sheet_id}")
def get_sheet_by_id(sheet_id: str) -> MedicalSheet:
    """Get sheet by id."""
    sheet = get_sheet(sheet_id)
    if not sheet:
        raise HTTPException(status_code=404, detail="Sheet not found")
    return sheet
