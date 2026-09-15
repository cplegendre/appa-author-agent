from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from .errors import ConfigError


class VoiceSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_words: int = Field(ge=1, le=2000)
    max_words: int = Field(ge=1, le=3000)
    hashtag_min: int = Field(default=0, ge=0, le=50)
    hashtag_max: int = Field(default=0, ge=0, le=50)
    guidance: list[str] = Field(default_factory=list)


class TeaserVoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_words: int = Field(default=30, ge=1, le=500)
    max_words: int = Field(default=70, ge=1, le=800)
    guidance: list[str] = Field(default_factory=list)


class BrandVoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facebook: VoiceSection
    instagram: VoiceSection
    teaser: TeaserVoice
    factual_grounding: list[str] = Field(default_factory=list)
    avoid_phrases: list[str] = Field(default_factory=list)
    cross_draft_similarity_warning: float = Field(default=0.84, ge=0.0, le=1.0)
    style_examples_per_platform: int = Field(default=3, ge=0, le=8)
    enforce_release_metadata: bool = False
    factual_review_enabled: bool = False

    def prompt_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="python")


_DEFAULTS: dict[str, Any] = {
    "facebook": {
        "min_words": 250,
        "max_words": 450,
        "hashtag_min": 0,
        "hashtag_max": 0,
        "guidance": [
            "Open with a short series-continuity or story-theme hook.",
            "State exact title, series/book position, and publication status early.",
            "Anchor the post in one concrete scene before reflecting on the theme.",
            "Use short reflective paragraphs written for parents, teachers, librarians, and read-aloud adults.",
            "For bilingual books, explain naturally how English and French support the story "
            "without turning the post into a lesson plan.",
            "Include a compact book-information block and the direct Amazon URL when published.",
            "End with a warm series-continuity sentence and a brief thank-you.",
        ],
    },
    "instagram": {
        "min_words": 140,
        "max_words": 260,
        "hashtag_min": 12,
        "hashtag_max": 16,
        "guidance": [
            "Open with one concise reflective sentence tied to the story theme.",
            "State title and availability near the top.",
            "Describe one concrete story moment, then add one or two short reflective paragraphs.",
            "Use a compact title/series block and 'link in bio' for published books.",
            "Keep the copy narrative and warm; do not merely shorten Facebook.",
            "Use relevant hashtags, favoring series, bilingual, picture-book, read-aloud, and story-specific themes.",
        ],
    },
    "teaser": {
        "min_words": 30,
        "max_words": 70,
        "guidance": [
            "Reveal the central situation and one emotional or narrative question only.",
            "Do not reveal the resolution, lesson learned, or full character arc.",
            "Create curiosity and include release timing without claiming availability before publication.",
        ],
    },
    "factual_grounding": [
        "Every concrete scene detail must come directly from the factual BookProfile.",
        "Never invent scenery, weather, gestures, body language, dialogue, "
        "appearance details, emotions, or plot events.",
        "Never infer character gender or pronouns; use names or neutral phrasing unless explicitly supported.",
        "Never invent educational, developmental, therapeutic, classroom, or research claims.",
        "Never construct or guess a URL; use RELEASE_URL exactly as supplied or omit it.",
    ],
    "avoid_phrases": [
        "heartwarming story",
        "perfect for little readers",
        "magical journey",
        "find their voice",
        "must-have",
        "building bridges",
        "every journey begins with a single step",
    ],
    "cross_draft_similarity_warning": 0.84,
    "style_examples_per_platform": 3,
    "enforce_release_metadata": False,
    "factual_review_enabled": False,
}


def load_brand_voice(root: Path) -> BrandVoice:
    path = root / "config/brand_voice.yaml"
    if not path.exists():
        return BrandVoice.model_validate(_DEFAULTS)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Could not load brand voice configuration `{path}`: {exc}") from exc
    try:
        return BrandVoice.model_validate(data)
    except PydanticValidationError as exc:
        errors = "; ".join(f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in exc.errors())
        raise ConfigError(f"Invalid brand voice configuration: {errors}") from exc
