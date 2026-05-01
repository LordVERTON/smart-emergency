import { API_BASE, UPLOAD_TIMEOUT_MS } from "./config";

export type HealthResponse = {
  ok: boolean;
};

export type StructuredNote = {
  motif: string;
  histoire_maladie: string;
  antecedents: string;
  traitements: string;
  allergies: string;
  examen_clinique: string;
  constantes: string;
  hypotheses: string;
  plan: string;
  a_verifier: boolean;
};

export type TranscribeResponse = {
  id: string;
  transcript: string;
  structured: StructuredNote;
  extraction_meta?: {
    mode: "ai" | "fallback" | "heuristic";
    confidence_by_field: Record<string, number>;
    average_confidence: number;
    validation_issues: string[];
    requires_review: boolean;
  };
};

export type NoteSummary = {
  id: string;
  motif: string;
  created_at: string;
};

export type NoteDetail = {
  id: string;
  transcript: string;
  structured: StructuredNote;
  created_at: string;
  extraction_meta?: {
    mode: "ai" | "fallback" | "heuristic";
    confidence_by_field: Record<string, number>;
    average_confidence: number;
    validation_issues: string[];
    requires_review: boolean;
  };
};

export type SheetSummary = {
  id: string;
  motif: string;
  createdAt: string;
};

export type SheetDetail = {
  id: string;
  transcriptId: string;
  createdAt: string;
  motif: string;
  histoireMaladie: string;
  antecedents: string;
  traitements: string;
  allergies: string;
  examenClinique: string;
  constantes: string;
  hypotheses: string;
  plan: string;
  aVerifier: boolean;
};

function getNgrokBypassHeaders(): Record<string, string> {
  if (API_BASE.includes("ngrok-free.")) {
    return { "ngrok-skip-browser-warning": "true" };
  }
  return {};
}

async function parseError(response: Response, fallback: string): Promise<Error> {
  try {
    const body = (await response.json()) as { detail?: string };
    if (body.detail) {
      return new Error(body.detail);
    }
  } catch {
    // Ignore parse error and keep fallback
  }
  return new Error(fallback);
}

export async function checkHealth(): Promise<HealthResponse> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 10_000);

  try {
    const response = await fetch(`${API_BASE}/health`, {
      signal: controller.signal,
      headers: getNgrokBypassHeaders()
    });
    if (!response.ok) {
      throw new Error(`Health check failed (${response.status})`);
    }
    return (await response.json()) as HealthResponse;
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function uploadAudio(uri: string): Promise<TranscribeResponse> {
  const data = new FormData();
  data.append("audio", {
    uri,
    name: "recording.m4a",
    type: "audio/m4a"
  } as unknown as Blob);

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), UPLOAD_TIMEOUT_MS);

  try {
    const response = await fetch(`${API_BASE}/transcribe`, {
      method: "POST",
      body: data,
      signal: controller.signal,
      headers: getNgrokBypassHeaders()
    });

    if (!response.ok) {
      throw await parseError(response, `Upload failed (${response.status})`);
    }

    return (await response.json()) as TranscribeResponse;
  } finally {
    clearTimeout(timeoutId);
  }
}

export async function listNotes(): Promise<NoteSummary[]> {
  const response = await fetch(`${API_BASE}/notes`, {
    headers: getNgrokBypassHeaders()
  });
  if (!response.ok) {
    throw await parseError(response, `List notes failed (${response.status})`);
  }
  return (await response.json()) as NoteSummary[];
}

export async function getNote(noteId: string): Promise<NoteDetail> {
  const response = await fetch(`${API_BASE}/notes/${noteId}`, {
    headers: getNgrokBypassHeaders()
  });
  if (!response.ok) {
    throw await parseError(response, `Get note failed (${response.status})`);
  }
  return (await response.json()) as NoteDetail;
}

export async function createSheetFromTranscript(transcriptId: string, text: string): Promise<SheetDetail> {
  const response = await fetch(`${API_BASE}/sheets/from-transcript`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...getNgrokBypassHeaders()
    },
    body: JSON.stringify({ transcriptId, text })
  });
  if (!response.ok) {
    throw await parseError(response, `Create sheet failed (${response.status})`);
  }
  return (await response.json()) as SheetDetail;
}

export async function listSheets(): Promise<SheetSummary[]> {
  const response = await fetch(`${API_BASE}/sheets/`, {
    headers: getNgrokBypassHeaders()
  });
  if (!response.ok) {
    throw await parseError(response, `List sheets failed (${response.status})`);
  }
  return (await response.json()) as SheetSummary[];
}
