"""Pydantic models for MedicalSheet."""

from pydantic import BaseModel


class Patient(BaseModel):
    name: str | None = None
    age: int | None = None
    sex: str | None = None
    motif: str | None = None


class Tests(BaseModel):
    bio: list[str] = []
    imaging: list[str] = []
    ecg: list[str] = []
    gas: list[str] = []


class Meta(BaseModel):
    createdAt: str
    transcriptId: str
    confidence: float | None = None


class MedicalSheet(BaseModel):
    id: str
    patient: Patient
    antecedents: list[str]
    homeTreatment: list[str]
    history: list[str]
    exam: list[str]
    tests: Tests
    diagnosis: list[str]
    treatmentPlan: list[str]
    orientation: list[str]
    meta: Meta
