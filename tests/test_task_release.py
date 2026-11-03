"""The published task files stay exactly as the Pilot-1 agents saw them (README: "the exact task.md the agent saw")."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TASKS = ("Q03", "Q04", "Q07", "Q12", "Q14", "Q16", "Q17", "Q26", "Q27")

# SHA-256 of every file under tasks/ in the Pilot-1 release (commit 1910d3d). A task file must not change; a future
# round gets new task files instead.
RELEASED = {
    "tasks/Q03/answer.schema.json": "079e2605d09245446e6289869cf0ed52fa6cd746971c62c8d7a9a6c59c2e2209",
    "tasks/Q03/task.md": "b563751bd45247686f7b4c48a34b22e6fb3eaa4fa0d4af3f020b58c3b341a155",
    "tasks/Q04/answer.schema.json": "6c59c7349021ff8c41fe7e7d0d3671ab20c95d6ecf32bfb6a5d912c5cb3508fc",
    "tasks/Q04/task.md": "aeba643e28dca27acce8111276fcd0db21c9174c6fc74ef55e32e2799336eb14",
    "tasks/Q07/answer.schema.json": "56b766b2edbbd3b5e7e0ab1d669fe4a9cbaead6cc84e0db0c1e0093d8db4e9aa",
    "tasks/Q07/task.md": "72178fd26308242089d55c3dede0a08ca7d26494d268834a292a1c25661a98fe",
    "tasks/Q12/answer.schema.json": "5809faf1d6360ede4ea6176723310ef9c82c940396c9badfb49f987a23e0cfb1",
    "tasks/Q12/task.md": "6577f6b721d3ca4c8494a2b84f15aac6a6b0f8a84c062689d0043026bcb191b6",
    "tasks/Q14/answer.schema.json": "f3f3ff015ee703bce6d964a4c2413179ba556b0eb6ee6562e1664c7db103cada",
    "tasks/Q14/task.md": "c605fdf0112c53521d1c02c4c606bd0a1f6fd6b23af84ee969939d6a28230b67",
    "tasks/Q16/answer.schema.json": "6241320b53eb165c99c44d2470821d9a6ae088e957e729ba3785ff6a455ec582",
    "tasks/Q16/task.md": "bba8c199d574746676b6eee6b4ebdf43f8e034f56edb11c9c597380514e0bcee",
    "tasks/Q17/answer.schema.json": "8bfe58b6b634607509ece62c751cf53af11745056218adc7bf4e4883521ee00e",
    "tasks/Q17/task.md": "b81dc46197dd810fbe87ff23c03e9a5e9149232c19baaab826bd79201419fe52",
    "tasks/Q26/answer.schema.json": "7e8319098f32ea21286766b07613e225271b2534ea61eb12645784c7e2fed31a",
    "tasks/Q26/task.md": "5938ceaf6878f9592339296f80039a1f17ccefc154bc7e0a1e91bb7107da9cc5",
    "tasks/Q27/answer.schema.json": "528c89543172c60efb51d8fddcd98960c86c81d493d7d11cf02fe1234f8dbdc8",
    "tasks/Q27/task.md": "f293d3db76cb6a737530b3acd5b3bacdf1972038b991d74b901b7127e90aad76",
    "tasks/business_definitions.md": "0d31f56d56a7c5a92a40fe29c273a1b763399bbb536a7a5593e514b1941f2d8f",
    "tasks/execution_contract.md": "d050b556d66f9c67bd0728fb885441e6b323f4a064417663cb3c7578c238cd5f",
}


def test_task_files_are_byte_identical_to_the_release():
    present = {p.relative_to(ROOT).as_posix() for p in (ROOT / "tasks").rglob("*") if p.is_file()}
    assert present == set(RELEASED)
    for rel, digest in RELEASED.items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == digest, f"{rel} changed"


@pytest.mark.parametrize("task", TASKS)
def test_task_statement_names_its_task(task: str):
    assert (ROOT / "tasks" / task / "task.md").read_text(encoding="utf-8").startswith(f"# Task {task}\n")


@pytest.mark.parametrize("task", TASKS)
def test_answer_schema_is_a_valid_draft_2020_12_schema(task: str):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / "tasks" / task / "answer.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)


def test_output_contract_example_still_uses_the_documented_placeholder():
    """README explains that the example says "Q01"; keep that note accurate."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert '`"task_id": "Q01"`' in readme
    for task in TASKS:
        assert '"task_id": "Q01"' in (ROOT / "tasks" / task / "task.md").read_text(encoding="utf-8")
