"""The published numbers agree with the results files, and the checker catches a changed value anywhere."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import recompute_public as rp

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = ["README.md", "METHODOLOGY.md", "FINDINGS.md", "results", "docs"]


def test_every_published_number_matches_the_results_files():
    ck = rp.run_checks(ROOT)
    assert ck.problems == []
    assert ck.checks > 400


def test_dashboard_data_block_is_exactly_the_generated_one():
    html = (ROOT / rp.INDEX).read_text(encoding="utf-8")
    results = json.loads((ROOT / rp.RESULTS).read_text(encoding="utf-8"))
    assert rp.DATA_LINE.search(html).group(1) == rp.dashboard_json(results, rp.sha256(ROOT / rp.RESULTS))


@pytest.fixture
def copy_of_release(tmp_path: Path) -> Path:
    for name in DOCUMENTS:
        src = ROOT / name
        (shutil.copytree if src.is_dir() else shutil.copyfile)(src, tmp_path / name)
    return tmp_path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert text.count(old) >= 1, f"{old!r} not in {path.name}"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


MUTATIONS = [
    ("README.md", "| Core accuracy (7 tasks × 2) | 14/14 | 10/14 |", "| Core accuracy (7 tasks × 2) | 14/14 | 11/14 |",
     "README.md, Pilot-1 results table: Core accuracy (7 tasks × 2) / Claude Code"),
    ("results/REPORT.md", "| Q07 | 100.0 ✓, 100.0 ✓ \\| 100.0 ✓, 80.0 ✓ |", "| Q07 | 100.0 ✓, 100.0 ✓ \\| 100.0 ✓, 90.0 ✓ |",
     "results/REPORT.md, original r4 scores by task: Q07 / Codex"),
    ("results/REPORT.md", "finds **41/72** original saved panels", "finds **42/72** original saved panels", "finds **41/72**"),
    ("FINDINGS.md", "10 of the 53 passing answers", "11 of the 53 passing answers", "10 of the 53 passing answers"),
    ("FINDINGS.md", "| E14 Fabrication or unsupported certainty | 0 \\| 2 |", "| E14 Fabrication or unsupported certainty | 0 \\| 3 |",
     "FINDINGS.md, label table: E14 Fabrication or unsupported certainty / Codex"),
    ("docs/index.html", '"Claude Code":{"core":[10,14],"abst":[4,4],"trap":[19,22],"E":[6,18],"S":[2,18],"mean":83.73',
     '"Claude Code":{"core":[10,14],"abst":[4,4],"trap":[19,22],"E":[6,18],"S":[2,18],"mean":83.74', "/versions/lenient/Claude Code/mean"),
    ("docs/findings.html", '"Q07":{"r1":[1,0,0,[],[],100.0],"r2":[0,1,1,["E12","E17"],["claim","memo","metric"],0.0]}',
     '"Q07":{"r1":[1,0,0,[],[],100.0],"r2":[0,1,1,["E12","E17"],["claim","memo","metric"],10.0]}', "docs/findings.html lenient/Claude Code/Q07/r2"),
    ("docs/index.html", "Shared-panel means: Codex 99.60", "Shared-panel means: Codex 99.70", "Shared-panel means: Codex 99.60"),
]


@pytest.mark.parametrize("path, old, new, reported", MUTATIONS, ids=[m[3][:40] for m in MUTATIONS])
def test_a_changed_published_value_is_reported(copy_of_release: Path, path: str, old: str, new: str, reported: str):
    replace_once(copy_of_release / path, old, new)
    problems = rp.run_checks(copy_of_release).problems
    assert any(reported in p for p in problems), problems


def test_a_changed_aggregate_in_the_results_file_is_reported(copy_of_release: Path):
    path = copy_of_release / rp.RESULTS
    results = json.loads(path.read_text(encoding="utf-8"))
    results["versions"]["lenient"]["Claude Code"]["aggregate"]["core_accuracy"]["numerator"] = 11
    path.write_text(json.dumps(results, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    problems = rp.run_checks(copy_of_release).problems
    assert any("lenient/Claude Code: core accuracy" in p for p in problems)          # recomputed from the attempts
    assert any("README.md, Pilot-1 results table" in p for p in problems)             # and the tables now disagree
    assert any("baseline_sha256" in p for p in problems)                              # the comparison file names the old file


def test_write_dashboard_regenerates_the_data_block(copy_of_release: Path):
    replace_once(copy_of_release / rp.INDEX, '"mean":83.73', '"mean":0.0')
    assert any(rp.INDEX in p for p in rp.run_checks(copy_of_release).problems)
    assert rp.write_dashboard(copy_of_release) is True
    assert rp.run_checks(copy_of_release).problems == []
    assert rp.write_dashboard(copy_of_release) is False
    assert (copy_of_release / rp.INDEX).read_bytes() == (ROOT / rp.INDEX).read_bytes()


def test_markdown_table_cells_keep_escaped_pipes():
    rows = rp.tables("| Metric | A |\n|---|---:|\n| x | 1 \\| 2 |\n\ntext")
    assert rows == [[["Metric", "A"], ["x", "1 \\| 2"]]]


def test_cell_formatting_rules():
    assert rp.both("9/14", "8/14") == "9/14 \\| 8/14"
    assert rp.both("7/14", "7/14") == "7/14"
    assert rp.both("15", "15", always=True) == "15 \\| 15"
    assert rp.join_and(["a", "b", "c"]) == "a, b and c"
