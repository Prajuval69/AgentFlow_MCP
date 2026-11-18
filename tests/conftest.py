import secrets

import pytest
from fastapi.testclient import TestClient

from agentflow.api import create_app
from agentflow.cli import INVOICE_PROMPT
from agentflow.config import Settings
from agentflow.domain import PlanRequest
from agentflow.service import Service


@pytest.fixture
def service(tmp_path):
    instance = Service(
        Settings(db_path=str(tmp_path / "state.sqlite3"), webhook_secret=secrets.token_hex(32))
    )
    yield instance
    instance.store.close()


@pytest.fixture
def invoice(service):
    return service.generate(PlanRequest(prompt=INVOICE_PROMPT))


@pytest.fixture
def client(service):
    with TestClient(create_app(service)) as instance:
        yield instance
