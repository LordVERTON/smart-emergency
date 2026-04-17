"""
Parse transcript text into MedicalSheet.
Rules: regex + keyword detection. Unknown text → history.
"""

import re
import logging
from datetime import datetime, timezone
from uuid import uuid4

from sheets.models import MedicalSheet, Patient, Tests, Meta

logger = logging.getLogger(__name__)

# Keywords for classification
HISTORY_KEYWORDS = {"dyspnée", "dyspnee", "fièvre", "fievre", "douleur", "toux", "nausée", "vomissement"}
TESTS_BIO = {"crp", "bio", "nfs", "ionogramme", "créatinine", "troponine", "bnp", "d-dimères"}
TESTS_IMAGING = {"scanner", "scanner", "radio", "radiographie", "irm", "échographie", "echographie", "thorax"}
TESTS_ECG = {"ecg", "électrocardiogramme", "electrocardiogramme"}
TESTS_GAS = {"gaz", "gazométrie", "gazometrie", "saturation", "spo2"}
DIAGNOSIS_KEYWORDS = {"diag", "diagnostic", "pneumonie", "pac", "ic", "avc", "idm", "sep", "infection"}
ORIENTATION_KEYWORDS = {"hospit", "hospitalisation", "pug", "uhcd", "réa", "rea", "urgence", "domicile", "sortie"}


def _extract_age(text: str) -> int | None:
    """Detect age: regex r'(\\d{2,3})\\s?ans'."""
    m = re.search(r"(\d{2,3})\s?ans", text, re.IGNORECASE)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return None


def _extract_sex(text: str) -> str | None:
    """Detect sex: Mme, Madame, femme, homme, M."""
    t = text.lower()
    if any(k in t for k in ["madame", "mme", "femme", "f "]):
        return "F"
    if any(k in t for k in ["monsieur", "m.", "homme", " masculin"]):
        return "M"
    return None


def _extract_motif(text: str) -> str | None:
    """First sentence or after 'motif'."""
    m = re.search(r"motif\s*[:\-]\s*(.+?)(?=\n|\.\s+[A-Z]|$)", text, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).strip()[:200]
    first = re.match(r"^([^.]{10,100})\.?", text)
    return first.group(1).strip() if first else None


def _extract_section(text: str, *markers: str) -> list[str]:
    """Extract lines after ATCD, antécédents, traitement, TTT, etc."""
    result = []
    for marker in markers:
        m = re.search(
            rf"{re.escape(marker)}\s*[:\-]?\s*(.+?)(?=\n\n|\n[A-Z]|$)",
            text,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            block = m.group(1).strip()
            for line in re.split(r"[,;\n]", block):
                line = line.strip()
                if line and len(line) > 2:
                    result.append(line[:300])
    return result


def _extract_antecedents(text: str) -> list[str]:
    """After ATCD, antécédents."""
    return _extract_section(text, "ATCD", "antécédents", "antécédent")


def _extract_home_treatment(text: str) -> list[str]:
    """After traitement, TTT."""
    return _extract_section(text, "traitement", "TTT", "traitements")


def _classify_sentences(text: str) -> tuple[list[str], list[str], list[str], list[str], list[str], list[str]]:
    """
    Classify sentences into history, exam, tests, diagnosis, treatmentPlan, orientation.
    Unknown → history.
    """
    history: list[str] = []
    exam: list[str] = []
    tests_bio: list[str] = []
    tests_imaging: list[str] = []
    tests_ecg: list[str] = []
    tests_gas: list[str] = []
    diagnosis: list[str] = []
    treatment_plan: list[str] = []
    orientation: list[str] = []

    # Split into sentences/phrases
    parts = re.split(r"[.\n]+", text)
    for part in parts:
        part = part.strip()
        if len(part) < 3:
            continue
        lower = part.lower()

        # Tests
        if any(k in lower for k in TESTS_BIO):
            tests_bio.append(part[:200])
            continue
        if any(k in lower for k in TESTS_IMAGING):
            tests_imaging.append(part[:200])
            continue
        if any(k in lower for k in TESTS_ECG):
            tests_ecg.append(part[:200])
            continue
        if any(k in lower for k in TESTS_GAS):
            tests_gas.append(part[:200])
            continue

        # Diagnosis
        if any(k in lower for k in DIAGNOSIS_KEYWORDS):
            diagnosis.append(part[:200])
            continue

        # Orientation
        if any(k in lower for k in ORIENTATION_KEYWORDS):
            orientation.append(part[:200])
            continue

        # History (symptoms)
        if any(k in lower for k in HISTORY_KEYWORDS):
            history.append(part[:200])
            continue

        # Exam (examen, constantes, etc.)
        if re.search(r"examen|constantes|ta|fc|temp|auscultation", lower):
            exam.append(part[:200])
            continue

        # Treatment plan (plan, prescription)
        if re.search(r"plan|prescription|ordonnance|antibiothérapie", lower):
            treatment_plan.append(part[:200])
            continue

        # Default: history
        history.append(part[:200])

    tests = Tests(
        bio=tests_bio,
        imaging=tests_imaging,
        ecg=tests_ecg,
        gas=tests_gas,
    )
    return history, exam, tests, diagnosis, treatment_plan, orientation


def parse_transcript(text: str, transcript_id: str) -> MedicalSheet:
    """
    Parse transcript into MedicalSheet.
    Defensive: empty lists if nothing found.
    """
    if not text or not isinstance(text, str):
        text = ""

    logger.info("Parsing transcript %s, len=%d", transcript_id, len(text))

    patient = Patient(
        name=None,
        age=_extract_age(text),
        sex=_extract_sex(text),
        motif=_extract_motif(text),
    )

    antecedents = _extract_antecedents(text)
    home_treatment = _extract_home_treatment(text)

    history, exam, tests, diagnosis, treatment_plan, orientation = _classify_sentences(text)

    sheet_id = str(uuid4())
    created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    meta = Meta(
        createdAt=created_at,
        transcriptId=transcript_id,
        confidence=None,
    )

    sheet = MedicalSheet(
        id=sheet_id,
        patient=patient,
        antecedents=antecedents or [],
        homeTreatment=home_treatment or [],
        history=history or [],
        exam=exam or [],
        tests=tests,
        diagnosis=diagnosis or [],
        treatmentPlan=treatment_plan or [],
        orientation=orientation or [],
        meta=meta,
    )
    logger.info("Parsed sheet %s", sheet_id)
    return sheet
