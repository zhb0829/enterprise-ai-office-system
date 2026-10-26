import pytest
from types import SimpleNamespace

from app.config import Settings


def configured(**values):
    return Settings(
        _env_file=None, app_env="test",
        embedding_api_key="test-embedding-key",
        embedding_base_url="https://api.siliconflow.cn/v1",
        **values,
    )


def test_rerank_reuses_same_provider_embedding_key():
    settings = configured(rerank_url="https://api.siliconflow.cn/v1/rerank")
    assert settings.effective_rerank_api_key == "test-embedding-key"
    assert settings.rerank_api_key == ""


def test_explicit_rerank_key_takes_precedence():
    settings = configured(rerank_url="https://other.invalid/rerank", rerank_api_key="explicit")
    assert settings.effective_rerank_api_key == "explicit"


@pytest.mark.parametrize("url", [
    "", "https://other.invalid/rerank", "http://api.siliconflow.cn/v1/rerank",
    "https://api.siliconflow.cn:444/rerank",
    "https://user@api.siliconflow.cn/v1/rerank",
])
def test_shared_key_is_not_sent_to_unrelated_or_insecure_origin(url):
    assert configured(rerank_url=url).effective_rerank_api_key == ""


def test_remote_rerank_sends_shared_key(monkeypatch):
    from app.agent import retrieval
    monkeypatch.setattr(retrieval, "settings", configured(
        rerank_url="https://api.siliconflow.cn/v1/rerank",
    ))
    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"results": [{"index": 0, "relevance_score": 0.9}]}

    def post(url, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(retrieval.httpx, "post", post)
    candidates = [{
        "clause": SimpleNamespace(id="clause-1", content="Financial report required."),
        "document": SimpleNamespace(title="Application"),
        "rrf_score": 0.1,
    }]
    _, diagnostics = retrieval.rerank("Required documents", candidates)
    assert captured["headers"]["Authorization"] == "Bearer test-embedding-key"
    assert diagnostics == {"backend": "cross-encoder-api", "degraded": False}


def test_remote_rerank_does_not_send_shared_key_to_other_provider(monkeypatch):
    from app.agent import retrieval
    monkeypatch.setattr(retrieval, "settings", configured(
        rerank_url="https://other.invalid/rerank",
    ))

    def unexpected_post(*args, **kwargs):
        pytest.fail("Embedding credentials must not be sent to another origin")

    monkeypatch.setattr(retrieval.httpx, "post", unexpected_post)
    candidates = [{
        "clause": SimpleNamespace(id="clause-1", content="Financial report required."),
        "document": SimpleNamespace(title="Application"),
        "rrf_score": 0.1,
    }]
    _, diagnostics = retrieval.rerank("Required documents", candidates)
    assert diagnostics["degraded"] is True
    assert diagnostics["backend"] == "deterministic-lexical"
