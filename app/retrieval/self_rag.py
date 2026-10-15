"""Self-RAG style retrieve → grade → optionally hop again.

Reflection is implemented as structured LLM JSON, not special tokens,
so it stays schema-validated and testable.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.config.settings import Settings
from app.core.exceptions import LLMOutputError, LLMProviderError
from app.prompts.self_rag import GRADE_SYSTEM, GRADE_USER
from app.providers.base import LLMProvider
from app.providers.json_parser import parse_model
from app.retrieval.hybrid import HybridRetriever
from app.retrieval.query_rewrite import QueryRewriter
from app.retrieval.reranker import DocumentReranker
from app.schemas.retrieval import RetrievedChunk


class GradeResult(BaseModel):
    relevant: bool
    sufficient: bool
    missing_aspect: str = ""
    rationale: str = ""


class SelfRAGLoop:
    def __init__(
        self,
        retriever: HybridRetriever,
        reranker: DocumentReranker,
        rewriter: QueryRewriter,
        llm: LLMProvider,
        settings: Settings,
    ) -> None:
        self._retriever = retriever
        self._reranker = reranker
        self._rewriter = rewriter
        self._llm = llm
        self._settings = settings

    async def retrieve(
        self,
        query: str,
        *,
        top_k: int,
    ) -> list[RetrievedChunk]:
        accumulated: dict[str, RetrievedChunk] = {}
        current_query = query
        missing = ""
        for _hop in range(self._settings.max_retrieval_hops):
            rewritten = await self._rewriter.rewrite(current_query, missing_aspect=missing)
            queries = list(dict.fromkeys([query, *rewritten]))[:2]
            candidates_by_id: dict[str, RetrievedChunk] = {}
            for search_query in queries:
                for candidate in await self._retriever.retrieve(search_query, top_k=top_k):
                    candidates_by_id.setdefault(candidate.chunk_id, candidate)
            reranked = await self._reranker.rerank(
                query, list(candidates_by_id.values()), top_n=self._settings.rerank_top_n
            )
            for chunk in reranked:
                accumulated[chunk.chunk_id] = chunk
            grade = await self._grade(query, list(accumulated.values()))
            if grade.sufficient:
                break
            missing = grade.missing_aspect or "more specific policy conditions"
            current_query = query
        return list(accumulated.values())[: self._settings.rerank_top_n * 2]

    async def _grade(self, query: str, chunks: list[RetrievedChunk]) -> GradeResult:
        evidence = "\n\n".join(f"[{c.chunk_id}] {c.content}" for c in chunks[:6]) or "(empty)"
        try:
            response = await self._llm.generate(
                [
                    {"role": "system", "content": GRADE_SYSTEM},
                    {"role": "user", "content": GRADE_USER.format(query=query, evidence=evidence)},
                ],
                temperature=0.0,
                max_tokens=256,
                response_format={"type": "json_object"},
            )
            return parse_model(response.content, GradeResult)
        except (LLMProviderError, LLMOutputError):
            return GradeResult(relevant=bool(chunks), sufficient=bool(chunks), rationale="fallback")
