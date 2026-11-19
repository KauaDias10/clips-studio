"""Titles, descriptions and hashtags come out in the clip's language.

The metadata prompts are written in English; without a language line a model
answered in English even for a Portuguese stream."""

import json

from analysis import metadata
from core.models import ClipCandidate, Segment


class _Recorder:
    """An LLM that remembers the prompt and answers with valid metadata."""

    def __init__(self):
        self.prompts = []

    def generate(self, prompt, **_kw):
        self.prompts.append(prompt)
        if '"items"' in prompt:
            return json.dumps({"items": [{"index": 0, "title": "Título", "description": "Desc",
                                          "hashtags": ["#gta6"]}]})
        return json.dumps({"title": "Título", "description": "Desc", "hashtags": ["#gta6"]})


def _run_batch(language):
    llm = _Recorder()
    clip = ClipCandidate(0.0, 10.0, 80, hook="gancho")
    segs = [Segment(0.0, 10.0, "cara, que foda, é o barco do Michael")]
    out = metadata.generate_metadata_batch([clip], segs, "Live de GTA 6", llm, language=language)
    return llm.prompts[0], out


def test_portuguese_clips_ask_for_portuguese_titles(monkeypatch):
    monkeypatch.setattr(metadata, "generate_json", lambda b, p, s: b.generate(p))
    prompt, out = _run_batch("pt")
    assert "LANGUAGE:" in prompt and "Portuguese" in prompt
    assert prompt.index("LANGUAGE:") < prompt.index("CLIP 0")
    assert out[0].title == "Título"


def test_english_and_auto_leave_the_prompt_unchanged(monkeypatch):
    monkeypatch.setattr(metadata, "generate_json", lambda b, p, s: b.generate(p))
    for lang in ("", "auto", "en", None):
        prompt, _ = _run_batch(lang)
        assert "LANGUAGE:" not in prompt


def test_single_clip_prompt_carries_the_language(monkeypatch):
    monkeypatch.setattr(metadata, "generate_json", lambda b, p, s: b.generate(p))
    llm = _Recorder()
    clip = ClipCandidate(0.0, 10.0, 80, hook="gancho")
    segs = [Segment(0.0, 10.0, "qué locura, el barco de Michael")]
    metadata.generate_metadata(clip, segs, "Directo", llm, language="es")
    assert "Spanish" in llm.prompts[0]
    assert llm.prompts[0].index("LANGUAGE:") < llm.prompts[0].index("CLIP TRANSCRIPT:")


def test_an_unknown_code_is_still_named():
    assert "xx" in metadata.language_rule("xx")
