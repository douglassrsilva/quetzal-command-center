"""Thin REST adapter for Databricks Managed Agent Memory (Beta).

The scope is always derived from the authenticated Databricks Apps proxy
identity. Request bodies and the model can never select another user's scope.
"""

from __future__ import annotations

import os
from typing import Any

from databricks.sdk import WorkspaceClient


class ManagedAgentMemory:
    def __init__(self) -> None:
        self.store_name = os.getenv("QUETZAL_MANAGED_MEMORY_STORE", "").strip()

    @property
    def enabled(self) -> bool:
        return bool(self.store_name)

    @property
    def entries_path(self) -> str:
        return f"/api/2.1/unity-catalog/memory-stores/{self.store_name}/entries"

    @staticmethod
    def _scope(actor: str) -> str:
        if not actor or actor == "quetzal-operator":
            raise RuntimeError("Verified end-user identity is required for managed memory")
        return f"user:{actor.casefold()}"

    @staticmethod
    def _entry(item: Any) -> dict[str, Any]:
        if not isinstance(item, dict):
            return {}
        entry = item.get("memory_entry", item.get("entry", item))
        return entry if isinstance(entry, dict) else {}

    def recall(self, *, actor: str, query: str, top_k: int = 6) -> list[str]:
        if not self.enabled:
            return []
        result = WorkspaceClient().api_client.do(
            "POST",
            f"{self.entries_path}:search",
            body={
                "scope": self._scope(actor),
                "query": query[:1000],
                "path_prefix": "/memories/research/",
                "top_k": top_k,
            },
        ) or {}
        items = result.get("entries", result.get("results", [])) if isinstance(result, dict) else result
        memories: list[str] = []
        seen: set[str] = set()
        for item in items or []:
            entry = self._entry(item)
            contents = entry.get("contents")
            if not isinstance(contents, str):
                continue
            contents = contents.strip()
            # Do not re-inject incomplete tool-call artifacts produced by older
            # model variants. They are not durable knowledge.
            if not contents or "DSML｜tool_calls" in contents:
                continue
            normalized = " ".join(contents.casefold().split())
            if normalized in seen:
                continue
            seen.add(normalized)
            memories.append(contents[:1800])
        return memories

    def remember_research(
        self,
        *,
        actor: str,
        conversation_id: str,
        trace_id: str,
        question: str,
        answer: str,
        tools: list[dict[str, str]],
    ) -> None:
        if not self.enabled or not any(tool.get("tool") == "web_search" for tool in tools):
            return
        safe_conversation = "".join(char for char in conversation_id if char.isalnum() or char in "-_")[:128]
        safe_trace = "".join(char for char in trace_id if char.isalnum() or char in "-_")[:128]
        WorkspaceClient().api_client.do(
            "POST",
            self.entries_path,
            query={"scope": self._scope(actor)},
            body={
                "path": f"/memories/research/{safe_conversation}/{safe_trace}.md",
                "contents": (
                    "Investigación externa de Quetzal IQ.\n\n"
                    f"Pregunta: {question[:1000]}\n\n"
                    f"Síntesis: {answer[:2400]}"
                ),
                # The legacy UC-backed Managed Memory search is BM25-based.
                # Including the question here makes topic terms retrievable
                # immediately instead of indexing only a generic description.
                "description": f"Investigación externa de Quetzal IQ: {question[:500]}",
            },
        )


managed_agent_memory = ManagedAgentMemory()
