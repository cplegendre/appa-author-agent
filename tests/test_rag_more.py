from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest

from author_agent.ollama_client import OllamaError
from author_agent.rag import (
    RagStore,
    load_posts_file,
    parse_meta_facebook,
    parse_meta_instagram,
)


def _store(tmp_path):
    return RagStore(tmp_path / "rag.db", "http://localhost:11434", "embeddinggemma:latest")


# ---------------------------------------------------------------------------
# embed(): empty text, legacy /api/embeddings fallback, 404 on both, bad payload
# ---------------------------------------------------------------------------


def test_embed_rejects_empty_text(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.embed("   ")


def test_embed_falls_back_to_legacy_endpoint_on_404(tmp_path):
    store = _store(tmp_path)
    modern = Mock(status_code=404)
    legacy = Mock(status_code=200)
    legacy.json.return_value = {"embedding": [0.5, 0.5]}
    with patch("author_agent.rag.post_json", side_effect=[modern, legacy]) as mocked:
        result = store.embed("hello world")
    assert result == [0.5, 0.5]
    assert mocked.call_count == 2
    assert mocked.call_args_list[1].args[1] == "/api/embeddings"


def test_embed_raises_actionable_error_when_both_endpoints_404(tmp_path):
    store = _store(tmp_path)
    both_404 = Mock(status_code=404)
    with patch("author_agent.rag.post_json", side_effect=[both_404, both_404]):
        with pytest.raises(OllamaError, match="embedding endpoint was not found"):
            store.embed("hello")


def test_embed_raises_on_unexpected_payload_shape(tmp_path):
    store = _store(tmp_path)
    resp = Mock(status_code=200)
    resp.json.return_value = {"unexpected": True}
    with patch("author_agent.rag.post_json", return_value=resp):
        with pytest.raises(OllamaError, match="Unexpected Ollama embedding response"):
            store.embed("hello")


# ---------------------------------------------------------------------------
# upsert(): insert, update-on-conflict, empty text guard
# ---------------------------------------------------------------------------


def _fake_embed_response(vector):
    resp = Mock(status_code=200)
    resp.json.return_value = {"embeddings": [vector]}
    return resp


def test_upsert_rejects_empty_text(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.upsert(kind="post", text="   ")


def test_upsert_inserts_then_updates_same_external_id(tmp_path):
    store = _store(tmp_path)
    with patch("author_agent.rag.post_json", return_value=_fake_embed_response([1.0, 0.0])):
        first_id = store.upsert(
            kind="post",
            text="Original text",
            source="fb",
            external_id="123",
            platform="facebook",
            date="2026-01-01",
        )
    with patch("author_agent.rag.post_json", return_value=_fake_embed_response([0.0, 1.0])):
        second_id = store.upsert(
            kind="post",
            text="Updated text",
            source="fb",
            external_id="123",
            platform="facebook",
            date="2026-01-02",
        )
    assert first_id == second_id
    assert store.stats()["total"] == 1


def test_upsert_without_external_id_always_inserts(tmp_path):
    store = _store(tmp_path)
    with patch("author_agent.rag.post_json", return_value=_fake_embed_response([1.0, 0.0])):
        store.upsert(kind="post", text="A", source="fb")
        store.upsert(kind="post", text="B", source="fb")
    assert store.stats()["total"] == 2


# ---------------------------------------------------------------------------
# search(): filtering by kind/platform, top_k truncation, ranking
# ---------------------------------------------------------------------------


def test_search_filters_by_kind_and_platform_and_ranks_by_similarity(tmp_path):
    store = _store(tmp_path)
    vectors = {
        "close": [1.0, 0.0],
        "far": [0.0, 1.0],
    }
    with patch("author_agent.rag.post_json") as mocked:
        mocked.side_effect = [_fake_embed_response(vectors["close"]), _fake_embed_response(vectors["far"])]
        store.upsert(kind="post", text="Close post", source="s", external_id="1", platform="facebook")
        store.upsert(kind="book", text="Far book", source="s", external_id="2", platform="")

    with patch("author_agent.rag.post_json", return_value=_fake_embed_response([1.0, 0.0])):
        hits = store.search("query", top_k=5, kinds=["post"], platforms=["facebook"])
    assert len(hits) == 1
    assert hits[0].text == "Close post"


def test_search_respects_top_k(tmp_path):
    store = _store(tmp_path)
    with patch("author_agent.rag.post_json", return_value=_fake_embed_response([1.0, 0.0])):
        for i in range(5):
            store.upsert(kind="post", text=f"Post {i}", source="s", external_id=str(i), platform="facebook")
    with patch("author_agent.rag.post_json", return_value=_fake_embed_response([1.0, 0.0])):
        hits = store.search("query", top_k=2)
    assert len(hits) == 2


# ---------------------------------------------------------------------------
# stats() / recent_posts()
# ---------------------------------------------------------------------------


def test_stats_groups_by_kind_and_platform(tmp_path):
    store = _store(tmp_path)
    with patch("author_agent.rag.post_json", return_value=_fake_embed_response([1.0, 0.0])):
        store.upsert(kind="post", text="A", source="s", external_id="1", platform="facebook")
        store.upsert(kind="post", text="B", source="s", external_id="2", platform="instagram")
        store.upsert(kind="book", text="C", source="s", external_id="3")
    stats = store.stats()
    assert stats["total"] == 3
    assert stats["by_kind"] == {"book": 1, "post": 2}
    assert stats["by_platform"]["facebook"] == 1
    assert stats["by_platform"]["n/a"] == 1


def test_recent_posts_only_returns_post_kind_ordered_by_date(tmp_path):
    store = _store(tmp_path)
    with patch("author_agent.rag.post_json", return_value=_fake_embed_response([1.0, 0.0])):
        store.upsert(kind="post", text="Older", source="s", external_id="1", platform="facebook", date="2026-01-01")
        store.upsert(kind="post", text="Newer", source="s", external_id="2", platform="facebook", date="2026-02-01")
        store.upsert(kind="book", text="Not a post", source="s", external_id="3", date="2026-03-01")
    recent = store.recent_posts()
    assert [r["text"] for r in recent] == ["Newer", "Older"]


# ---------------------------------------------------------------------------
# load_posts_file(): csv / json variants / txt / unsupported
# ---------------------------------------------------------------------------


def test_load_posts_file_csv(tmp_path):
    path = tmp_path / "posts.csv"
    path.write_text("date,platform,text,id\n2026-01-10,instagram,Hello,ig-1\n", encoding="utf-8")
    rows = load_posts_file(path)
    assert rows[0]["text"] == "Hello"


def test_load_posts_file_json_array(tmp_path):
    path = tmp_path / "posts.json"
    path.write_text(json.dumps([{"text": "Hi"}]), encoding="utf-8")
    assert load_posts_file(path) == [{"text": "Hi"}]


def test_load_posts_file_json_wrapped_object(tmp_path):
    path = tmp_path / "posts.json"
    path.write_text(json.dumps({"data": [{"text": "Wrapped"}]}), encoding="utf-8")
    assert load_posts_file(path) == [{"text": "Wrapped"}]


def test_load_posts_file_json_without_recognized_key_raises(tmp_path):
    path = tmp_path / "posts.json"
    path.write_text(json.dumps({"nope": []}), encoding="utf-8")
    with pytest.raises(ValueError, match="posts/data/items"):
        load_posts_file(path)


def test_load_posts_file_txt_wraps_whole_file(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("Just some text", encoding="utf-8")
    rows = load_posts_file(path)
    assert rows == [{"text": "Just some text", "source": "notes.txt"}]


def test_load_posts_file_rejects_unsupported_extension(tmp_path):
    path = tmp_path / "posts.xyz"
    path.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported posts file"):
        load_posts_file(path)


# ---------------------------------------------------------------------------
# Meta export parsers
# ---------------------------------------------------------------------------


def test_parse_meta_facebook_extracts_text_and_date(tmp_path):
    path = tmp_path / "your_posts_1.json"
    path.write_text(
        json.dumps(
            {
                "posts_v2": [
                    {
                        "timestamp": 1738000000,
                        "data": [{"post": "Hello readers, new chapter is out!"}],
                    },
                    {"timestamp": 1738000001, "data": []},  # no text -> filtered out
                ]
            }
        ),
        encoding="utf-8",
    )
    rows = parse_meta_facebook(path)
    assert len(rows) == 1
    assert "Hello readers" in rows[0]["text"]
    assert rows[0]["platform"] == "facebook"
    assert rows[0]["date"]


def test_parse_meta_facebook_handles_plain_list(tmp_path):
    path = tmp_path / "posts.json"
    path.write_text(json.dumps([{"data": [{"post": "Plain list post"}], "timestamp": 1700000000}]), encoding="utf-8")
    rows = parse_meta_facebook(path)
    assert rows[0]["text"] == "Plain list post"


def test_parse_meta_instagram_extracts_captions_from_media(tmp_path):
    path = tmp_path / "posts_1.json"
    path.write_text(
        json.dumps([{"media": [{"title": "A lovely bedtime story caption", "creation_timestamp": 1738000000}]}]),
        encoding="utf-8",
    )
    rows = parse_meta_instagram(path)
    assert len(rows) == 1
    assert "bedtime story" in rows[0]["text"]
    assert rows[0]["platform"] == "instagram"


def test_parse_meta_instagram_wrapped_object(tmp_path):
    path = tmp_path / "posts.json"
    path.write_text(json.dumps({"ig_posts": [{"media": [{"caption": "Wrapped caption"}]}]}), encoding="utf-8")
    rows = parse_meta_instagram(path)
    assert rows[0]["text"] == "Wrapped caption"


def test_parse_meta_instagram_skips_empty_text_rows(tmp_path):
    path = tmp_path / "posts.json"
    path.write_text(json.dumps([{"media": []}]), encoding="utf-8")
    rows = parse_meta_instagram(path)
    assert rows == []
