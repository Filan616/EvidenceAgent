"""Execute all explicit Mock fixtures through the actual CLI and save evidence."""
import json

from src.main import ROOT, main
from src.trace import write_json


def generate():
    cases = json.loads((ROOT / "examples/cases.json").read_text(encoding="utf-8"))
    records = []
    for case in cases:
        directory = ROOT / "examples/generated/mock"
        name = case["script"]
        trace_path, output_path = directory / f"{name}_trace.json", directory / f"{name}_output.json"
        argv = ["--mock", "--mock-script", str(ROOT / f"examples/mock_scripts/{name}.json"),
                "--question", case["question"], "--as-of", case["as_of"],
                "--trace-file", str(trace_path), "--output-file", str(output_path)]
        if case["history_file"]:
            argv += ["--history-file", str(ROOT / case["history_file"])]
        if case["fault"]:
            argv += ["--fault", case["fault"]]
        exit_code = main(argv)
        result = json.loads(output_path.read_text(encoding="utf-8"))
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
        records.append({"case_id": case["id"], "mode": "mock", "exit_code": exit_code,
                        "status": result["status"], "expected_status": case["expected_status"],
                        "passed": result["status"] == case["expected_status"],
                        "trace": str(trace_path.relative_to(ROOT)), "output": str(output_path.relative_to(ROOT)),
                        "actions": [step["action"] for step in trace["steps"]]})
    write_json(ROOT / "examples/generated/mock/manifest.json", records)
    return 0 if all(record["passed"] for record in records) else 1


if __name__ == "__main__":
    raise SystemExit(generate())
