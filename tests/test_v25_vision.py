from pathlib import Path

import fitz

from author_agent.persistence import AutomationStore
from author_agent.vision import MultimodalBookAnalyzer


class FakeVision:
    def __init__(self): self.calls = 0
    def analyze(self, image_bytes, *, page, text):
        self.calls += 1
        assert image_bytes.startswith(b"\x89PNG")
        return [{"claim": "A red balloon is visible", "confidence": 0.9, "source": "vision"}]


def make_pdf(path: Path):
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72,72), "Yok finds a balloon.")
    doc.save(path)
    doc.close()


def test_multimodal_analysis_and_cache(tmp_path):
    pdf = tmp_path / "book.pdf"
    make_pdf(pdf)
    provider = FakeVision()
    analyzer = MultimodalBookAnalyzer(AutomationStore(tmp_path / "a.sqlite3"), provider)
    first = analyzer.analyze_pdf(pdf, enabled=True)
    second = analyzer.analyze_pdf(pdf, enabled=True)
    assert first[0].visual_evidence[0]["source"] == "vision"
    assert second[0].visual_evidence == first[0].visual_evidence
    assert provider.calls == 1


def test_text_only_fallback(tmp_path):
    pdf = tmp_path / "book.pdf"
    make_pdf(pdf)
    evidence = MultimodalBookAnalyzer(AutomationStore(tmp_path / "a.sqlite3"), None).analyze_pdf(pdf, enabled=True)
    assert "Yok finds a balloon" in evidence[0].text_evidence[0]
    assert evidence[0].visual_evidence == []

def test_ollama_vision_provider_parses_grounded_observations(monkeypatch):
    from author_agent.vision import OllamaVisionProvider
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"response": '{"observations":[{"claim":"A red balloon is visible","confidence":0.9}]}' }
    monkeypatch.setattr("requests.post", lambda *a, **k: Response())
    out = OllamaVisionProvider("http://localhost:11434", "vision-model").analyze(b"png", page=1, text="")
    assert out == [{"claim": "A red balloon is visible", "confidence": 0.9, "source": "vision"}]
