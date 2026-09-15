"""Regression test for a bug found in real usage: correctly-worded Facebook/Instagram
posts were coming back as one dense, unbroken paragraph instead of the short,
reflective paragraphs with breathing room the author's real posts use — even though
the prompt already asked for "2-4 short reflective paragraphs".

Fix: (1) the prompt now explicitly demands literal "\n\n" breaks with a concrete
example, and (2) as a deterministic safety net, code reflows an unbroken block into
short paragraphs by sentence grouping if the model ignores the instruction anyway.
"""
from author_agent.orchestration import (
    _looks_like_single_dense_block,
    _reflow_into_paragraphs,
    _validate_release_social_contract,
)

# The exact shape of text reported as a bug: one long run-on paragraph, no breaks
# until the 📚 metadata footer.
DENSE_FACEBOOK_TEXT = (
    "Yok has always felt most at home in the quiet corners of her world, where her "
    "green scales and long tail are part of her story and not something to hide. "
    "Now, in Yok's First Friend, the first book in the A Yok Story series, we follow "
    "her as she steps outside and into the wide world of the park. There, she meets "
    "Tom, who sees her not as different, but as simply Yok, and that small moment of "
    "connection becomes the first step toward something bigger. It's not always easy "
    "to take that first step, but with kindness and patience, even the smallest "
    "gestures can make a big difference. This story reminds us that everyone has "
    "their own way of moving through the world, and that friendship can begin with "
    "just one shared moment. 📚 Yok's First Friend A Yok Story · Book 1 of 10 Now "
    "available in paperback on Amazon: https://www.amazon.com/dp/B0H72C7X1N Thank "
    "you for being part of Yok's journey."
)


def test_dense_block_is_detected():
    assert _looks_like_single_dense_block(DENSE_FACEBOOK_TEXT) is True


def test_well_formatted_text_with_breaks_is_not_flagged_as_dense():
    formatted = (
        "Opening hook.\n\nA short reflective paragraph.\n\nAnother short paragraph.\n\n"
        "📚 Title\nSeries · Book 1 of 10\n\nThank you for reading."
    )
    assert _looks_like_single_dense_block(formatted) is False


def test_short_text_is_never_flagged_as_dense_even_without_breaks():
    # A short teaser with no paragraph breaks is fine — this only matters for
    # genuinely long, wall-of-text posts.
    assert _looks_like_single_dense_block("A short teaser sentence.") is False


def test_reflow_splits_dense_block_into_multiple_short_paragraphs():
    reflowed = _reflow_into_paragraphs(DENSE_FACEBOOK_TEXT)
    paragraphs = [p for p in reflowed.split("\n\n") if p.strip()]
    assert len(paragraphs) >= 3
    # Every original sentence must survive the reflow — nothing lost, only reshaped.
    assert "green scales and long tail" in reflowed
    assert "Thank you for being part of Yok's journey." in reflowed


def test_reflow_keeps_the_metadata_footer_intact_as_its_own_block():
    reflowed = _reflow_into_paragraphs(DENSE_FACEBOOK_TEXT)
    footer_paragraph = reflowed.split("\n\n")[-1]
    assert footer_paragraph.startswith("📚")
    assert "Book 1 of 10" in footer_paragraph


def test_release_social_contract_auto_reflows_dense_facebook_and_instagram():
    dense_instagram = DENSE_FACEBOOK_TEXT.replace(
        "Now available in paperback on Amazon: https://www.amazon.com/dp/B0H72C7X1N",
        "Now available on Amazon — link in bio.",
    )
    payload = {
        "facebook": DENSE_FACEBOOK_TEXT,
        "instagram": dense_instagram,
        "teaser": "A short spoiler-safe teaser line.",
    }
    _validate_release_social_contract(
        payload, status="published", release_url="https://www.amazon.com/dp/B0H72C7X1N", brand_voice={}
    )
    assert payload["facebook"].count("\n\n") >= 2
    assert payload["instagram"].count("\n\n") >= 2
    # Teaser is untouched — it's short and wasn't part of this fix's scope.
    assert payload["teaser"] == "A short spoiler-safe teaser line."


def test_already_well_formatted_facebook_post_is_left_untouched():
    good = (
        "Opening hook.\n\nA short reflective paragraph.\n\nAnother short paragraph.\n\n"
        "📚 Title\nSeries · Book 1 of 10\n\nThank you for reading."
    )
    payload = {"facebook": good, "instagram": "Short caption. #a #b", "teaser": "Teaser."}
    _validate_release_social_contract(payload, status="published", release_url="", brand_voice={})
    assert payload["facebook"] == good
