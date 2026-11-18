"""Local TF-IDF retrieval. Documents are evidence, never executable instructions."""

import hashlib
import math
import re
from collections import Counter

from agentflow.domain import Document, Evidence


def tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", text.lower().replace("_", " "))
    aliases = {
        "invoices": "invoice",
        "below": "threshold",
        "exceeds": "threshold",
        "amount": "threshold",
        "finance": "notification",
        "notify": "notification",
        "email": "notification",
        "owner": "notification",
        "endpoint": "security",
        "files": "security",
        "arbitrary": "security",
        "look": "lookup",
        "record": "item",
        "records": "item",
        "sharepoint": "item",
    }
    return [aliases.get(word, word) for word in words]


def retrieve(query: str, documents: list[Document], k: int = 5) -> list[Evidence]:
    counts = [Counter(tokens(doc.title + " " + doc.content)) for doc in documents]
    vocabulary = set().union(*(set(c) for c in counts))
    idf = {
        word: math.log((1 + len(counts)) / (1 + sum(word in c for c in counts))) + 1
        for word in vocabulary
    }

    def vector(count: Counter) -> dict[str, float]:
        return {word: (1 + math.log(n)) * idf.get(word, 1.0) for word, n in count.items()}

    q = vector(Counter(tokens(query)))
    qnorm = math.sqrt(sum(v * v for v in q.values())) or 1
    scored = []
    for doc, count in zip(documents, counts, strict=True):
        v = vector(count)
        norm = math.sqrt(sum(x * x for x in v.values())) or 1
        score = sum(q.get(word, 0) * weight for word, weight in v.items()) / (qnorm * norm)
        scored.append(
            Evidence(
                source_id=doc.id,
                version=doc.version,
                title=doc.title,
                passage=doc.content[:2000],
                score=float(score),
                content_sha256=hashlib.sha256(doc.content.encode()).hexdigest(),
            )
        )
    return sorted(scored, key=lambda item: (-item.score, item.source_id))[:k]
