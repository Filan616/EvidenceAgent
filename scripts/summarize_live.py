"""Summarize every trace in one completed batch without rerunning or selecting results."""
import argparse
import hashlib
import json
from pathlib import Path

from src.main import ROOT
from src.trace import write_json


def summarize(batch):
    archive = ROOT / "examples/test_runs" / batch
    run = json.loads((archive / "run.json").read_text(encoding="utf-8"))
    if run["mode"] != "live":
        raise ValueError("需要已完成的Live批次")
    records = []
    for path in sorted((ROOT / "examples/generated/live").glob("*/trace.json")):
        trace = json.loads(path.read_text(encoding="utf-8"))
        if trace["config"].get("evaluation_batch") != batch:
            continue
        records.append({"case": trace["config"]["evaluation"], "trace": str(path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "mode": trace["mode"],
            "model": trace["model"], "provider_host": trace["config"]["provider_host"],
            "final_status": trace["final"]["status"], "counts": trace["counts"],
            "actions": [{"step": s["step"], "round": s["round"], "call_id": s["call_id"], "action": s["action"],
                         "executed": s["executed"], "ok": s["ok"],
                         "business_parameters": {k: v for k, v in s["parameters"].items() if k in {"query", "doc_id", "status", "top_k"}},
                         "error_type": s["observation"].get("error_type"),
                         "validation_details": s["observation"].get("details", [])} for s in trace["steps"]]})
    if not records:
        raise ValueError("批次没有Trace")
    baseline = json.loads((ROOT / "examples/repair_baseline/manifest.json").read_text(encoding="utf-8"))
    unchanged = all(hashlib.sha256((ROOT / r["path"]).read_bytes()).hexdigest() == r["sha256"] for r in baseline["files"])
    summary = {"batch": batch, "pytest_exit_code": run["exit_code"], "trace_count": len(records),
               "baseline_files": len(baseline["files"]), "baseline_unchanged": unchanged,
               "model_calls": sum(r["counts"]["model_calls"] for r in records),
               "tool_attempts": sum(r["counts"]["attempted"] for r in records),
               "executed_tools": sum(r["counts"]["executed"] for r in records), "records": records}
    target = archive / "live_summary.json"
    if target.exists():
        raise ValueError("该批次摘要已存在；不覆盖既有评估产物")
    write_json(target, summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "records"}, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", required=True)
    summarize(parser.parse_args().batch)
