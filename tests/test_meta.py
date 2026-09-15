import json
from author_agent.rag import parse_meta_facebook, parse_meta_instagram


def test_facebook_meta_parser(tmp_path):
    p = tmp_path / "your_posts_1.json"
    p.write_text(json.dumps([{"timestamp": 1700000000, "data": [{"post": "Hello FB"}]}]))
    rows = parse_meta_facebook(p)
    assert rows[0]["text"] == "Hello FB"
    assert rows[0]["platform"] == "facebook"


def test_instagram_meta_parser(tmp_path):
    p = tmp_path / "posts_1.json"
    p.write_text(json.dumps([{"media": [{"title": "Hello IG", "creation_timestamp": 1700000000}]}]))
    rows = parse_meta_instagram(p)
    assert rows[0]["text"] == "Hello IG"
    assert rows[0]["platform"] == "instagram"
