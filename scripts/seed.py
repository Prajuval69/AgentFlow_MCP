"""Reproducible non-destructive local seed."""

from agentflow.service import Service

if __name__ == "__main__":
    service = Service()
    service.store.seed()
    print({"mode": "simulated", "items": len(service.store.bodies("items"))})
    service.store.close()
