from collections import Counter
from .base import Record, Selection, Selector, prepare, selected


class SourceBalanced(Selector):
    def select(self, records: list[Record]) -> Selection:
        rows = prepare(records)
        counts = Counter(r["source_family"] for r in rows)
        return Selection("source_balanced", len(rows), [
            selected(r, 1.0 / counts[r["source_family"]], r["source_family"], [r]) for r in rows
        ], {"weight_rule": "1 / records_in_source_family"})
