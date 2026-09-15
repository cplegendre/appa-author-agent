"""Compatibility facade for orchestration responsibilities.

Implementation is split by responsibility; imports remain stable for callers/tests.
"""
from .orchestration_types import OrchestrationDeps
from .publishing_orchestration import output_dir, release_output, preview_and_report, release_cmd, evergreen_cmd
from .orchestration_generation import (
    _clean_string, _text_from_value, _find_field_value, _payload_shape, _payload_sample,
    _generate_social_with_retry, _generate_targeted_text_with_retry, _normalize_social_payload, _extract_generated_text,
)
from .orchestration_validation import (
    _urls_in, _reject_leaked_placeholder, _reject_social_formatting, _current_release_facts, _metadata_search_text,
    _validate_current_release_metadata, _reads_as_not_yet_available, _validate_release_field_contract,
    _trim_excess_hashtags, _validate_release_social_contract,
)
from .orchestration_factual import (
    _factual_rejections, FactualGroundingError, _validate_factual_grounding, _cross_draft_similarity,
)
from .orchestration_review import regenerate_output_field, update_output_drafts
from .orchestration_scheduling import load_releases, release_candidates, today_cmd

__all__ = [name for name in globals() if not name.startswith('__')]
