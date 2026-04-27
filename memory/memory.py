"""
Memory Engine — semantic + vector memory with FAISS.

Falls back to keyword matching if FAISS is unavailable.
Persists to disk for cross-session recall.
"""

import json
import os
from pathlib import Path

# --- Config ---
MEM_DIR = Path(__file__).resolve().parent.parent / "memory_store"
MEM_PATH = MEM_DIR / "session.json"

# --- Storage ---
store: list = []

# --- FAISS (optional) ---
_faiss_available = False
index = None
DIM = 1536

try:
    import faiss
    import numpy as np
    index = faiss.IndexFlatL2(DIM)
    _faiss_available = True
except ImportError:
    pass


def _embed(text: str):
    """Generate a deterministic pseudo-embedding.

    Replace with real embeddings (OpenAI, NVIDIA, local) in production.
    """
    if _faiss_available:
        import numpy as np
        rng = np.random.RandomState(abs(hash(text)) % (2**31))
        return rng.rand(DIM).astype("float32")
    return None


def save_memory(task: str, action: dict, result) -> None:
    """Persist a memory entry with optional vector indexing."""
    entry = {
        "task": str(task)[:500],
        "action": action,
        "result": str(result)[:500],
    }
    store.append(entry)

    if _faiss_available and index is not None:
        vec = _embed(task)
        if vec is not None:
            import numpy as np
            index.add(np.array([vec]))

    _persist()


def search_memory(query: str, k: int = 5) -> list:
    """Search memory by semantic similarity or keyword fallback."""
    if not store:
        return []

    if _faiss_available and index is not None and len(store) > 0:
        try:
            import numpy as np
            vec = _embed(query)
            if vec is not None:
                _, I = index.search(np.array([vec]), min(k, len(store)))
                return [store[i] for i in I[0] if 0 <= i < len(store)]
        except Exception:
            pass

    # Fallback: keyword match
    query_lower = query.lower()
    scored = []
    for entry in store:
        text = (entry["task"] + " " + str(entry["action"]) + " " + entry["result"]).lower()
        score = sum(1 for word in query_lower.split() if word in text)
        scored.append((score, entry))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [entry for score, entry in scored[:k] if score > 0] or store[-k:]


def load_all_memory() -> list:
    """Load all memory from disk."""
    global store, index, _faiss_available
    if MEM_PATH.exists():
        try:
            with open(MEM_PATH, "r", encoding="utf-8") as f:
                store = json.load(f)
            # Rebuild vector index
            if _faiss_available:
                import numpy as np
                index = faiss.IndexFlatL2(DIM)
                for entry in store:
                    vec = _embed(entry["task"])
                    if vec is not None:
                        index.add(np.array([vec]))
        except (json.JSONDecodeError, IOError):
            store = []
    return store


def reset_memory():
    """Clear all memory."""
    global store, index
    store = []
    if _faiss_available:
        index = faiss.IndexFlatL2(DIM)
    _persist()


def _persist():
    """Write current store to disk."""
    MEM_DIR.mkdir(parents=True, exist_ok=True)
    with open(MEM_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2)


# Load on import
load_all_memory()