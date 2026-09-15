from pathlib import Path

from author_agent.orchestration_generation import _generate_social_with_retry
from author_agent.orchestration_types import OrchestrationDeps
from author_agent.orchestration_validation import _reject_social_formatting


def _deps(responses, prompts):
    queue = list(responses)

    def generate_json(_base_url, _model, prompt, _timeout):
        prompts.append(prompt)
        return queue.pop(0)

    return OrchestrationDeps(
        root=Path("."),
        settings={},
        rag_store=lambda: None,
        analyze_book=lambda _p: {},
        generate_json=generate_json,
        render=lambda *_a, **_k: "BASE SOCIAL PROMPT",
        prepare_website_update=lambda *_a, **_k: {},
        duplicate_report=lambda *_a, **_k: {},
        rag_context=lambda *_a, **_k: [],
        style_examples=lambda *_a, **_k: {},
        brand_voice={},
        user_output=lambda _v: None,
    )


def _validate(payload):
    for field in ("facebook", "instagram", "teaser"):
        _reject_social_formatting(field, payload[field])


def _long_block(prefix="Plain"):
    return " ".join([prefix] + [f"word{i}" for i in range(90)])


def test_markdown_draft_is_rejected_and_regenerated_not_stripped():
    prompts = []
    clean_fb = "A clean opening about the story.\n\nA second paragraph keeps the copy readable."
    clean_ig = "A clean Instagram opening.\n\nA second paragraph. #ChildrensBooks #PictureBooks"
    responses = [
        {
            "facebook": "A *special* story.\n\nSecond paragraph.",
            "instagram": clean_ig,
            "teaser": "A short teaser.",
        },
        {"facebook": clean_fb, "instagram": clean_ig, "teaser": "A short teaser."},
    ]
    result = _generate_social_with_retry(
        _deps(responses, prompts),
        {"base_url": "http://localhost", "marketing_model": "qwen", "timeout_seconds": 10},
        "social_release.txt",
        ("facebook", "instagram", "teaser"),
        {},
        label="release",
        post_validate=_validate,
    )

    assert len(prompts) == 2
    assert result["facebook"] == clean_fb
    assert "*special*" not in result["facebook"]
    assert "Markdown formatting" in prompts[1]


def test_long_single_block_draft_is_rejected_and_regenerated():
    prompts = []
    bad_fb = _long_block("Facebook")
    clean_fb = (
        "Readable first paragraph with a concrete story moment.\n\nReadable second paragraph with the reflection."
    )
    responses = [
        {"facebook": bad_fb, "instagram": "Short IG.\n\nSecond paragraph.", "teaser": "Short teaser."},
        {"facebook": clean_fb, "instagram": "Short IG.\n\nSecond paragraph.", "teaser": "Short teaser."},
    ]
    result = _generate_social_with_retry(
        _deps(responses, prompts),
        {"base_url": "http://localhost", "marketing_model": "qwen", "timeout_seconds": 10},
        "social_release.txt",
        ("facebook", "instagram", "teaser"),
        {},
        label="release",
        post_validate=_validate,
    )

    assert len(prompts) == 2
    assert result["facebook"] == clean_fb
    assert "no blank-line paragraph separator" in prompts[1]


def test_plain_text_with_multiple_paragraphs_passes_without_retry():
    prompts = []
    facebook = _long_block("Opening") + "\n\n" + "A final short paragraph."
    instagram = _long_block("Instagram") + "\n\n" + "#ChildrensBooks #PictureBooks"
    responses = [{"facebook": facebook, "instagram": instagram, "teaser": "What happens next?"}]

    result = _generate_social_with_retry(
        _deps(responses, prompts),
        {"base_url": "http://localhost", "marketing_model": "qwen", "timeout_seconds": 10},
        "social_release.txt",
        ("facebook", "instagram", "teaser"),
        {},
        label="release",
        post_validate=_validate,
    )

    assert len(prompts) == 1
    assert result["facebook"] == facebook
    assert result["instagram"] == instagram
