from __future__ import annotations

from typing import Any, Mapping

from aitest_runtime.r3_e1 import KnowledgeRetrievalAdapter, KnowledgeRetrievalResult

from .errors import R35Error
from .workset import KnowledgeRetrievalPort, WorkSetRequest, WorkSetResult, retrieve_workset


class R3E1KnowledgeBridge:
    """Read-only R3.5 bridge to the frozen R3.E1 Knowledge substrate."""

    def __init__(self, retriever: KnowledgeRetrievalPort) -> None:
        if retriever is None or not callable(getattr(retriever, "retrieve", None)):
            raise R35Error("R3_5_KNOWLEDGE_REF_MISSING", "R3.E1 retriever is required")
        self._retriever = retriever

    @classmethod
    def from_runtime(cls, runtime_service: Any) -> "R3E1KnowledgeBridge":
        return cls(KnowledgeRetrievalAdapter(runtime_service))

    @property
    def retriever(self) -> KnowledgeRetrievalPort:
        return self._retriever

    def retrieve_workset(self, request: WorkSetRequest) -> WorkSetResult:
        return retrieve_workset(request, self._retriever)

    def retrieve(self, request: WorkSetRequest) -> WorkSetResult:
        return self.retrieve_workset(request)

    @staticmethod
    def relation_refs(result: WorkSetResult | KnowledgeRetrievalResult) -> tuple[str, ...]:
        source = result.retrieval if isinstance(result, WorkSetResult) else result
        if not isinstance(source, KnowledgeRetrievalResult):
            raise R35Error("R3_5_SCHEMA_INVALID", "relation_refs requires R3.E1 retrieval result")
        return tuple(item.relation_id for item in source.relations)

    @staticmethod
    def source_refs(result: WorkSetResult | KnowledgeRetrievalResult) -> tuple[Mapping[str, Any], ...]:
        source = result.retrieval if isinstance(result, WorkSetResult) else result
        if not isinstance(source, KnowledgeRetrievalResult):
            raise R35Error("R3_5_SCHEMA_INVALID", "source_refs requires R3.E1 retrieval result")
        return tuple(item.to_dict() for item in source.source_refs)

