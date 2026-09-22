"""Semantic memory and vector similarity retrieval for AUREX.

Implements lightweight local vector similarity matching using TF-IDF and character n-gram
embeddings (pure Python + numpy) to semantically retrieve routines, locations, and preferences
completely offline with zero cloud dependency.
"""

import math
import re
from typing import List, Dict, Any, Optional
import numpy as np
from app.memory.memory_manager import get_memory_manager


class SemanticMemory:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SemanticMemory, cls).__new__(cls)
            cls._instance._memory = get_memory_manager()
        return cls._instance

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """Generate word tokens and character 3-grams for semantic fuzzy matching."""
        clean = text.lower().strip()
        words = re.findall(r"\b\w+\b", clean)
        # Add character trigrams to catch misspellings and partial phrases
        trigrams = []
        for w in words:
            if len(w) >= 3:
                for i in range(len(w) - 2):
                    trigrams.append(w[i:i+3])
        return words + trigrams

    def _compute_vector(self, tokens: List[str], vocab: Dict[str, int]) -> np.ndarray:
        vec = np.zeros(len(vocab), dtype=np.float32)
        for t in tokens:
            if t in vocab:
                vec[vocab[t]] += 1.0
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec

    def search_routines(self, query: str, min_confidence: float = 0.25) -> Optional[Dict[str, Any]]:
        """
        Semantically match a natural language query against saved or proposed routines.
        E.g., "Start my usual development setup" -> matches "Morning Development".
        """
        routines = self._memory.list_routines()
        if not routines:
            return None

        q_tokens = self._tokenize(query)
        if not q_tokens:
            return None

        # Build vocabulary from query and routine names/triggers
        vocab = {}
        for r in routines:
            tokens = self._tokenize(f"{r['name']} {r.get('trigger_desc', '')}")
            for t in tokens:
                if t not in vocab:
                    vocab[t] = len(vocab)
        for t in q_tokens:
            if t not in vocab:
                vocab[t] = len(vocab)

        q_vec = self._compute_vector(q_tokens, vocab)

        best_match = None
        best_score = 0.0

        for r in routines:
            r_tokens = self._tokenize(f"{r['name']} {r.get('trigger_desc', '')}")
            r_vec = self._compute_vector(r_tokens, vocab)
            score = float(np.dot(q_vec, r_vec))
            if score > best_score and score >= min_confidence:
                best_score = score
                best_match = r

        if best_match:
            best_match["match_score"] = round(best_score, 3)
        return best_match

    def search_locations(self, query: str) -> Optional[str]:
        """
        Semantically match a natural phrase to a resolved folder path.
        E.g. "where is my OS project" -> matches "my OS project" -> D:\OS.
        """
        mappings = self._memory.list_location_mappings()
        if not mappings:
            return None

        clean_q = query.lower().strip()
        # Direct substring match
        for m in mappings:
            nat = m["natural_name"].lower()
            if nat in clean_q or clean_q in nat:
                return m["resolved_path"]

        # Fuzzy vector match
        q_tokens = self._tokenize(query)
        vocab = {}
        for m in mappings:
            for t in self._tokenize(m["natural_name"]):
                if t not in vocab:
                    vocab[t] = len(vocab)
        for t in q_tokens:
            if t not in vocab:
                vocab[t] = len(vocab)

        q_vec = self._compute_vector(q_tokens, vocab)
        best_path = None
        best_score = 0.0

        for m in mappings:
            m_tokens = self._tokenize(m["natural_name"])
            m_vec = self._compute_vector(m_tokens, vocab)
            score = float(np.dot(q_vec, m_vec))
            if score > best_score and score > 0.35:
                best_score = score
                best_path = m["resolved_path"]

        return best_path


_global_semantic_memory = SemanticMemory()

def get_semantic_memory() -> SemanticMemory:
    return _global_semantic_memory
