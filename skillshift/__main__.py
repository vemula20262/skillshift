import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

from .io import read_jsonl, validate_dev, write_json, write_text_new
from .selectors import METHODS, get_selector
from .selectors.base import prepare


def main():
    parser = argparse.ArgumentParser(description="SkillShift selector tools")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("select", "compare", "tune", "embed"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--input", required=True)
        cmd.add_argument("--output", required=True)
        if name in ("select", "compare", "tune"):
            source = cmd.add_mutually_exclusive_group(required=True)
            source.add_argument("--splits", help="Task splits JSON; use task manifest for family validation")
            source.add_argument("--task-manifest", help="Runnable dataset task_manifest.json (preferred)")
        if name in ("select", "compare"):
            calibration = cmd.add_mutually_exclusive_group()
            calibration.add_argument("--threshold", type=float, help="Manual uncalibrated threshold (e.g. demos)")
            calibration.add_argument("--calibration", help="Model-bound development calibration JSON")
        if name == "select":
            cmd.add_argument("--method", choices=METHODS, required=True)
        if name == "tune":
            cmd.add_argument("--pairs", required=True)
            cmd.add_argument("--candidates", type=float, nargs="+", required=True)
        if name == "embed":
            cmd.add_argument("--model", required=True)
            cmd.add_argument("--revision", required=True, help="Pin a model commit for reproducibility")
            cmd.add_argument("--cache", required=True)
    args = parser.parse_args()
    try:
        run(args, parser)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


def run(args, parser):
    protected = [args.input] + [getattr(args, name, None) for name in ("splits", "task_manifest", "pairs", "calibration")]
    if any(Path(p).resolve() == Path(args.output).resolve() for p in protected if p):
        parser.error("Output must not overwrite an input file")
    if Path(args.output).exists():
        parser.error("Output already exists; choose a new path to preserve run evidence")
    rows = prepare(read_jsonl(args.input))
    if not rows:
        parser.error("Input contains no attempt records")
    if hasattr(args, "splits"):
        manifest_path = args.task_manifest or args.splits
        manifest = json.loads(Path(manifest_path).read_text())
        validate_dev(rows, manifest)
    if args.command in ("select", "compare"):
        provenance = calibration_provenance(args, rows, manifest_path)
    if args.command == "select":
        result = get_selector(args.method, args.threshold).select(rows).to_dict()
        result["metadata"].update(provenance)
        result["metadata"]["input_sha256"] = hashlib.sha256(Path(args.input).read_bytes()).hexdigest()
        result["metadata"]["manifest_sha256"] = hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()
        write_json(args.output, result)
    elif args.command == "compare":
        results = [get_selector(method, args.threshold).select(rows) for method in METHODS]
        with io.StringIO(newline="") as file:
            writer = csv.DictWriter(file, lineterminator="\n", fieldnames=["method", "occurrence_id", "record_id", "task_id", "source_family",
                "outcome", "group_id", "weight", "member_ids", "families", "threshold", "input_sha256", "manifest_sha256", "embedding_model", "calibration_status", "calibration_sha256"])
            writer.writeheader()
            provenance = {**provenance, "threshold": args.threshold,
                          "input_sha256": hashlib.sha256(Path(args.input).read_bytes()).hexdigest(),
                          "manifest_sha256": hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()}
            for result in results:
                for item in result.items:
                    writer.writerow({"method": result.method, "record_id": item.record["record_id"],
                        "occurrence_id": item.record["occurrence_id"],
                        "task_id": item.record["task_id"], "source_family": item.record["source_family"],
                        "outcome": item.record["outcome"], "group_id": item.group_id, "weight": item.weight,
                        "member_ids": json.dumps(item.member_ids), "families": json.dumps(item.families), **provenance})
            write_text_new(args.output, file.getvalue())
    elif args.command == "tune":
        from .tuning import tune
        result = tune(rows, read_jsonl(args.pairs), args.candidates, manifest)
        result["input_sha256"] = hashlib.sha256(Path(args.input).read_bytes()).hexdigest()
        result["pairs_sha256"] = hashlib.sha256(Path(args.pairs).read_bytes()).hexdigest()
        result["manifest_sha256"] = hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest()
        write_json(args.output, result)
    else:
        from .embeddings import encode
        result = encode(rows, args.model, args.revision, args.cache)
        write_text_new(args.output, "".join(json.dumps(r, allow_nan=False) + "\n" for r in result))


def calibration_provenance(args, rows, manifest_path):
    models = {r.get("embedding_model") for r in rows}
    provenance = {"embedding_model": next(iter(models)) if len(models) == 1 else None,
                  "calibration_status": "manual_uncalibrated" if args.threshold is not None else "not_applicable",
                  "calibration_sha256": None}
    if args.calibration:
        prepare(rows, embeddings=True)
        raw = Path(args.calibration).read_bytes()
        calibration = json.loads(raw)
        if not isinstance(calibration, dict) or calibration.get("status") != "development_pair_calibrated":
            raise ValueError("Calibration artifact has no informative calibrated threshold")
        if not calibration.get("embedding_model") or models != {calibration["embedding_model"]}:
            raise ValueError("Calibration embedding model does not match input")
        if calibration.get("manifest_sha256") != hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest():
            raise ValueError("Calibration task manifest does not match input manifest")
        if calibration.get("synthetic") and not all(r.get("synthetic") is True for r in rows):
            raise ValueError("Synthetic calibration cannot be used on real attempts")
        threshold = calibration.get("threshold")
        if type(threshold) not in (int, float) or not -1 <= threshold <= 1:
            raise ValueError("Calibration threshold must be finite and within [-1, 1]")
        args.threshold = threshold
        provenance.update(calibration_status=calibration["status"],
                          calibration_sha256=hashlib.sha256(raw).hexdigest())
    return provenance


if __name__ == "__main__":
    main()
