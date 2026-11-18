"""Same runnable CLI demo as python -m agentflow.cli demo."""

import json

from agentflow.cli import offline_demo
from agentflow.service import Service

if __name__ == "__main__":
    service = Service()
    try:
        print(json.dumps(offline_demo(service), indent=2))
    finally:
        service.store.close()
