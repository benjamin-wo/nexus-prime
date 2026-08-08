"""Ordinary IR over manifests: BM25 index, top-k shortlists, recovery path."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from capabilities.registry import Manifest, load_registry

STOPWORDS = {
    "a", "an", "the", "to", "of", "in", "on", "at", "for", "and", "or",
    "is", "are", "was", "were", "my", "me", "i", "it", "this", "that",
    "how", "what", "when", "who", "do", "does", "did", "from", "with",
    "like", "ask", "your", "you", "we", "be", "has", "have", "not",
}


def tokenize(text: str) -> list[str]:
    return [
        w
        for w in re.findall(r"[a-z0-9$']+", text.lower())
        if w not in STOPWORDS and len(w) > 1
    ]


@dataclass(frozen=True)
class RetrievalHit:
    id: str
    score: float
    rank: int
    manifest: Manifest


@dataclass(frozen=True)
class RetrievalResult:
    query: str
    top: tuple[RetrievalHit, ...]
    recovered: bool
    expanded: tuple[RetrievalHit, ...]
    all_scores: tuple[RetrievalHit, ...]
    k: int


class BM25Index:
    def __init__(self, manifests: list[Manifest], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.manifests = {m.id: m for m in manifests}
        self.doc_tokens: dict[str, list[str]] = {}
        self.doc_len: dict[str, int] = {}
        self.doc_freq: Counter = Counter()
        total_len = 0
        for manifest in manifests:
            tokens = tokenize(manifest.retrieval_text)
            self.doc_tokens[manifest.id] = tokens
            self.doc_len[manifest.id] = len(tokens)
            total_len += len(tokens)
            for token in set(tokens):
                self.doc_freq[token] += 1
        self.n = max(1, len(manifests))
        self.avgdl = total_len / self.n
        self.idf: dict[str, float] = {}
        for token, df in self.doc_freq.items():
            self.idf[token] = math.log((self.n - df + 0.5) / (df + 0.5) + 1.0)

    def score(self, query_tokens: list[str], doc_id: str) -> float:
        doc = Counter(self.doc_tokens[doc_id])
        doc_len = self.doc_len[doc_id]
        total = 0.0
        for token in set(query_tokens):
            freq = doc.get(token, 0)
            if freq == 0:
                continue
            denom = freq + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl)
            total += self.idf.get(token, 0.0) * (freq * (self.k1 + 1)) / denom
        return total

    def _hits(self, query_tokens: list[str]) -> list[RetrievalHit]:
        scored = [
            (self.score(query_tokens, mid), mid)
            for mid in self.manifests
        ]
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [
            RetrievalHit(id=mid, score=score, rank=rank + 1, manifest=self.manifests[mid])
            for rank, (score, mid) in enumerate(scored)
        ]

    def retrieve(self, query: str, k: int = 5) -> list[RetrievalHit]:
        tokens = tokenize(query)
        if not tokens:
            return []
        return self._hits(tokens)[:k]

    def retrieve_with_recovery(
        self,
        query: str,
        k: int = 5,
        recovery_k: int = 20,
        min_score: float = 0.8,
        flat_gap: float = 0.15,
    ) -> RetrievalResult:
        tokens = tokenize(query)
        if not tokens:
            return RetrievalResult(
                query=query, top=(), recovered=True, expanded=(), all_scores=(), k=k
            )
        all_scores = tuple(self._hits(tokens))
        top = all_scores[:k]
        recovered = self.needs_recovery(top, min_score=min_score, flat_gap=flat_gap)
        expanded = all_scores[:recovery_k] if recovered else ()
        return RetrievalResult(
            query=query,
            top=top,
            recovered=recovered,
            expanded=expanded,
            all_scores=all_scores,
            k=k,
        )

    @staticmethod
    def needs_recovery(
        top: tuple[RetrievalHit, ...],
        min_score: float = 0.8,
        flat_gap: float = 0.15,
    ) -> bool:
        if not top:
            return True
        scores = [h.score for h in top]
        if max(scores) < min_score:
            return True
        if max(scores) - min(scores) < flat_gap:
            return True
        return False


def build_index(extra_manifests: list[Manifest] | None = None) -> BM25Index:
    registry = load_registry()
    manifests = list(registry.values()) + (extra_manifests or [])
    return BM25Index(manifests)


def shortlist_token_cost(result: RetrievalResult) -> int:
    return sum(len(tokenize(h.manifest.retrieval_text)) for h in result.top)
