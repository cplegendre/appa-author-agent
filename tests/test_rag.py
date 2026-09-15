from unittest.mock import Mock, patch
from author_agent.rag import RagStore, normalize_post


def test_cosine_identity():
    assert abs(RagStore._cosine([1.0, 2.0], [1.0, 2.0]) - 1.0) < 1e-12


def test_cosine_orthogonal():
    assert RagStore._cosine([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_normalize_meta_like_post():
    got = normalize_post({"message": "Hello readers", "created_time": "2026-09-10", "id": "123"}, "facebook")
    assert got["text"] == "Hello readers"
    assert got["platform"] == "facebook"
    assert got["external_id"] == "123"


def test_embed_uses_mocked_network(tmp_path):
    resp = Mock(status_code=200)
    resp.json.return_value = {"embeddings": [[1.0, 0.0]]}
    with patch("author_agent.rag.post_json", return_value=resp):
        store = RagStore(tmp_path / "rag.db", "http://localhost:11434", "embeddinggemma:latest")
        assert store.embed("hello") == [1.0, 0.0]
