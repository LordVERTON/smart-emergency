"""LangGraph orchestration using LangChain prompts/parsers."""

from __future__ import annotations

import os
from typing import Any, TypedDict

from pydantic import BaseModel, Field


class AIStructuredNote(BaseModel):
    """Structured medical note extracted by LLM."""

    motif: str = Field(default="")
    histoire_maladie: str = Field(default="")
    antecedents: str = Field(default="")
    traitements: str = Field(default="")
    allergies: str = Field(default="")
    examen_clinique: str = Field(default="")
    constantes: str = Field(default="")
    hypotheses: str = Field(default="")
    plan: str = Field(default="")
    a_verifier: bool = Field(default=True)


class AIExtractionState(TypedDict):
    """State container for graph nodes."""

    transcript: str
    structured: dict[str, Any]
    confidence_by_field: dict[str, float]
    validation_issues: list[str]
    requires_review: bool


class AIExtractionResult(BaseModel):
    """Final graph output payload."""

    structured: AIStructuredNote
    confidence_by_field: dict[str, float]
    average_confidence: float
    validation_issues: list[str]
    requires_review: bool


def _build_llm():
    """
    Build the LangChain chat model.
    Raises RuntimeError if provider config is missing.
    """
    provider = os.getenv("AI_PROVIDER", "openai").strip().lower()
    if provider != "openai":
        raise RuntimeError(f"Unsupported AI_PROVIDER: {provider}. Expected 'openai'.")

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is required for AI extraction.")

    from langchain_openai import ChatOpenAI

    model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    return ChatOpenAI(model=model_name, temperature=0)


def _field_confidence(value: str) -> float:
    """
    Compute a simple confidence score for one extracted field.
    Rule-based to remain deterministic and cheap at runtime.
    """
    normalized = (value or "").strip()
    if not normalized:
        return 0.1
    if len(normalized) < 8:
        return 0.4
    if len(normalized) < 20:
        return 0.65
    return 0.85


def extract_structured_note_with_graph(transcript: str) -> AIExtractionResult:
    """
    Extract a strict structured note from transcript using:
    LangGraph (orchestration) + LangChain (prompt/parsing).
    """
    from langchain.output_parsers import PydanticOutputParser
    from langchain_core.prompts import PromptTemplate
    from langgraph.graph import END, StateGraph

    parser = PydanticOutputParser(pydantic_object=AIStructuredNote)
    llm = _build_llm()

    prompt = PromptTemplate(
        template=(
            "Tu es un assistant médical de structuration.\n"
            "Objectif: extraire uniquement les informations explicitement présentes dans le transcript.\n"
            "Si une information est absente, renvoie une chaine vide.\n"
            "Ne jamais inventer.\n\n"
            "{format_instructions}\n\n"
            "Transcript:\n{transcript}\n"
        ),
        input_variables=["transcript"],
        partial_variables={"format_instructions": parser.get_format_instructions()},
    )

    def llm_extract_node(state: AIExtractionState) -> AIExtractionState:
        prompt_value = prompt.format(transcript=state["transcript"])
        ai_message = llm.invoke(prompt_value)
        parsed = parser.parse(ai_message.content)
        structured = parsed.model_dump()

        confidence_by_field = {
            "motif": _field_confidence(structured.get("motif", "")),
            "histoire_maladie": _field_confidence(structured.get("histoire_maladie", "")),
            "antecedents": _field_confidence(structured.get("antecedents", "")),
            "traitements": _field_confidence(structured.get("traitements", "")),
            "allergies": _field_confidence(structured.get("allergies", "")),
            "examen_clinique": _field_confidence(structured.get("examen_clinique", "")),
            "constantes": _field_confidence(structured.get("constantes", "")),
            "hypotheses": _field_confidence(structured.get("hypotheses", "")),
            "plan": _field_confidence(structured.get("plan", "")),
        }
        return {
            "transcript": state["transcript"],
            "structured": structured,
            "confidence_by_field": confidence_by_field,
            "validation_issues": [],
            "requires_review": True,
        }

    def clinical_validation_node(state: AIExtractionState) -> AIExtractionState:
        """
        Separate validation node (production-ready graph stage).
        Ensures minimum clinical completeness and computes review flag.
        """
        structured = state["structured"]
        confidence_by_field = dict(state["confidence_by_field"])
        validation_issues: list[str] = []

        required_fields = ["motif", "histoire_maladie", "plan"]
        for field_name in required_fields:
            if not str(structured.get(field_name, "")).strip():
                validation_issues.append(f"Champ clinique manquant: {field_name}")
                confidence_by_field[field_name] = min(confidence_by_field.get(field_name, 0.1), 0.2)

        if str(structured.get("allergies", "")).strip() == "":
            validation_issues.append("Allergies non précisées")

        avg_conf = sum(confidence_by_field.values()) / len(confidence_by_field)
        requires_review = avg_conf < 0.7 or len(validation_issues) > 0
        structured["a_verifier"] = requires_review

        return {
            "transcript": state["transcript"],
            "structured": structured,
            "confidence_by_field": confidence_by_field,
            "validation_issues": validation_issues,
            "requires_review": requires_review,
        }

    workflow = StateGraph(AIExtractionState)
    workflow.add_node("llm_extract", llm_extract_node)
    workflow.add_node("clinical_validate", clinical_validation_node)
    workflow.set_entry_point("llm_extract")
    workflow.add_edge("llm_extract", "clinical_validate")
    workflow.add_edge("clinical_validate", END)
    app = workflow.compile()

    final_state = app.invoke(
        {
            "transcript": transcript,
            "structured": {},
            "confidence_by_field": {},
            "validation_issues": [],
            "requires_review": True,
        }
    )
    average_confidence = (
        sum(final_state["confidence_by_field"].values()) / len(final_state["confidence_by_field"])
        if final_state["confidence_by_field"]
        else 0.0
    )
    return AIExtractionResult(
        structured=AIStructuredNote(**final_state["structured"]),
        confidence_by_field=final_state["confidence_by_field"],
        average_confidence=round(average_confidence, 3),
        validation_issues=final_state["validation_issues"],
        requires_review=final_state["requires_review"],
    )
