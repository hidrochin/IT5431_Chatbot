"""
FAQ action — RAG (Retrieval-Augmented Generation) edition
=========================================================

Pipeline
--------
User query
  → embed (litellm / text-embedding-3-small)
  → FAISS cosine-similarity search across ALL CSV rows
  → top-k retrieved docs
  → LLM generates answer from retrieved context only

Index lifecycle
---------------
- Built lazily on first call (class-level singleton).
- Serialised to db/_faq_index.pkl (FAISS bytes + doc list + SHA-1 of CSVs).
- Cache invalidated automatically when any CSV file changes.
- No manual rebuild needed after data edits — restart action server.
"""

from typing import Any, Text, Dict, List
from rasa_sdk import Action, Tracker
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import SlotSet
import os
import csv
import hashlib
import pickle
import logging

import litellm
import numpy as np
import faiss

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
DB_DIR     = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "db"))
CACHE_PATH = os.path.join(DB_DIR, "_faq_index.pkl")
CATEGORIES = ["rooms", "policies", "amenities", "location", "general"]
TOP_K      = 6          # number of rows to retrieve per query
MIN_SCORE  = 0.30       # minimum cosine similarity threshold (0–1)
# ─────────────────────────────────────────────────────────────────────────────


class ActionFaqLookup(Action):
    """RAG-based FAQ: embed → FAISS retrieve → LLM generate."""

    SYSTEM_PROMPT = (
        "You are the AI Concierge for a luxury 5-star hotel in Hanoi, Vietnam. "
        "Answer the guest's question using ONLY the hotel data provided below. "
        "Be professional, warm, and concise — no more than 3-4 sentences. "
        "If the specific answer is not in the data, politely say so and suggest "
        "contacting the front desk."
    )

    # ── Class-level singleton (shared across all action invocations) ───────────
    _index: "faiss.IndexFlatIP | None" = None
    _docs:  List[str]                  = []
    _embed_model: str                  = ""
    # ──────────────────────────────────────────────────────────────────────────

    def name(self) -> Text:
        return "action_faq_lookup"

    # ── Main entry point ──────────────────────────────────────────────────────

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker:    Tracker,
        domain:     Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:

        query = (
            tracker.get_slot("faq_query")
            or tracker.latest_message.get("text", "")
        )

        self._ensure_index()
        context = self._retrieve(query)

        if context:
            user_prompt = (
                f"Hotel data (retrieved):\n{context}\n\n"
                f"Guest question: {query}"
            )
        else:
            # Fallback: refer to front desk using general contact info
            contact = self._load_raw_csv("general")
            user_prompt = (
                f"You have no specific hotel data for this question.\n"
                f"Hotel contact info:\n{contact}\n\n"
                f"Guest question: {query}\n\n"
                "Politely say you don't have that specific detail and refer "
                "the guest to the front desk using the contact info above."
            )

        dispatcher.utter_message(text=self._call_llm(user_prompt))
        return []

    # ── Index management ──────────────────────────────────────────────────────

    def _ensure_index(self) -> None:
        """Build or restore the FAISS index if not already in memory."""
        if ActionFaqLookup._index is not None:
            return

        embed_model = os.getenv("FAQ_EMBED_MODEL", "text-embedding-3-small")
        docs = self._load_all_docs()

        if not docs:
            log.warning("FAQ RAG: no CSV documents found in %s", DB_DIR)
            return

        csv_hash = self._csv_hash()

        # Fast path: valid on-disk cache
        cached = self._load_cache(csv_hash, embed_model)
        if cached:
            ActionFaqLookup._index, ActionFaqLookup._docs, ActionFaqLookup._embed_model = cached
            log.info("FAQ RAG: index loaded from cache (%d docs)", len(ActionFaqLookup._docs))
            return

        # Slow path: embed all docs and build FAISS index
        log.info("FAQ RAG: building FAISS index for %d documents...", len(docs))
        try:
            vectors = self._embed(docs, embed_model)        # (N, dim)  float32
        except Exception as e:
            log.error("FAQ RAG: embedding failed — %s", e)
            return

        faiss.normalize_L2(vectors)                         # cosine via inner product
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)

        ActionFaqLookup._index       = index
        ActionFaqLookup._docs        = docs
        ActionFaqLookup._embed_model = embed_model

        self._save_cache(csv_hash, embed_model, index, docs)
        log.info(
            "FAQ RAG: index ready — %d docs, dim=%d",
            len(docs), vectors.shape[1],
        )

    # ── Retrieval ─────────────────────────────────────────────────────────────

    def _retrieve(self, query: str) -> str:
        """
        Embed the query, search FAISS, return top-k docs above MIN_SCORE
        as a newline-joined string ready for the LLM prompt.
        """
        index = ActionFaqLookup._index
        docs  = ActionFaqLookup._docs
        model = ActionFaqLookup._embed_model

        if index is None or index.ntotal == 0:
            return ""

        try:
            q_vec = self._embed([query], model)             # (1, dim)  float32
        except Exception as e:
            log.error("FAQ RAG: query embedding failed — %s", e)
            return ""

        faiss.normalize_L2(q_vec)
        k = min(TOP_K, index.ntotal)
        scores, indices = index.search(q_vec, k)            # (1, k)

        results = [
            docs[idx]
            for score, idx in zip(scores[0], indices[0])
            if idx >= 0 and float(score) >= MIN_SCORE
        ]

        log.info(
            "FAQ RAG: query=%r → %d/%d docs above threshold %.2f",
            query[:60], len(results), k, MIN_SCORE,
        )
        return "\n".join(results)

    # ── Document loading ──────────────────────────────────────────────────────

    def _load_all_docs(self) -> List[str]:
        """
        Read every category CSV and return one descriptive string per row.
        Each string is prefixed with its category so the LLM has source context.

        Example output row:
            [amenities] facility: Swimming Pool | hours: 06:00–22:00 | location: Rooftop
        """
        docs: List[str] = []
        for category in CATEGORIES:
            path = os.path.join(DB_DIR, f"{category}.csv")
            if not os.path.exists(path):
                continue
            with open(path, encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    parts = [
                        f"{k}: {v}"
                        for k, v in row.items()
                        if k and isinstance(v, str) and v.strip()
                    ]
                    if parts:
                        docs.append(f"[{category}] " + " | ".join(parts))
        return docs

    def _load_raw_csv(self, category: str) -> str:
        """Return an entire CSV as plain text (used only for fallback contact info)."""
        path = os.path.join(DB_DIR, f"{category}.csv")
        if not os.path.exists(path):
            return ""
        lines: List[str] = []
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                parts = [
                    f"{k}: {v}"
                    for k, v in row.items()
                    if k and isinstance(v, str) and v.strip()
                ]
                if parts:
                    lines.append(" | ".join(parts))
        return "\n".join(lines)

    # ── Embedding ─────────────────────────────────────────────────────────────

    def _embed(self, texts: List[str], model: str) -> np.ndarray:
        """Call litellm.embedding() and return a float32 numpy array."""
        response = litellm.embedding(
            model=model,
            input=texts,
            api_key=os.getenv("OPENAI_API_KEY"),
        )
        vectors = [item["embedding"] for item in response.data]
        return np.array(vectors, dtype=np.float32)

    # ── Disk cache ────────────────────────────────────────────────────────────

    def _csv_hash(self) -> str:
        """SHA-1 of all CSV file bytes — changes whenever any data file is edited."""
        h = hashlib.sha1()
        for category in CATEGORIES:
            path = os.path.join(DB_DIR, f"{category}.csv")
            if os.path.exists(path):
                with open(path, "rb") as f:
                    h.update(f.read())
        return h.hexdigest()

    def _load_cache(self, csv_hash: str, embed_model: str):
        """
        Return (index, docs, model) if the pickle cache is valid.
        Returns None on any mismatch or error.
        """
        if not os.path.exists(CACHE_PATH):
            return None
        try:
            with open(CACHE_PATH, "rb") as f:
                payload = pickle.load(f)
            if (
                payload.get("hash")  == csv_hash
                and payload.get("model") == embed_model
            ):
                index = faiss.deserialize_index(payload["index_bytes"])
                return index, payload["docs"], embed_model
        except Exception as exc:
            log.warning("FAQ RAG: cache invalid (%s) — rebuilding.", exc)
        return None

    def _save_cache(
        self,
        csv_hash:    str,
        embed_model: str,
        index:       "faiss.IndexFlatIP",
        docs:        List[str],
    ) -> None:
        try:
            payload = {
                "hash":        csv_hash,
                "model":       embed_model,
                "index_bytes": faiss.serialize_index(index),
                "docs":        docs,
            }
            with open(CACHE_PATH, "wb") as f:
                pickle.dump(payload, f)
            log.info("FAQ RAG: index cached to %s", CACHE_PATH)
        except Exception as exc:
            log.warning("FAQ RAG: cache save failed (%s).", exc)

    # ── LLM call ──────────────────────────────────────────────────────────────

    def _call_llm(self, user_prompt: str) -> str:
        try:
            response = litellm.completion(
                model=os.getenv("FAQ_LLM_MODEL", "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ],
                api_key=os.getenv("OPENAI_API_KEY"),
                max_tokens=300,
                temperature=0.3,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            log.error("FAQ RAG: LLM call failed — %s", exc)
            return (
                "I apologize, I'm unable to retrieve that information at the moment. "
                "Please contact our front desk — they will be happy to assist you."
            )


class ActionResetFaqSlots(Action):
    """Clear faq_query after each FAQ turn so the slot is fresh for next time."""

    def name(self) -> Text:
        return "action_reset_faq_slots"

    def run(
        self,
        dispatcher: CollectingDispatcher,
        tracker:    Tracker,
        domain:     Dict[Text, Any],
    ) -> List[Dict[Text, Any]]:
        return [SlotSet("faq_query", None)]
