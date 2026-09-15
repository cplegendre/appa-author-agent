"""Compatibility facade for orchestration helpers.

Implementation is split by responsibility across dedicated modules, but these
imports remain intentionally re-exported for existing callers and tests.
"""

from .orchestration_factual import (
    FactualGroundingError,
    _cross_draft_similarity,
    _factual_rejections,
    _validate_factual_grounding,
)
from .orchestration_generation import (
    _clean_string,
    _extract_generated_text,
    _find_field_value,
    _generate_social_with_retry,
    _generate_targeted_text_with_retry,
    _normalize_social_payload,
    _payload_sample,
    _payload_shape,
    _text_from_value,
)
from .orchestration_review import (
    regenerate_output_field,
    update_output_drafts,
)
from .orchestration_scheduling import (
    load_releases,
    release_candidates,
    today_cmd,
)
from .orchestration_types import OrchestrationDeps
from .orchestration_validation import (
    _current_release_facts,
    #    _looks_like_single_dense_block,
    _metadata_search_text,
    _reads_as_not_yet_available,
    _reject_leaked_placeholder,
    _reject_social_formatting,
    _trim_excess_hashtags,
    _urls_in,
    _validate_current_release_metadata,
    _validate_release_field_contract,
    _validate_release_social_contract,
)
from .publishing_orchestration import (
    evergreen_cmd,
    output_dir,
    preview_and_report,
    release_cmd,
    release_output,
)

__all__ = [
    "FactualGroundingError",
    "OrchestrationDeps",
    "_clean_string",
    "_cross_draft_similarity",
    "_current_release_facts",
    "_extract_generated_text",
    "_factual_rejections",
    "_find_field_value",
    "_generate_social_with_retry",
    "_generate_targeted_text_with_retry",
    #    "_looks_like_single_dense_block",
    "_metadata_search_text",
    "_normalize_social_payload",
    "_payload_sample",
    "_payload_shape",
    "_reads_as_not_yet_available",
    "_reject_leaked_placeholder",
    "_reject_social_formatting",
    "_text_from_value",
    "_trim_excess_hashtags",
    "_urls_in",
    "_validate_current_release_metadata",
    "_validate_factual_grounding",
    "_validate_release_field_contract",
    "_validate_release_social_contract",
    "evergreen_cmd",
    "load_releases",
    "output_dir",
    "preview_and_report",
    "regenerate_output_field",
    "release_candidates",
    "release_cmd",
    "release_output",
    "today_cmd",
    "update_output_drafts",
]
