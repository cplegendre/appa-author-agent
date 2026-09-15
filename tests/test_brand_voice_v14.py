from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


from author_agent import main
from author_agent.brand_voice import load_brand_voice
from author_agent.orchestration import _cross_draft_similarity
from author_agent.rag import RagHit


class StyleStore:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def search(self, query, **kwargs):
        self.calls.append({"query": query, **kwargs})
        platform = (kwargs.get("platforms") or [""])[0]
        return [
            RagHit(
                id=1,
                kind="post",
                source="meta",
                external_id=f"{platform}-1",
                title="",
                text=f"historical {platform} post",
                date="2026-08-01",
                platform=platform,
                topic="friendship",
                score=0.91,
                metadata={},
            )
        ]


def test_brand_voice_file_loads_expected_long_form_defaults():
    voice = load_brand_voice(Path(__file__).resolve().parents[1])
    assert voice.facebook.min_words == 250
    assert voice.facebook.max_words == 450
    assert voice.instagram.hashtag_min == 12
    assert voice.instagram.hashtag_max == 16
    assert voice.teaser.max_words == 70
    assert "perfect for little readers" in voice.avoid_phrases


def test_style_examples_are_platform_specific_and_post_only():
    store = StyleStore()
    voice = load_brand_voice(Path(__file__).resolve().parents[1]).prompt_dict()
    examples = main._style_examples(store, "friendship", voice)
    assert examples["facebook"][0]["platform"] == "facebook"
    assert examples["instagram"][0]["platform"] == "instagram"
    assert all(call["kinds"] == ["post"] for call in store.calls)
    assert {tuple(call["platforms"]) for call in store.calls} == {("facebook",), ("instagram",)}


class EmbedStore:
    def embed(self, text: str) -> list[float]:
        mapping = {
            "facebook": [1.0, 0.0],
            "instagram": [0.98, 0.02],
            "teaser": [0.0, 1.0],
        }
        return mapping[text]

    @staticmethod
    def _cosine(a, b):
        from author_agent.rag import RagStore

        return RagStore._cosine(a, b)


def test_cross_draft_similarity_flags_overlapping_new_copy():
    report = _cross_draft_similarity(
        EmbedStore(),
        {"facebook": "facebook", "instagram": "instagram", "teaser": "teaser"},
        0.84,
    )
    assert report["available"] is True
    assert report["warning"] is True
    flagged = [pair for pair in report["pairs"] if pair["warning"]]
    assert flagged[0]["left"] == "facebook"
    assert flagged[0]["right"] == "instagram"


def test_release_prompt_receives_brand_voice_style_examples_and_url(tmp_path, monkeypatch):
    book = tmp_path / "book.txt"
    book.write_text("book", encoding="utf-8")
    image = tmp_path / "promo.png"
    image.write_bytes(b"x")
    (tmp_path / "data").mkdir()

    monkeypatch.setattr(main, "ROOT", tmp_path)
    monkeypatch.setattr(
        main,
        "analyze_book",
        lambda _path: {
            "title": "Yok Test",
            "series": "A Bilingual Yok Story",
            "book_number": "3",
            "series_total": "6",
            "themes": ["feelings"],
            "summary_short": "A tower falls.",
        },
    )
    monkeypatch.setattr(main, "rag_store", lambda: StyleStore())
    captured: dict[str, str] = {}

    def fake_generate(_base, _model, prompt, _timeout):
        captured["prompt"] = prompt
        return {"facebook": "FB", "instagram": "IG", "teaser": "T"}

    monkeypatch.setattr(main, "generate_json", fake_generate)
    monkeypatch.setattr(main, "_duplicate_report", lambda *_args: {"warning": False})
    monkeypatch.setattr(main, "prepare_website_update", lambda *a, **k: {"status": "dry-run"})

    result, _ = main.release_cmd(
        SimpleNamespace(
            book=str(book),
            image=str(image),
            date="2026-09-13",
            url="https://amazon.example/book",
            published=True,
            dry_run=True,
            website_dry_run=True,
        ),
        emit=False,
    )
    prompt = captured["prompt"]
    assert "https://amazon.example/book" in prompt
    assert "250" in prompt and "450" in prompt
    assert "historical facebook post" in prompt
    assert "historical instagram post" in prompt
    assert result["style_examples"]["facebook"]
