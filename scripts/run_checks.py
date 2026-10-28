"""Run real pytest and save exact captured results, not invented summaries."""
import argparse
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from src.main import ROOT
from src.trace import write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    if args.live and (not os.getenv("OPENAI_API_KEY") or not os.getenv("MODEL_NAME")):
        report = {"status": "BLOCKED", "checked_at": datetime.now(timezone.utc).isoformat(),
                  "reason": "OPENAI_API_KEY 和/或 MODEL_NAME 未配置；没有执行真实模型验证，没有生成 Live Trace。"}
        write_json(ROOT / "examples/live_validation_status.json", report)
        print(report["reason"])
        return 2
    command = [sys.executable, "-m", "pytest", "-q"]
    if args.live:
        command += ["--run-live", "tests/test_live.py"]
    started = datetime.now(timezone.utc).isoformat()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:8]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", env={**os.environ, "PYTHONUTF8": "1",
                            "EVIDENCE_EVALUATION_RUN_ID": run_id})
    target = ROOT / "examples" / ("live_test_results.txt" if args.live else "test_results.txt")
    target.parent.mkdir(parents=True, exist_ok=True)
    record = f"command: {subprocess.list2cmdline(command)}\nstarted_at: {started}\nfinished_at: {datetime.now(timezone.utc).isoformat()}\nexit_code: {result.returncode}\n\n{result.stdout}{result.stderr}"
    archive = ROOT / "examples/test_runs" / run_id
    archive.mkdir(parents=True, exist_ok=False)
    (archive / "results.txt").write_text(record, encoding="utf-8")
    write_json(archive / "run.json", {"run_id": run_id, "mode": "live" if args.live else "offline",
                                     "command": command, "exit_code": result.returncode, "started_at": started})
    if target.exists():
        (archive / "previous_latest_results.txt").write_bytes(target.read_bytes())
    target.write_text(record, encoding="utf-8")
    print(record + f"\nArchived results: {archive}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
