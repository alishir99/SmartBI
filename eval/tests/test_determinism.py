"""The generator is reproducible — the assumption the whole oracle rests on."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "scripts" / "generate_data.py"

SEED = 7
LINES = 4000


def generate(out: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--seed", str(SEED), "--lines", str(LINES),
         "--out", str(out)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert result.returncode == 0, result.stderr or result.stdout


def digests(directory: Path) -> dict[str, str]:
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.iterdir()) if path.is_file()}


@pytest.fixture(scope="module")
def two_runs(tmp_path_factory) -> tuple[dict[str, str], dict[str, str]]:
    if not GENERATOR.exists():
        pytest.skip("scripts/generate_data.py saknas")
    outputs = []
    for name in ("first", "second"):
        out = tmp_path_factory.mktemp(name)
        generate(out)
        outputs.append(digests(out))
    return outputs[0], outputs[1]


def test_the_same_seed_produces_byte_identical_output(two_runs):
    first, second = two_runs

    assert first, "generatorn skrev inga filer"
    assert set(first) == set(second)

    differing = [name for name in first if first[name] != second[name]]
    assert not differing, f"inte reproducerbart: {differing}"


def test_both_the_facts_and_the_facit_are_covered(two_runs):
    """A determinism check that happened to skip fact_sales_line would prove nothing."""
    first, _ = two_runs

    assert "fact_sales_line.csv" in first
    assert "ground_truth.json" in first
    assert "dim_product.csv" in first


def test_a_different_seed_produces_different_data(two_runs, tmp_path):
    """Otherwise the test above would pass on a generator that ignores its seed entirely."""
    first, _ = two_runs
    subprocess.run(
        [sys.executable, str(GENERATOR), "--seed", str(SEED + 1), "--lines", str(LINES),
         "--out", str(tmp_path)],
        cwd=ROOT, capture_output=True, text=True, check=True,
        encoding="utf-8", errors="replace")

    other = digests(tmp_path)
    assert other["fact_sales_line.csv"] != first["fact_sales_line.csv"]
    assert other["ground_truth.json"] != first["ground_truth.json"]
