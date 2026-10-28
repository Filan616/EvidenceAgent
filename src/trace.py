"""Actual execution records only; secrets are scrubbed before serialization."""
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def scrub(value):
    secrets = [v for k, v in os.environ.items() if any(s in k.upper() for s in ("API_KEY", "TOKEN", "SECRET")) and len(v) >= 8]
    def clean(text):
        for secret in secrets:
            text = text.replace(secret, "[REDACTED]")
        return re.sub(r"\bsk-[A-Za-z0-9_-]{8,}", "[REDACTED]", text)
    if isinstance(value, str):
        return clean(value)
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, dict):
        return {k: ("[REDACTED]" if any(s in k.lower() for s in ("api_key", "authorization", "password")) else scrub(v)) for k, v in value.items()}
    return value


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Replace only after serialization succeeds; no false 'saved' report.
    payload = json.dumps(scrub(data), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(payload, encoding="utf-8")
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


class Trace:
    def __init__(self, client, question, history, corpus, prompt, schemas, config):
        self.started = perf_counter()
        versions = {"python": platform.python_version()}
        for name in ("openai", "python-dotenv", "jsonschema", "pytest"):
            try:
                versions[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                versions[name] = "not-installed"
        self.data = {"run_id": uuid.uuid4().hex, "mode": client.mode, "model": client.model,
                     "requested_model": client.model, "started_at": datetime.now(timezone.utc).isoformat(),
                     "input": {"question": question, "history": history}, "config": config,
                     "corpus_hash": corpus.hash, "prompt_hash": digest(prompt), "schema_hash": digest(schemas),
                     "versions": versions, "steps": [], "rounds": [], "question_revisions": [],
                     "counts": {"model_calls": 0, "requested": 0, "attempted": 0, "executed": 0, "skipped": 0}}

    def finish(self, result, client, coverage):
        self.data.update({"final": result, "elapsed_seconds": round(perf_counter() - self.started, 6),
                          "finished_at": datetime.now(timezone.utc).isoformat(),
                          "capabilities": dict(client.capabilities),
                          "question_revisions": coverage.revisions})
        self.data.update({"contract_attempts": coverage.attempts, "protected_constraints": coverage.hard_constraints})
