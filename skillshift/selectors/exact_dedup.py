from .base import Record, Selection, Selector, digest, partition_key, prepare, selected


class ExactDedup(Selector):
    def select(self, records: list[Record]) -> Selection:
        rows, groups = prepare(records), {}
        for r in rows:
            trajectory = r.get("trajectory_sha256")
            if (not isinstance(trajectory, str) or len(trajectory) != 64
                    or any(c not in "0123456789abcdef" for c in trajectory)):
                raise ValueError("Exact dedup requires a lowercase SHA-256 trajectory_sha256")
            # Preserve evaluation partitions even when trajectory bytes match.
            key = digest([partition_key(r), trajectory])
            groups.setdefault(key, []).append(r)
        items = [selected(min(g, key=lambda r: (r.get("is_copy", False), r["occurrence_id"])), 1.0, key, g)
                 for key, g in sorted(groups.items())]
        return Selection("exact_dedup", len(rows), items, {"hash": "sha256"})
