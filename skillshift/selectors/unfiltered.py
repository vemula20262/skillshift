from .base import Record, Selection, Selector, prepare, selected


class Unfiltered(Selector):
    def select(self, records: list[Record]) -> Selection:
        rows = prepare(records)
        return Selection("unfiltered", len(rows), [
            selected(r, 1.0, r["occurrence_id"], [r]) for r in rows
        ], {})
