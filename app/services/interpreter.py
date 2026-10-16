from __future__ import annotations
import re
import json
import urllib.request
import urllib.error
from app.config import LLM_ENABLED, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_TIMEOUT_SECONDS
from app.schemas import InterpretationResponse


def _interpret_prompt_rules(prompt: str) -> InterpretationResponse:
    """Conservative, deterministic prompt parser; no LLM call or silent design inference."""
    text = " ".join(prompt.strip().split())
    lower = text.lower()
    product_type = None
    product_name = None
    if "workbench" in lower or "work bench" in lower:
        product_type = "workbench_panel_kit"
        product_name = "Workbench panel kit"
    elif "panel kit" in lower or "flat panel" in lower or "sheet panel" in lower:
        product_type = "flat_panel_kit"
        product_name = "Flat panel kit"
    elif "plate kit" in lower or "custom plate" in lower:
        product_type = "custom_plate_kit"
        product_name = "Custom plate kit"

    quantity = None
    qty_patterns = [
        r"\b(?:qty|quantity)\s*[:=]?\s*(\d+)\b",
        r"\b(\d+)\s+(?:units?|pieces?|pcs|workbenches|workbench|panels?|products?)\b",
    ]
    for pattern in qty_patterns:
        match = re.search(pattern, lower)
        if match:
            quantity = int(match.group(1))
            break

    dimension_match = re.search(
        r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:mm)?\s*[x×]\s*"
        r"(\d+(?:\.\d+)?)\s*(?:mm)?\s*[x×]\s*"
        r"(\d+(?:\.\d+)?)(?:\s*mm)?\b", lower
    )
    length = width = height = None
    if dimension_match:
        length, width, height = (float(dimension_match.group(i)) for i in (1, 2, 3))

    material_grade = None
    grade = re.search(r"\b(s275jr|s355jr|a36|mild steel|stainless steel)\b", lower)
    if grade:
        label = grade.group(1)
        material_grade = {"mild steel": "MILD_STEEL", "stainless steel": "STAINLESS_STEEL"}.get(label, label.upper())

    thickness = None
    thickness_match = re.search(r"\b(?:thickness|thick|plate|sheet)\s*(?:of|=|:)?\s*(\d+(?:\.\d+)?)\s*mm\b", lower)
    if thickness_match:
        thickness = float(thickness_match.group(1))
    else:
        thickness_match = re.search(r"\b(\d+(?:\.\d+)?)\s*mm\s*(?:thick|thickness|plate|sheet)\b", lower)
        if thickness_match:
            thickness = float(thickness_match.group(1))

    missing = []
    if product_type is None:
        missing.append("Which supported product template should be used? V1 supports a workbench panel kit, flat panel kit, or custom rectangular plate kit.")
    if quantity is None:
        missing.append("What is the required production quantity?")
    if length is None or width is None or height is None:
        missing.append("Provide overall product length × width × height in millimetres.")
    if material_grade is None:
        missing.append("Confirm the material grade (for example S275JR or MILD_STEEL); do not infer it from the product name.")
    if thickness is None:
        missing.append("Confirm the required plate thickness in millimetres.")

    found = sum([product_type is not None, quantity is not None, length is not None, material_grade is not None, thickness is not None])
    confidence = "high" if found == 5 and not missing else "medium" if found >= 3 else "low"
    assumptions = [
        "Prompt interpretation is a draft only; a human must verify every extracted field.",
        "V1 generates only a supported rectangular plate-component schedule; profile design, structural/load calculations, bends, weld design, and CNC release are out of scope.",
    ]
    return InterpretationResponse(
        product_type=product_type, product_name=product_name, quantity=quantity,
        length_mm=length, width_mm=width, height_mm=height,
        material_grade=material_grade, thickness_mm=thickness,
        confidence=confidence, interpreter_mode="deterministic_rules", missing_questions=missing, assumptions=assumptions,
        note="This is deterministic prompt parsing, not a generative CAD/LLM design. Confirm all extracted values before creating an order."
    )



def _interpret_prompt_llm(prompt: str) -> InterpretationResponse:
    if not LLM_API_KEY or not LLM_MODEL:
        raise RuntimeError("LLM is enabled but STEELMIND_LLM_API_KEY or STEELMIND_LLM_MODEL is missing")
    system_text = (
        "Extract order fields only. Do not design a product, infer unspecified engineering values, "
        "or claim structural safety. Supported product_type values: workbench_panel_kit, flat_panel_kit, "
        "custom_plate_kit. Return one JSON object with keys product_type, product_name, quantity, length_mm, "
        "width_mm, height_mm, material_grade, thickness_mm, confidence, missing_questions, assumptions, note. "
        "Use null for unknown values, list every missing question, and require a human to verify all fields. "
        "Never turn an overall dimension into a component dimension. Values must use millimetres. "
        "confidence must be low, medium, or high. Do not output markdown."
    )
    payload = {
        "model": LLM_MODEL,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system_text},
            {"role": "user", "content": prompt},
        ],
    }
    request = urllib.request.Request(
        f"{LLM_BASE_URL}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {LLM_API_KEY}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=LLM_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        data = json.loads(content)
        data["interpreter_mode"] = "configured_llm"
        data["note"] = str(data.get("note", "")) + " LLM extraction is untrusted draft data; human confirmation is mandatory."
        data.setdefault("assumptions", [])
        data.setdefault("missing_questions", [])
        return InterpretationResponse.model_validate(data)
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, ValueError, TypeError) as exc:
        raise RuntimeError(f"Configured LLM extraction failed: {exc}") from exc


def interpret_prompt(prompt: str) -> InterpretationResponse:
    """Use an explicitly configured OpenAI-compatible API, with deterministic fallback."""
    if LLM_ENABLED:
        try:
            return _interpret_prompt_llm(prompt)
        except Exception as exc:
            fallback = _interpret_prompt_rules(prompt)
            fallback.interpreter_mode = "deterministic_fallback"
            fallback.note = f"Configured LLM unavailable or invalid; deterministic rules used instead ({type(exc).__name__}). Confirm extracted fields manually."
            fallback.assumptions.append("An LLM failure occurred; output was not accepted from the model.")
            return fallback
    return _interpret_prompt_rules(prompt)
