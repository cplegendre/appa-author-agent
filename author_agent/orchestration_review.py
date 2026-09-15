from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import ValidationError
from .io_utils import load_json, save_json
from .orchestration_factual import _validate_factual_grounding
from .orchestration_generation import _generate_targeted_text_with_retry
from .orchestration_types import OrchestrationDeps
from .orchestration_validation import (
    _current_release_facts,
    _reject_social_formatting,
    _trim_excess_hashtags,
    _validate_release_field_contract,
)


def regenerate_output_field(path: Path, field: str, deps: OrchestrationDeps) -> dict:
    if field not in {"facebook", "instagram", "teaser"}:
        raise ValidationError("Field must be facebook, instagram, or teaser.")
    data = load_json(path, None)
    if not isinstance(data, dict):
        raise ValidationError(f"Invalid output JSON: {path}")
    store = deps.rag_store()
    ollama = deps.settings["ollama"]
    if isinstance(data.get("social"), dict):
        social = data["social"]
        profile = data.get("profile", {})
        query = " ".join([str(profile.get("title", "")), str(profile.get("summary_short", ""))]).strip() or path.stem
        rag_context = data.get("rag_context") or deps.rag_context(store, query)
        platform = "instagram" if field == "teaser" else field
        style_examples = deps.style_examples(store, query, deps.brand_voice, platforms=(platform,)).get(platform, [])
        book_value = str(data.get("book", "") or "")
        book_path = Path(book_value) if book_value else None
        book_evidence = (
            deps.book_evidence(store, book_path, f"{query} {social.get(field, '')}", top_k=10)
            if book_path is not None and book_path.is_file()
            else []
        )
        prompt = deps.render(
            "social_field.txt",
            FIELD=field,
            RELEASE_STATUS="published" if data.get("published") else "scheduled",
            RELEASE_DATE=data.get("release_date", data.get("date", "")),
            RELEASE_URL=data.get("url", ""),
            CURRENT_RELEASE_FACTS=_current_release_facts(
                profile if isinstance(profile, dict) else {},
                status="published" if data.get("published") else "scheduled",
                release_date=str(data.get("release_date", data.get("date", "")) or ""),
                release_url=str(data.get("url", "") or ""),
            ),
            BOOK_PROFILE=profile,
            BOOK_EVIDENCE=book_evidence,
            BRAND_VOICE=deps.brand_voice,
            RAG_CONTEXT=rag_context,
            STYLE_EXAMPLES=style_examples,
            CURRENT_TEXT=social.get(field, ""),
        )
        text = _generate_targeted_text_with_retry(
            deps,
            ollama,
            prompt,
            field,
            post_validate=lambda candidate: _reject_social_formatting(field, candidate),
            label="release_field",
        )
        instagram_voice = (
            deps.brand_voice.get("instagram", {}) if isinstance(deps.brand_voice.get("instagram"), dict) else {}
        )
        strict_editorial = bool(
            deps.brand_voice.get("enforce_release_metadata", False)
            and str(data.get("editorial_contract_version", "")) >= "0.16"
        )
        if field == "instagram" and strict_editorial:
            hashtag_max = int(instagram_voice.get("hashtag_max", 0) or 0)
            text = _trim_excess_hashtags(text, hashtag_max)
        _validate_release_field_contract(
            field,
            text,
            status="published" if data.get("published") else "scheduled",
            release_url=str(data.get("url", "") or ""),
            require_release_metadata=strict_editorial,
            release_facts=_current_release_facts(
                profile if isinstance(profile, dict) else {},
                status="published" if data.get("published") else "scheduled",
                release_date=str(data.get("release_date", data.get("date", "")) or ""),
                release_url=str(data.get("url", "") or ""),
            ),
            hashtag_min=(
                int(instagram_voice.get("hashtag_min", 0) or 0) if field == "instagram" and strict_editorial else 0
            ),
            hashtag_max=(
                int(instagram_voice.get("hashtag_max", 0) or 0) if field == "instagram" and strict_editorial else 0
            ),
        )
        if strict_editorial:
            _validate_factual_grounding(deps, ollama, profile, {field: text}, book_path=book_path)
        social[field] = text
        data.setdefault("duplicate_check", {})[field] = deps.duplicate_report(store, text, platform)
    else:
        if field == "teaser":
            raise ValidationError("Evergreen outputs do not have a teaser field.")
        idea = {key: data.get(key, "") for key in ("topic", "category", "angle")}
        context = deps.rag_context(
            store,
            " ".join(str(value) for value in idea.values()) or "children books evergreen",
            top_k=12,
        )
        style_examples = deps.style_examples(
            store,
            " ".join(str(value) for value in idea.values()) or "children books evergreen",
            deps.brand_voice,
            platforms=(field,),
        ).get(field, [])
        prompt = deps.render(
            "evergreen_field.txt",
            FIELD=field,
            IDEA=idea,
            BRAND_VOICE=deps.brand_voice,
            RAG_CONTEXT=context,
            STYLE_EXAMPLES=style_examples,
            CURRENT_TEXT=data.get(field, ""),
        )
        text = _generate_targeted_text_with_retry(
            deps,
            ollama,
            prompt,
            field,
            post_validate=lambda candidate: _reject_social_formatting(field, candidate),
            label="evergreen_field",
        )
        data[field] = text
        data.setdefault("duplicate_check", {})[field] = deps.duplicate_report(store, text, field)
    save_json(path, data)
    return {"field": field, "text": text, "duplicate_check": data["duplicate_check"][field], "output": str(path)}


def update_output_drafts(path: Path, drafts: dict[str, str]) -> dict:
    data = load_json(path, None)
    if not isinstance(data, dict):
        raise ValidationError(f"Invalid output JSON: {path}")
    raw_social = data.get("social")
    target: dict[str, Any] = raw_social if isinstance(raw_social, dict) else data
    for key, value in drafts.items():
        if key in {"facebook", "instagram", "teaser"} and value is not None:
            target[key] = str(value)
    save_json(path, data)
    return data
