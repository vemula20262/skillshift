from collections import Counter
from .base import Record, Selection, Selector, prepare, selected, semantic_groups


class SourceBehavior(Selector):
    def __init__(self, threshold: float):
        self.threshold = threshold

    def select(self, records: list[Record]) -> Selection:
        rows = prepare(records, embeddings=True)
        groups = semantic_groups(rows, self.threshold)
        items = []
        for i, group in enumerate(groups):
            counts = Counter(r["source_family"] for r in group)
            for r in group:
                items.append(selected(r, 1.0 / counts[r["source_family"]], f"behavior:{i}", group))
        return Selection("source_behavior", len(rows), items, {
            "threshold": self.threshold, "clustering": "greedy_complete_link",
            "weight_rule": "1 / records_in_source_family_and_behavior",
        })
