def validate_dev(records, manifest):
    """Accept repo task_manifest.json (preferred) or wrapped/raw task splits.

    Full manifests also enforce family and precautionary block isolation.
    Only metadata is used; no reference workbooks or test outcomes are read.
    """
    expected_families = None
    if isinstance(manifest, list):
        expected_families, family_splits, block_splits = {}, {}, {}
        splits = {"dev": [], "val": [], "test": []}
        for row in manifest:
            task, family, split = row.get("id"), row.get("family_id"), row.get("split")
            if not isinstance(task, str) or not task or not isinstance(family, str) or not family or split not in splits:
                raise ValueError("Task manifest requires nonempty id/family_id and dev/val/test split")
            if task in expected_families:
                raise ValueError("Duplicate task in manifest")
            if row.get("eligible_for_execution") is False:
                raise ValueError("Use runnable task manifest; ineligible source task encountered")
            if family_splits.setdefault(family, split) != split:
                raise ValueError("Source family crosses splits")
            block = row.get("split_group_id", family)
            if not isinstance(block, str) or not block:
                raise ValueError("split_group_id must be a nonempty string")
            if block_splits.setdefault(block, split) != split:
                raise ValueError("Precautionary block crosses splits")
            expected_families[task] = family
            splits[split].append(task)
        if not all(splits.values()):
            raise ValueError("Full task manifest must include nonempty dev, val and test splits")
        manifest = splits
    if not isinstance(manifest, dict):
        raise ValueError("Expected task manifest array or splits object")
    manifest = manifest.get("splits", manifest)
    if set(manifest) == {"dev", "validation", "test"}:
        manifest = {"dev": manifest["dev"], "val": manifest["validation"], "test": manifest["test"]}
    required = {"dev", "val", "test"}
    if set(manifest) != required:
        raise ValueError("split manifest must contain exactly dev, val, test")
    if any(not isinstance(v, list) or any(not isinstance(x, str) or not x for x in v)
           or len(v) != len(set(v)) for v in manifest.values()):
        raise ValueError("split entries must be lists of unique string task IDs")
    sets = {k: set(v) for k, v in manifest.items()}
    if any(sets[a] & sets[b] for a, b in (("dev", "val"), ("dev", "test"), ("val", "test"))):
        raise ValueError("task IDs cross split boundaries")
    for r in records:
        if r["task_id"] not in sets["dev"] or r.get("split") != "dev":
            raise ValueError(f"Non-development record: {r['record_id']}")
        if expected_families is not None and expected_families[r["task_id"]] != r["source_family"]:
            raise ValueError("Record source_family differs from task manifest")
