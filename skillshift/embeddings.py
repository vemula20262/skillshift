"""Optional Sentence Transformers adapter; no network calls during core tests."""
from .selectors.base import prepare


def encode(records, model_name, revision, cache_folder):
    rows = prepare(records)
    if any("pool_record_id" in r for r in rows):
        raise ValueError("Embed original attempts before pool construction")
    if not rows:
        return rows
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(model_name, revision=revision, cache_folder=cache_folder,
                                trust_remote_code=False)
    vectors = model.encode([r["summary"] for r in rows], normalize_embeddings=True,
                           convert_to_numpy=True, show_progress_bar=False)
    if len(vectors) != len(rows):
        raise ValueError("Embedding model must return exactly one vector per input record")
    for r, vector in zip(rows, vectors):
        r["embedding"] = vector.tolist()
        r["embedding_model"] = f"{model_name}@{revision}"
    return prepare(rows, embeddings=True)
