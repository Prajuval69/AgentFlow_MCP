import httpx
import pytest

from agentflow.config import Settings
from agentflow.domain import AgentFlowError
from agentflow.planner import OllamaProvider


class ClientDouble:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response

    def get(self, url):
        return next(self.responses)


def response(payload):
    return httpx.Response(200, json=payload, request=httpx.Request("POST", "http://localhost"))


def test_ollama_schema_failure_retry_cap(monkeypatch, service):
    client = ClientDouble([response({"message": {"content": '{"steps":[]}'}})] * 2)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client)
    with pytest.raises(AgentFlowError) as exc:
        OllamaProvider(Settings()).generate("anything", [], service.catalog.model_dump())
    assert exc.value.code == "PROVIDER_FAILURE"
    assert len(client.calls) == 2


def test_ollama_transient_then_valid(monkeypatch, service, invoice):
    client = ClientDouble(
        [
            httpx.ConnectError("offline"),
            response({"message": {"content": invoice.model_dump_json()}}),
        ]
    )
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client)
    plan = OllamaProvider(Settings()).generate(
        "anything", invoice.evidence, service.catalog.model_dump()
    )
    assert plan.provider == "ollama"
    assert plan.id != invoice.id
    assert service.validate(plan).valid
    assert len(client.calls) == 2


def test_ollama_health_model_missing(monkeypatch):
    client = ClientDouble([response({"models": [{"name": "other-model"}]})])
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client)
    assert not OllamaProvider(Settings()).health()
