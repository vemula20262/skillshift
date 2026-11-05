from .base import Record, Selection, Selector, medoid, prepare, selected, semantic_groups


class SemanticDedup(Selector):
    def __init__(self, threshold: float):
        self.threshold = threshold

    def select(self, records: list[Record]) -> Selection:
        rows = prepare(records, embeddings=True)
        groups = semantic_groups(rows, self.threshold)
        return Selection("semantic_dedup", len(rows), [
            selected(medoid(g), 1.0, f"behavior:{i}", g) for i, g in enumerate(groups)
        ], {"threshold": self.threshold, "clustering": "greedy_complete_link"})
