from .base import Record, Selection, Selector, digest, partition_key, prepare, selected


class ExactDedup(Selector):
    def select(self, records: list[Record]) -> Selection:
        rows, groups = prepare(records), {}
        for r in rows:
            # Exact feedback identity excludes source IDs and embeddings, but
            # keeps outcome and tool evidence. No lossy text normalization.
            key = digest([partition_key(r), r["summary"], r.get("tool_events", [])])
            groups.setdefault(key, []).append(r)
        items = [selected(min(g, key=lambda r: (r.get("is_copy", False), r["occurrence_id"])), 1.0, key, g)
                 for key, g in sorted(groups.items())]
        return Selection("exact_dedup", len(rows), items, {"hash": "sha256"})
