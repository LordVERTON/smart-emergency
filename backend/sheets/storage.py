"""JSON file storage for medical sheets."""

import json
import logging
from pathlib import Path

from sheets.models import MedicalSheet

logger = logging.getLogger(__name__)

SHEETS_FILE = Path(__file__).parent.parent / "data" / "sheets.json"


def _ensure_file() -> None:
    """Create sheets.json if missing."""
    SHEETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not SHEETS_FILE.exists():
        SHEETS_FILE.write_text("[]", encoding="utf-8")
        logger.info("Created %s", SHEETS_FILE)


def _load_raw() -> list[dict]:
    """Load raw JSON data."""
    _ensure_file()
    try:
        data = json.loads(SHEETS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Could not load sheets: %s", e)
        return []


def _save_raw(sheets: list[dict]) -> None:
    """Save raw JSON data."""
    _ensure_file()
    SHEETS_FILE.write_text(
        json.dumps(sheets, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_all_sheets() -> list[MedicalSheet]:
    """Load all sheets from storage."""
    raw = _load_raw()
    result = []
    for item in raw:
        try:
            result.append(MedicalSheet.model_validate(item))
        except Exception as e:
            logger.warning("Skip invalid sheet %s: %s", item.get("id"), e)
    return result


def save_sheet(sheet: MedicalSheet) -> None:
    """Save or update a sheet."""
    raw = _load_raw()
    ids = [s.get("id") for s in raw]
    sheet_dict = sheet.model_dump()
    if sheet.id in ids:
        raw = [s if s.get("id") != sheet.id else sheet_dict for s in raw]
    else:
        raw.append(sheet_dict)
    _save_raw(raw)
    logger.info("Saved sheet %s", sheet.id)


def get_sheet(sheet_id: str) -> MedicalSheet | None:
    """Get a sheet by id."""
    raw = _load_raw()
    for item in raw:
        if item.get("id") == sheet_id:
            try:
                return MedicalSheet.model_validate(item)
            except Exception as e:
                logger.warning("Invalid sheet %s: %s", sheet_id, e)
                return None
    return None


def list_sheets() -> list[dict]:
    """List sheets (id, patient.motif, meta.createdAt) for listing."""
    raw = _load_raw()
    return [
        {
            "id": s.get("id"),
            "motif": s.get("patient", {}).get("motif"),
            "createdAt": s.get("meta", {}).get("createdAt"),
        }
        for s in raw
    ]
