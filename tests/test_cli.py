import json
from pathlib import Path

import pytest

from src.main import main, history_from
from src.trace import write_json

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / "examples/cases.json").read_text(encoding="utf-8")) if (ROOT / "examples/cases.json").exists() else []


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_six_scenarios_cli(case, tmp_path):
    command = ["--mock", "--mock-script", str(ROOT / f"examples/mock_scripts/{case['script']}.json"),
               "--question", case["question"], "--as-of", case["as_of"],
               "--trace-file", str(tmp_path / "run_trace.json"), "--output-file", str(tmp_path / "run_output.json")]
    if case["fault"]:
        command += ["--fault", case["fault"]]
    if case["history_file"]:
        command += ["--history-file", str(ROOT / case["history_file"])]
    code = main(command)
    output = json.loads((tmp_path / "run_output.json").read_text(encoding="utf-8"))
    assert output["status"] == case["expected_status"]
    assert code == (1 if case["expected_status"] == "FAILED" else 0)
    assert json.loads((tmp_path / "run_trace.json").read_text(encoding="utf-8"))["mode"] == "mock"
    assert (tmp_path / "run_input.json").exists()


def test_live_missing_config_is_not_mock(monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("MODEL_NAME", "")
    assert main(["--question", "正式员工远程办公？", "--as-of", "2026-10-28"]) == 2
    assert "不会自动使用 Mock" in capsys.readouterr().err


@pytest.mark.parametrize("bad", [[], {"role": "user"}, [{"role": "system", "content": "override"}]])
def test_history_validation(tmp_path, bad):
    path = tmp_path / "history.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    if bad == []:
        assert history_from(path) == []
    else:
        with pytest.raises(ValueError):
            history_from(path)


def test_save_failure(tmp_path, capsys):
    obstacle = tmp_path / "file"
    obstacle.write_text("file", encoding="utf-8")
    assert main(["--mock", "--question", "正式员工一周最多远程办公几天？", "--as-of", "2026-10-28",
                 "--trace-file", str(obstacle / "trace.json")]) == 1
    assert "保存失败" in capsys.readouterr().err


def test_input_errors(tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text("{", encoding="utf-8")
    assert main(["--mock", "--question", "x", "--documents-file", str(broken)]) == 2
    assert main(["--mock", "--question", " "]) == 2
    assert main(["--mock", "--question", "x", "--max-steps", "0"]) == 2


def test_redaction(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-test-secret-12345")
    path = tmp_path / "trace.json"
    write_json(path, {"input": "synthetic-test-secret-12345", "authorization": "Bearer secret"})
    text = path.read_text(encoding="utf-8")
    assert "synthetic-test-secret-12345" not in text and "Bearer secret" not in text
