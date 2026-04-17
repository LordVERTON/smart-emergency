"""
MedNote Backend - API FastAPI pour transcription audio et notes médicales structurées.
Stockage local: data/audio/*.m4a, data/notes/*.json
"""

import json
import logging
import os
import re
import subprocess
import uuid
from functools import lru_cache
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from ai import extract_structured_note_with_graph

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Chemins de stockage
DATA_DIR = Path(__file__).parent / "data"
AUDIO_DIR = DATA_DIR / "audio"
NOTES_DIR = DATA_DIR / "notes"

# Modèle Whisper (base ou small selon perf)
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

# Création des dossiers si nécessaire
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
NOTES_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="MedNote API", version="1.0.0")

# CORS permissif pour dev (accès depuis mobile sur LAN)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Sheets module (medical sheet generation)
from sheets.router import router as sheets_router
app.include_router(sheets_router)


# --- Modèles Pydantic ---

class StructuredNote(BaseModel):
    """Note médicale structurée (extraction heuristique sans LLM)."""
    motif: str
    histoire_maladie: str
    antecedents: str
    traitements: str
    allergies: str
    examen_clinique: str
    constantes: str
    hypotheses: str
    plan: str
    a_verifier: bool = True


class TranscribeResponse(BaseModel):
    """Réponse POST /transcribe."""
    id: str
    transcript: str
    structured: StructuredNote
    extraction_meta: dict | None = None


class NoteSummary(BaseModel):
    """Résumé d'une note pour la liste GET /notes."""
    id: str
    motif: str
    created_at: str


class NoteDetail(BaseModel):
    """Note complète pour GET /notes/{id}."""
    id: str
    transcript: str
    structured: StructuredNote
    created_at: str
    extraction_meta: dict | None = None


class HealthResponse(BaseModel):
    """Réponse GET /health."""
    ok: bool = True


# --- Heuristiques d'extraction (sans LLM) ---

def extract_field(text: str, pattern: str) -> str:
    """Extrait un champ via regex. Retourne '' si non trouvé."""
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def build_structured_note(transcript: str) -> StructuredNote:
    """
    Construit une note structurée à partir du transcript.
    Heuristiques simples: première phrase = motif, regex pour ATCD/Traitements/Allergies.
    """
    text = transcript.strip()
    if not text:
        return StructuredNote(
            motif="",
            histoire_maladie="",
            antecedents="",
            traitements="",
            allergies="",
            examen_clinique="",
            constantes="",
            hypotheses="",
            plan="",
            a_verifier=True,
        )

    # Motif = première phrase (jusqu'au premier point ou fin)
    first_sentence_match = re.match(r"^([^.]*\.?)\s*", text)
    motif = first_sentence_match.group(1).strip() if first_sentence_match else text[:100]

    # Extraction par patterns courants
    antecedents = extract_field(text, r"ATCD\s*[:\-]\s*(.+?)(?=\n\n|\n[A-Z]|$)")
    if not antecedents:
        antecedents = extract_field(text, r"antécédents?\s*[:\-]\s*(.+?)(?=\n\n|\n[A-Z]|$)")
    traitements = extract_field(text, r"traitements?\s*[:\-]\s*(.+?)(?=\n\n|\n[A-Z]|$)")
    allergies = extract_field(text, r"allergies?\s*[:\-]\s*(.+?)(?=\n\n|\n[A-Z]|$)")
    examen_clinique = extract_field(text, r"examen\s*(?:clinique)?\s*[:\-]\s*(.+?)(?=\n\n|\n[A-Z]|$)")
    constantes = extract_field(text, r"constantes?\s*[:\-]\s*(.+?)(?=\n\n|\n[A-Z]|$)")
    hypotheses = extract_field(text, r"hypothèses?\s*[:\-]\s*(.+?)(?=\n\n|\n[A-Z]|$)")
    plan = extract_field(text, r"plan\s*[:\-]\s*(.+?)(?=\n\n|\n[A-Z]|$)")

    return StructuredNote(
        motif=motif,
        histoire_maladie=text,
        antecedents=antecedents,
        traitements=traitements,
        allergies=allergies,
        examen_clinique=examen_clinique,
        constantes=constantes,
        hypotheses=hypotheses,
        plan=plan,
        a_verifier=True,
    )


# --- Validation & conversion audio ---

MIN_AUDIO_SIZE_BYTES = 1024  # 1 KB minimum (évite fichiers vides ou quasi-vides)


def _user_friendly_audio_error(stderr: str) -> str:
    """Traduit les erreurs ffmpeg/ffprobe en message utilisateur."""
    stderr_lower = stderr.lower()
    if "moov atom not found" in stderr_lower or "moov atom" in stderr_lower:
        return "Fichier audio corrompu ou incomplet. L'enregistrement a peut-être été interrompu trop tôt."
    if "invalid data found" in stderr_lower or "invalid data" in stderr_lower:
        return "Format audio invalide ou fichier corrompu. Réessayez un nouvel enregistrement."
    if "no such file" in stderr_lower:
        return "Fichier introuvable après enregistrement."
    if "connection" in stderr_lower or "timeout" in stderr_lower:
        return "Upload interrompu ou timeout. Vérifiez votre connexion."
    return "Le fichier audio n'a pas pu être traité. Réessayez avec un nouvel enregistrement."


def validate_audio_file(audio_path: Path) -> None:
    """
    Valide que le fichier existe, a une taille suffisante et est complet.
    Lève ValueError en cas de problème.
    """
    if not audio_path.exists():
        raise ValueError("Fichier non trouvé après enregistrement")
    size = audio_path.stat().st_size
    if size == 0:
        raise ValueError("Fichier audio vide")
    if size < MIN_AUDIO_SIZE_BYTES:
        raise ValueError(f"Fichier trop petit ({size} octets). Enregistrement probablement incomplet.")


def ffprobe_validate(audio_path: Path) -> dict:
    """
    Valide le fichier audio avec ffprobe. Ne jamais appeler ffmpeg sur un fichier invalide.
    Retourne les métadonnées si OK, lève ValueError sinon.
    """
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_format",
            "-show_streams",
            "-of", "json",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        err_msg = _user_friendly_audio_error(result.stderr or result.stdout or "Unknown error")
        logger.warning("ffprobe failed for %s: %s", audio_path, result.stderr)
        raise ValueError(err_msg)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise ValueError("Impossible d'analyser le fichier audio")


def convert_to_wav(audio_path: Path) -> Path:
    """
    Convertit m4a/mp4/mp3 en WAV via ffmpeg.
    À appeler uniquement après validation ffprobe réussie.
    """
    wav_path = audio_path.with_suffix(".wav")
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i", str(audio_path),
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            str(wav_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        err_msg = _user_friendly_audio_error(result.stderr or "")
        logger.error("ffmpeg conversion failed for %s: %s", audio_path, result.stderr)
        raise RuntimeError(err_msg)
    return wav_path


def transcribe_audio(audio_path: Path) -> str:
    """Transcrit l'audio avec faster-whisper. Retourne le texte en français."""
    # Conversion m4a -> wav pour éviter "invalid data found" (PyAV tolère mal certains m4a)
    wav_path = convert_to_wav(audio_path)
    try:
        model = get_whisper_model()
        segments, info = model.transcribe(str(wav_path), language="fr")
        transcript = " ".join(seg.text for seg in segments).strip()
        return transcript or "(Aucune parole détectée)"
    finally:
        if wav_path.exists():
            wav_path.unlink()


@lru_cache(maxsize=1)
def get_whisper_model():
    """
    Charge Whisper une seule fois par process pour réduire la latence.
    Le premier appel est plus lent (warm-up), les suivants sont rapides.
    """
    from faster_whisper import WhisperModel

    logger.info(
        "Loading Whisper model '%s' (device=%s, compute_type=%s)",
        WHISPER_MODEL,
        WHISPER_DEVICE,
        WHISPER_COMPUTE_TYPE,
    )
    return WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE)


def _handle_transcribe_exception(audio_path: Path, e: Exception) -> None:
    """Normalize unexpected transcription errors into HTTPException."""
    if audio_path.exists():
        audio_path.unlink()
    logger.exception("Transcription failed for %s", audio_path)
    err_str = str(e).lower()
    if "moov" in err_str or "invalid data" in err_str or "ffmpeg" in err_str:
        detail = _user_friendly_audio_error(str(e))
    else:
        detail = f"Erreur de transcription: {str(e)}"
    raise HTTPException(status_code=500, detail=detail)


def _heuristic_extraction_meta(requires_review: bool) -> dict:
    return {
        "mode": "heuristic",
        "confidence_by_field": {},
        "average_confidence": 0.0,
        "validation_issues": [],
        "requires_review": requires_review,
    }


# --- Endpoints ---

async def _transcribe_upload_to_text(audio: UploadFile, note_id: str) -> tuple[Path, str]:
    """
    Shared upload/transcription pipeline.
    Returns (audio_path, transcript).
    """
    audio_path = AUDIO_DIR / f"{note_id}.m4a"
    # 1. Lecture complète du stream (attend la fin de l'upload)
    content = await audio.read()
    upload_size = len(content)
    logger.info("Upload received: size=%d bytes, path=%s", upload_size, audio_path)

    # 2. Validation pré-écriture
    if upload_size == 0:
        raise HTTPException(status_code=400, detail="Fichier audio vide")
    if upload_size < MIN_AUDIO_SIZE_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Fichier trop petit ({upload_size} octets). Enregistrement incomplet.",
        )

    # 3. Écriture + flush disque (attente complète du stream)
    with audio_path.open("wb") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())

    # 4. Vérification post-écriture (taille cohérente)
    written_size = audio_path.stat().st_size
    if written_size != upload_size:
        raise HTTPException(
            status_code=500,
            detail=f"Erreur d'écriture: taille attendue {upload_size}, écrite {written_size}",
        )
    logger.info("File written: path=%s, size=%d", audio_path, written_size)

    # 5. Validation fichier (existence, taille)
    validate_audio_file(audio_path)

    # 6. Validation ffprobe AVANT ffmpeg (ne jamais appeler ffmpeg sur fichier invalide)
    try:
        probe_result = ffprobe_validate(audio_path)
        logger.info("ffprobe OK for %s: format=%s", audio_path, probe_result.get("format", {}).get("format_name", "?"))
    except ValueError as e:
        if audio_path.exists():
            audio_path.unlink()
        raise HTTPException(status_code=400, detail=str(e))

    # 7. Transcription (conversion + Whisper)
    transcript = transcribe_audio(audio_path)
    return audio_path, transcript


def _save_note(
    note_id: str,
    transcript: str,
    structured: StructuredNote,
    extraction_meta: dict | None = None,
) -> None:
    """Persist note payload in JSON storage."""
    created_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    note_data = {
        "id": note_id,
        "transcript": transcript,
        "structured": structured.model_dump(),
        "created_at": created_at,
        "extraction_meta": extraction_meta or {"mode": "heuristic"},
    }
    note_path = NOTES_DIR / f"{note_id}.json"
    note_path.write_text(json.dumps(note_data, ensure_ascii=False, indent=2), encoding="utf-8")

@app.get("/health", response_model=HealthResponse)
def health():
    """Vérification que l'API est en ligne."""
    return HealthResponse(ok=True)


@app.on_event("startup")
def preload_models() -> None:
    """
    Preload the Whisper model to avoid first-request cold start.
    Failure is non-blocking to keep API boot resilient.
    """
    try:
        get_whisper_model()
    except Exception as e:
        logger.warning("Whisper preload failed (will retry on demand): %s", e)


@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(audio: UploadFile = File(..., description="Fichier audio (m4a)")):
    """
    Reçoit un fichier audio (multipart/form-data), le valide, le sauvegarde,
    le transcrit avec faster-whisper, produit une note structurée.
    Rejette les uploads incomplets ou corrompus avant tout appel à ffmpeg.
    """
    note_id = str(uuid.uuid4())
    audio_path = AUDIO_DIR / f"{note_id}.m4a"

    try:
        audio_path, transcript = await _transcribe_upload_to_text(audio, note_id)

    except HTTPException:
        raise
    except ValueError as e:
        if audio_path.exists():
            audio_path.unlink()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        _handle_transcribe_exception(audio_path, e)

    # Construction de la note structurée
    structured = build_structured_note(transcript)

    extraction_meta = _heuristic_extraction_meta(structured.a_verifier)
    _save_note(note_id, transcript, structured, extraction_meta=extraction_meta)

    return TranscribeResponse(
        id=note_id,
        transcript=transcript,
        structured=structured,
        extraction_meta=extraction_meta,
    )


@app.post("/transcribe-ai", response_model=TranscribeResponse)
async def transcribe_ai(audio: UploadFile = File(..., description="Fichier audio (m4a)")):
    """
    Variante IA: transcription Whisper + structuration LangGraph/LangChain.
    Fallback automatique sur l'extraction heuristique si l'IA échoue.
    """
    note_id = str(uuid.uuid4())
    audio_path = AUDIO_DIR / f"{note_id}.m4a"

    try:
        audio_path, transcript = await _transcribe_upload_to_text(audio, note_id)
    except HTTPException:
        raise
    except ValueError as e:
        if audio_path.exists():
            audio_path.unlink()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        _handle_transcribe_exception(audio_path, e)

    # Structuration IA + fallback heuristique
    try:
        ai_result = extract_structured_note_with_graph(transcript)
        structured = StructuredNote(**ai_result.structured.model_dump())
        extraction_meta = {
            "mode": "ai",
            "confidence_by_field": ai_result.confidence_by_field,
            "average_confidence": ai_result.average_confidence,
            "validation_issues": ai_result.validation_issues,
            "requires_review": ai_result.requires_review,
        }
        logger.info("AI structured extraction succeeded for note_id=%s", note_id)
    except Exception as e:
        logger.warning("AI extraction failed, fallback to heuristics for note_id=%s: %s", note_id, e)
        structured = build_structured_note(transcript)
        extraction_meta = {
            "mode": "fallback",
            "confidence_by_field": {},
            "average_confidence": 0.0,
            "validation_issues": ["AI extraction failed; fallback heuristique utilise."],
            "requires_review": True,
        }

    _save_note(note_id, transcript, structured, extraction_meta=extraction_meta)

    return TranscribeResponse(
        id=note_id,
        transcript=transcript,
        structured=structured,
        extraction_meta=extraction_meta,
    )


@app.get("/notes", response_model=list[NoteSummary])
def list_notes():
    """Liste toutes les notes (id, motif, created_at)."""
    summaries = []
    for note_file in sorted(NOTES_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(note_file.read_text(encoding="utf-8"))
            summaries.append(
                NoteSummary(
                    id=data["id"],
                    motif=data.get("structured", {}).get("motif", "(Sans motif)"),
                    created_at=data.get("created_at", ""),
                )
            )
        except Exception:
            continue
    return summaries


@app.get("/notes/{note_id}", response_model=NoteDetail)
def get_note(note_id: str):
    """Récupère une note complète par ID."""
    note_path = NOTES_DIR / f"{note_id}.json"
    if not note_path.exists():
        raise HTTPException(status_code=404, detail="Note introuvable")

    try:
        data = json.loads(note_path.read_text(encoding="utf-8"))
        return NoteDetail(
            id=data["id"],
            transcript=data["transcript"],
            structured=StructuredNote(**data["structured"]),
            created_at=data["created_at"],
            extraction_meta=data.get("extraction_meta"),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
