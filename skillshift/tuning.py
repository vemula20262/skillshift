"""Development-only labeled-pair calibration, not test-outcome optimization."""
from .io import validate_dev
from .selectors.base import cosine, partition_key, prepare


def tune(records, pairs, candidates, manifest):
    records = prepare(records, embeddings=True)
    validate_dev(records, manifest)
    if any(any(k in r for k in ("pool_record_id", "original_record_id", "is_copy")) for r in records):
        raise ValueError("Tune on original development attempts before pool construction")
    model = records[0].get("embedding_model") if records else None
    if not model:
        raise ValueError("Calibration requires embedding_model metadata")
    synthetic_flags = set()
    for record in records:
        synthetic = record.get("synthetic", False)
        if type(synthetic) is not bool:
            raise ValueError("Calibration synthetic markers must be boolean")
        synthetic_flags.add(synthetic)
    if len(synthetic_flags) > 1:
        raise ValueError("Cannot mix synthetic and real calibration records")
    lookup = {r["occurrence_id"]: r for r in records}
    if not pairs or not candidates:
        raise ValueError("Need labeled development pairs and candidate thresholds")
    scores, seen, labels = [], set(), set()
    for index, pair in enumerate(pairs, start=1):
        if not isinstance(pair, dict):
            raise ValueError(f"Pair {index}: expected an object")
        if not {"left_id", "right_id", "equivalent"}.issubset(pair):
            raise ValueError(f"Pair {index}: requires left_id, right_id and equivalent")
        a, b, label = pair["left_id"], pair["right_id"], pair["equivalent"]
        if any(not isinstance(value, str) or not value.strip() for value in (a, b)):
            raise ValueError(f"Pair {index}: IDs must be nonempty strings")
        if type(label) is not bool or a == b or a not in lookup or b not in lookup:
            raise ValueError(f"Pair {index}: requires distinct known IDs and a boolean equivalent label")
        key = tuple(sorted((a, b)))
        if key in seen:
            raise ValueError("Duplicate labeled pair")
        seen.add(key)
        labels.add(label)
        left, right = lookup[a], lookup[b]
        compatible = partition_key(left) == partition_key(right)
        if label and not compatible:
            raise ValueError("Positive label conflicts with outcome/category/source/environment partition")
        scores.append((cosine(left["embedding"], right["embedding"]), compatible, label))
    if labels != {True, False}:
        raise ValueError("Calibration requires both equivalent and non-equivalent pairs")
    grid = []
    for threshold in sorted(set(candidates)):
        if not -1 <= threshold <= 1:
            raise ValueError("Candidate threshold outside [-1, 1]")
        predictions = [(compatible and score >= threshold, label) for score, compatible, label in scores]
        tp = sum(p and y for p, y in predictions)
        fp = sum(p and not y for p, y in predictions)
        fn = sum(not p and y for p, y in predictions)
        precision = tp / (tp + fp) if tp + fp else 0
        recall = tp / (tp + fn) if tp + fn else 0
        f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0
        grid.append(dict(threshold=threshold, tp=tp, fp=fp, fn=fn, precision=precision, recall=recall, f1=f1))
    best = max(grid, key=lambda x: (x["f1"], x["precision"], x["threshold"]))
    return {"status": "development_pair_calibrated" if best["f1"] > 0 else "no_informative_threshold",
            "threshold": best["threshold"] if best["f1"] > 0 else None,
            "embedding_model": model,
            "synthetic": synthetic_flags == {True},
            "objective": "max pair F1; ties: higher precision, then higher threshold",
            "pair_count": len(pairs), "task_ids": sorted({r["task_id"] for r in records}),
            "grid": grid, "note": "In-sample calibration metrics; not held-out task success."}
