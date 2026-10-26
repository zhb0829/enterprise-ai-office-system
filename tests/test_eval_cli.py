from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_offline_eval_cli_registers_platform_models(tmp_path):
    output = tmp_path / "offline.json"
    result = subprocess.run(
        [sys.executable, "-m", "evals.run", "--mode", "offline", "--output", str(output)],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["mode"] == "offline"
    assert report["synthetic"] is True
    assert report["summary"]["total"] > 0
    assert report["summary"]["passed"] == report["summary"]["total"]
