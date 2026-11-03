#!/usr/bin/env python3
"""Recompute the published Pilot-1 numbers and check every place that reports them.

    python tools/recompute_public.py                    # check; exits 1 and lists every disagreement
    python tools/recompute_public.py --write-dashboard  # first rewrite the data block of docs/index.html

Only the Python standard library is needed. Sources:
  results/pilot1_four_products.json            original r4 results: aggregates and per-attempt records per product
  results/pilot1_shared_panel_comparison.json  shared three-judge comparison (aggregates only)
  docs/findings.html                           per-attempt taxonomy codes (their only public copy)

Checks:
  1. Metrics recomputed from the per-attempt records agree with the stored aggregates. Counts, medians and outcomes
     are exact; rates and totals are stored rounded and checked to that rounding. Per-attempt scores are stored
     rounded to 0.1, so mean scores are checked to within that rounding.
  2. The results tables in README.md, results/REPORT.md and FINDINGS.md, and the figures quoted in their text and in
     METHODOLOGY.md, equal the values formatted from the JSON files.
  3. docs/index.html embeds exactly the data generated from the results file, including the file's SHA-256.
     docs/findings.html agrees with the results file on every attempt's success, E, S and score, and its taxonomy codes
     give the counts that FINDINGS.md reports. Both dashboards quote the shared-panel figures of the comparison file.
Trap recall and format failures have no per-attempt public records; they are checked as published aggregates only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
RESULTS = "results/pilot1_four_products.json"
SHARED = "results/pilot1_shared_panel_comparison.json"
INDEX = "docs/index.html"
FINDINGS_HTML = "docs/findings.html"

CORE = ("Q03", "Q04", "Q07", "Q12", "Q14", "Q16", "Q17")
UNANSWERABLE = ("Q26", "Q27")
VERSIONS = ("lenient", "strict")
TIME_LIMIT_S = 1200
SPEED_BONUS = 0.10                      # speed-adjusted score: passing attempts get score x (1 + 0.10 x (1 - t/1200))
HALF_STEP = 0.05                        # per-attempt scores are stored rounded to 0.1
DATA_LINE = re.compile(r"^const DATA = (\{.*\});$", re.M)


class Checker:
    """Collects every comparison; a problem names the file, the item and both values."""

    def __init__(self) -> None:
        self.checks = 0
        self.problems: list[str] = []

    def eq(self, where: str, published: Any, expected: Any) -> None:
        self.checks += 1
        if published != expected:
            self.problems.append(f"{where}: published {published!r}, expected {expected!r}")

    def near(self, where: str, published: float, recomputed: float, tolerance: float) -> None:
        self.checks += 1
        if published is None or abs(published - recomputed) > tolerance + 1e-9:
            self.problems.append(f"{where}: published {published!r}, recomputed {recomputed:.4f} (tolerance {tolerance:g})")

    def quoted(self, where: str, text: str, snippet: str) -> None:
        self.checks += 1
        if snippet not in text:
            self.problems.append(f"{where}: expected text not found: {snippet!r}")

    def fail(self, message: str) -> None:
        self.checks += 1
        self.problems.append(message)


# ------------------------------------------------------------------------------------------------------- helpers --

def frac(ratio: dict[str, Any]) -> str:
    return f"{ratio['numerator']}/{ratio['denominator']}"


def both(lenient: str, strict: str, always: bool = False) -> str:
    """A table cell: 'lenient \\| strict', or a single value when the two agree (unless `always`)."""
    return lenient if lenient == strict and not always else f"{lenient} \\| {strict}"


def join_and(items: list[str]) -> str:
    return ", ".join(items[:-1]) + " and " + items[-1]


def attempts(product: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [(task, rep, rec) for task, reps in product["per_task"].items() for rep, rec in reps.items()]


def seconds(rec: dict[str, Any]) -> float:
    return float(rec["elapsed_s"] or TIME_LIMIT_S)        # as in final_results.py: a missing time counts as the cap


def speed_adjusted(rec: dict[str, Any]) -> float:
    if not rec["success"]:
        return rec["score"]
    return rec["score"] * (1 + SPEED_BONUS * max(0.0, 1 - seconds(rec) / TIME_LIMIT_S))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tables(text: str) -> list[list[list[str]]]:
    """Every Markdown table in `text` as rows of cells (separator rows dropped; escaped pipes stay in the cell)."""
    out: list[list[list[str]]] = []
    current: list[list[str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            cells = [c.strip() for c in re.split(r"(?<!\\)\|", stripped)[1:-1]]
            if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                current.append(cells)
        elif current:
            out.append(current)
            current = []
    if current:
        out.append(current)
    return out


def find_table(text: str, first_header_cell: str) -> list[list[str]] | None:
    return next((t for t in tables(text) if t and t[0] and t[0][0].startswith(first_header_cell)), None)


def check_grid(ck: Checker, where: str, table: list[list[str]] | None, expected: dict[str, dict[str, str]]) -> None:
    """`expected`: row label -> {column label -> cell}. The table must have exactly these rows and columns."""
    if table is None:
        ck.fail(f"{where}: table not found")
        return
    header, body = table[0], table[1:]
    columns = list(next(iter(expected.values())))
    ck.eq(f"{where}: columns", header[1:], columns)
    ck.eq(f"{where}: rows", [row[0] for row in body], list(expected))
    for row in body:
        want = expected.get(row[0], {})
        for column, cell in zip(header[1:], row[1:]):
            if column in want:
                ck.eq(f"{where}: {row[0]} / {column}", cell, want[column])


def embedded_data(html: str, where: str) -> Any:
    m = DATA_LINE.search(html)
    if m is None:
        raise ValueError(f"{where}: no `const DATA = {{...}};` line")
    return json.loads(m.group(1))


def first_differences(published: Any, expected: Any, path: str = "", limit: int = 5) -> list[str]:
    """JSON paths where two values differ (at most `limit`)."""
    if isinstance(published, dict) and isinstance(expected, dict):
        out: list[str] = []
        for k in list(dict.fromkeys([*published, *expected])):
            if k not in published or k not in expected:
                out.append(f"{path}/{k}: present in only one")
            else:
                out += first_differences(published[k], expected[k], f"{path}/{k}", limit - len(out))
            if len(out) >= limit:
                break
        return out[:limit]
    if isinstance(published, list) and isinstance(expected, list) and len(published) == len(expected):
        out = []
        for i, (a, b) in enumerate(zip(published, expected)):
            out += first_differences(a, b, f"{path}/{i}", limit - len(out))
            if len(out) >= limit:
                break
        return out[:limit]
    return [] if published == expected else [f"{path or '/'}: published {published!r}, expected {expected!r}"]


# ----------------------------------------------------------------------------------------------- expected values --

R4_ROWS: list[tuple[str, Callable[[dict[str, Any]], str]]] = [
    ("Core accuracy (7 tasks × 2)", lambda p: frac(p["aggregate"]["core_accuracy"])),
    ("Valid abstention (Q26, Q27)", lambda p: frac(p["aggregate"]["valid_abstention"])),
    ("Trap recall", lambda p: frac(p["aggregate"]["trap_recall"])),
    ("Attempts with a wrong material claim (E)", lambda p: f"{p['errors_E']}/{p['aggregate']['silent_error_rate']['denominator']}"),
    ("Silent errors (S)", lambda p: frac(p["aggregate"]["silent_error_rate"])),
    ("Mean saved-content score", lambda p: f"{p['mean_score']:.2f}"),
    ("Speed-adjusted mean (≤ +10%)", lambda p: f"{p['mean_speed_adjusted_score']:.2f}"),
    ("Median seconds, all attempts", lambda p: f"{p['median_seconds_all']:.0f}"),
    ("Median seconds, successful deliveries", lambda p: f"{p['median_seconds_successful']:.0f}"),
    ("Successful deliveries per agent hour", lambda p: f"{p['correct_per_agent_hour']:.2f}"),
    ("Same delivery success in both repetitions", lambda p: p["same_success_both_reps"]),
    ("Terminal failures / format failures",
     lambda p: f"{len(p['aggregate']['terminal_failures'])} / {len(p['aggregate']['format_failures'])}"),
]

CODE_ROWS = [("E14 Fabrication or unsupported certainty", "E14"), ("E17 Metric–decision mismatch", "E17"),
             ("E12 Root-cause conflation", "E12"), ("E08 Confounding or composition", "E08"),
             ("Any wrong material claim (E)", "E"), ("Any unwarned wrong claim (S)", "S")]


def products_of(results: dict[str, Any]) -> list[str]:
    return list(results["versions"]["lenient"])


def r4_metrics_table(results: dict[str, Any]) -> dict[str, dict[str, str]]:
    lenient, strict = results["versions"]["lenient"], results["versions"]["strict"]
    return {label: {p: both(f(lenient[p]), f(strict[p])) for p in products_of(results)} for label, f in R4_ROWS}


def task_cell(product: dict[str, Any], task: str) -> str:
    reps = product["per_task"][task]
    return ", ".join(f"{reps[r]['score']:.1f} {'✓' if reps[r]['success'] else '✗'}"
                     + (" (timeout)" if reps[r]["outcome"] == "timeout" else "") for r in ("r1", "r2"))


def r4_task_table(results: dict[str, Any]) -> dict[str, dict[str, str]]:
    lenient, strict = results["versions"]["lenient"], results["versions"]["strict"]
    return {t: {p: both(task_cell(lenient[p], t), task_cell(strict[p], t)) for p in products_of(results)}
            for t in CORE + UNANSWERABLE}


def shared_value(shared: dict[str, Any], product: str, key: str) -> Any:
    return shared["products"][product]["shared_panel"]["lenient"][key]


def shared_table(results: dict[str, Any], shared: dict[str, Any], with_original_silent: bool) -> dict[str, dict[str, str]]:
    out = {}
    for p in products_of(results):
        lenient, strict = results["versions"]["lenient"][p], results["versions"]["strict"][p]
        silent = shared_value(shared, p, "silent_error_rate")
        row = {"Original r4 mean (lenient / strict)": f"{lenient['mean_score']:.2f} / {strict['mean_score']:.2f}",
               "Shared-panel mean": f"{shared_value(shared, p, 'mean_score'):.2f}",
               "Shared-panel core accuracy": frac(shared_value(shared, p, "core_accuracy"))}
        if with_original_silent:
            row["Original r4 silent errors (lenient / strict)"] = \
                f"{frac(lenient['aggregate']['silent_error_rate'])} / {frac(strict['aggregate']['silent_error_rate'])}"
        row["Shared-panel silent errors"] = f"{frac(silent)} ({100 * silent['value']:.1f}%)"
        out[p] = row
    return out


def code_counts(fdata: dict[str, Any], version: str, product: str, code: str) -> int:
    return sum(1 for reps in fdata[version][product].values() for d in reps.values() if code in d[3])


def code_table(results: dict[str, Any], fdata: dict[str, Any]) -> dict[str, dict[str, str]]:
    def count(version: str, product: str, code: str) -> int:
        prod = results["versions"][version][product]
        if code == "E":
            return prod["errors_E"]
        if code == "S":
            return prod["aggregate"]["silent_error_rate"]["numerator"]
        return code_counts(fdata, version, product, code)
    return {label: {p: both(str(count("lenient", p, code)), str(count("strict", p, code)), always=True)
                    for p in products_of(results)} for label, code in CODE_ROWS}


def dashboard_data(results: dict[str, Any], results_sha256: str) -> dict[str, Any]:
    """The data block of docs/index.html, generated from the results file."""
    versions: dict[str, Any] = {}
    for v in VERSIONS:
        versions[v] = {}
        for p, prod in results["versions"][v].items():
            agg = prod["aggregate"]
            pair = lambda ratio: [ratio["numerator"], ratio["denominator"]]
            versions[v][p] = {
                "core": pair(agg["core_accuracy"]), "abst": pair(agg["valid_abstention"]), "trap": pair(agg["trap_recall"]),
                "E": [prod["errors_E"], agg["silent_error_rate"]["denominator"]], "S": pair(agg["silent_error_rate"]),
                "mean": prod["mean_score"], "speed": prod["mean_speed_adjusted_score"], "cph": prod["correct_per_agent_hour"],
                "med": round(prod["median_seconds_all"]),
                "medsucc": None if prod["median_seconds_successful"] is None else round(prod["median_seconds_successful"]),
                "total_min": prod["total_agent_minutes"], "reps": prod["same_success_both_reps"],
                "timeouts": sum(1 for _, _, rec in attempts(prod) if rec["outcome"] == "timeout"),
                "tasks": {t: {r: [rec["score"], rec["success"], round(seconds(rec)), rec["outcome"]] for r, rec in reps.items()}
                          for t, reps in prod["per_task"].items()}}
    return {"products": products_of(results), "versions": versions, "results_sha256": results_sha256}


def dashboard_json(results: dict[str, Any], results_sha256: str) -> str:
    return json.dumps(dashboard_data(results, results_sha256), ensure_ascii=False, separators=(",", ":"))


# -------------------------------------------------------------------------------------------------------- checks --

def check_recomputed(ck: Checker, results: dict[str, Any]) -> None:
    for v in VERSIONS:
        for p, prod in results["versions"][v].items():
            where, agg, runs = f"{RESULTS} {v}/{p}", prod["aggregate"], attempts(prod)
            core = [rec for t, _, rec in runs if t in CORE]
            unanswerable = [rec for t, _, rec in runs if t in UNANSWERABLE]
            successful = [rec for _, _, rec in runs if rec["success"]]
            secs = [seconds(rec) for _, _, rec in runs]
            ck.eq(f"{where}: core accuracy", frac(agg["core_accuracy"]), f"{sum(r['success'] for r in core)}/{len(core)}")
            ck.eq(f"{where}: valid abstention", frac(agg["valid_abstention"]),
                  f"{sum(r['success'] for r in unanswerable)}/{len(unanswerable)}")
            ck.eq(f"{where}: errors_E", prod["errors_E"], sum(rec["E"] for _, _, rec in runs))
            ck.eq(f"{where}: silent errors", agg["silent_error_rate"]["numerator"], sum(rec["S"] for _, _, rec in runs))
            ck.eq(f"{where}: terminal failures", len(agg["terminal_failures"]),
                  sum(rec["outcome"] in ("timeout", "error") for _, _, rec in runs))
            ck.near(f"{where}: mean score", prod["mean_score"], statistics.fmean(rec["score"] for _, _, rec in runs),
                    HALF_STEP + 0.005)
            ck.near(f"{where}: speed-adjusted mean", prod["mean_speed_adjusted_score"],
                    statistics.fmean(speed_adjusted(rec) for _, _, rec in runs), HALF_STEP * (1 + SPEED_BONUS) + 0.005)
            ck.eq(f"{where}: median seconds, all", prod["median_seconds_all"], statistics.median(secs))
            ck.eq(f"{where}: median seconds, successful", prod["median_seconds_successful"],
                  statistics.median(seconds(r) for r in successful) if successful else None)
            ck.near(f"{where}: successful deliveries per agent hour", prod["correct_per_agent_hour"],
                    len(successful) / (sum(secs) / 3600), 0.005)
            ck.near(f"{where}: total agent minutes", prod["total_agent_minutes"], sum(secs) / 60, 0.05)
            same = sum(1 for reps in prod["per_task"].values() if len(reps) == 2 and reps["r1"]["success"] == reps["r2"]["success"])
            ck.eq(f"{where}: same success in both repetitions", prod["same_success_both_reps"], f"{same}/{len(prod['per_task'])}")


def check_shared_file(ck: Checker, results: dict[str, Any], shared: dict[str, Any], results_sha256: str) -> None:
    ck.eq(f"{SHARED}: baseline_sha256 (the results file it compares against)", shared["baseline_sha256"], results_sha256)
    ck.eq(f"{SHARED}: total reviews", shared["total_reviews"], shared["original_reviews"] + shared["added_reviews"])
    for p in products_of(results):
        entry = shared["products"][p]
        for v in VERSIONS:
            prod, original = results["versions"][v][p], entry["original_r4"][v]
            ck.eq(f"{SHARED} {p}/{v}: original r4 values equal the results file",
                  [original["mean_score"], original["core_accuracy"], original["errors_E"], original["silent_error_rate"]],
                  [prod["mean_score"], prod["aggregate"]["core_accuracy"], prod["errors_E"], prod["aggregate"]["silent_error_rate"]])
        for key in ("mean_score", "core_accuracy", "silent_error_rate"):    # the tables print one shared-panel value
            ck.eq(f"{SHARED} {p}: shared-panel {key} is the same under both fallback variants",
                  entry["shared_panel"]["strict"][key], entry["shared_panel"]["lenient"][key])


def check_documents(ck: Checker, root: Path, results: dict[str, Any], shared: dict[str, Any], fdata: dict[str, Any]) -> None:
    readme, report = (root / "README.md").read_text(encoding="utf-8"), (root / "results/REPORT.md").read_text(encoding="utf-8")
    findings, methodology = (root / "FINDINGS.md").read_text(encoding="utf-8"), (root / "METHODOLOGY.md").read_text(encoding="utf-8")
    products = products_of(results)
    check_grid(ck, "README.md, Pilot-1 results table", find_table(readme, "Metric"), r4_metrics_table(results))
    check_grid(ck, "results/REPORT.md, original r4 metrics", find_table(report, "Metric"), r4_metrics_table(results))
    check_grid(ck, "results/REPORT.md, original r4 scores by task", find_table(report, "Task"), r4_task_table(results))
    check_grid(ck, "results/REPORT.md, shared-panel table", find_table(report, "Product"), shared_table(results, shared, True))
    check_grid(ck, "FINDINGS.md, shared-panel table", find_table(findings, "Product"), shared_table(results, shared, False))
    check_grid(ck, "FINDINGS.md, label table", find_table(findings, "Answers with at least one claim tagged"),
               code_table(results, fdata))

    means = [f"{shared_value(shared, p, 'mean_score'):.2f}" for p in products]
    cores = [frac(shared_value(shared, p, "core_accuracy")) for p in products]
    silents = [frac(shared_value(shared, p, "silent_error_rate")) for p in products]
    added, total, outputs = shared["added_reviews"], shared["total_reviews"], shared["outputs"]
    ck.quoted("README.md", readme, f"{added} additional blind reviews complete {total} reviews of the same {outputs} answers")
    ck.quoted("README.md", readme, "Shared-panel means are " + ", ".join(f"{p} **{m}**" for p, m in zip(products, means)) + ".")
    ck.quoted("README.md", readme, f"Core successes are **{', '.join(cores)}**; silent errors are **{', '.join(silents)}**.")
    ck.quoted("results/REPORT.md", report, f"added {added} blind reviews to give every answer the same three judges")

    repair = results["repair"]
    orig, derived, n = repair["original_material_disagreement"], repair["derived_material_disagreement"], repair["outputs"]
    ck.quoted("results/REPORT.md", report, f"finds **{orig}/{n}** original saved panels")
    ck.quoted("results/REPORT.md", report, f"**{derived}/{n}** derived panels disagree")
    ck.quoted("METHODOLOGY.md", methodology, f"finds {orig}/{n} original saved panels with material disagreements")
    ck.quoted("METHODOLOGY.md", methodology, f"The derived r4 panels have {derived}/{n}")

    passing = {v: [(p, t, r) for p in products for t, r, rec in attempts(results["versions"][v][p]) if rec["success"]]
               for v in VERSIONS}
    flagged = {v: [(p, t, r) for p, t, r in passing[v] if results["versions"][v][p]["per_task"][t][r]["E"]] for v in VERSIONS}
    ck.quoted("FINDINGS.md", findings, f"{len(flagged['lenient'])} of the {len(passing['lenient'])} passing answers contained "
              f"at least one wrong material claim (lenient panel rule). Under the strict rule it was "
              f"{len(flagged['strict'])} of {len(passing['strict'])}.")
    in_numbers = [x for x in flagged["lenient"] if "metric" in fdata["lenient"][x[0]][x[1]][x[2]][4]]
    ck.quoted("FINDINGS.md", findings, "Under the lenient rule, none of those errors was in the structured numbers.")
    ck.eq("FINDINGS.md: lenient passing answers whose wrong claim is a structured number (text says none)", len(in_numbers), 0)
    answers = sum(len(attempts(results["versions"]["lenient"][p])) for p in products)
    e14 = {v: sum(code_counts(fdata, v, p, "E14") for p in products) for v in VERSIONS}
    ck.quoted("FINDINGS.md", findings, f"(taxonomy code E14) in {e14['lenient']} of {answers} answers under the lenient rule "
              f"and {e14['strict']} of {answers} under the strict rule.")
    ag = [results["versions"][v]["Antigravity"] for v in VERSIONS]
    ck.eq("FINDINGS.md: Antigravity E and S are the same under both rules (the text gives one figure)",
          [ag[0]["errors_E"], ag[0]["aggregate"]["silent_error_rate"]["numerator"]],
          [ag[1]["errors_E"], ag[1]["aggregate"]["silent_error_rate"]["numerator"]])
    ck.quoted("FINDINGS.md", findings, f"Antigravity had {ag[0]['errors_E']} answers with a wrong material claim, and "
              f"{ag[0]['aggregate']['silent_error_rate']['numerator']} of them had at least one unwarned wrong claim.")


def check_dashboards(ck: Checker, root: Path, results: dict[str, Any], shared: dict[str, Any], fdata: dict[str, Any],
                     results_sha256: str) -> None:
    index = (root / INDEX).read_text(encoding="utf-8")
    findings_html = (root / FINDINGS_HTML).read_text(encoding="utf-8")
    try:
        published = embedded_data(index, INDEX)
    except ValueError as exc:
        ck.fail(str(exc))
    else:
        ck.checks += 1
        diffs = first_differences(published, dashboard_data(results, results_sha256))
        if diffs:
            ck.problems.append(f"{INDEX}: embedded data differs from the results file (run with --write-dashboard): "
                               + "; ".join(diffs))

    count = 0
    for v in VERSIONS:
        for p, prod in results["versions"][v].items():
            for t, r, rec in attempts(prod):
                d = (fdata.get(v, {}).get(p, {}).get(t) or {}).get(r)
                count += 1
                if d is None:
                    ck.fail(f"{FINDINGS_HTML}: no data for {v}/{p}/{t}/{r}")
                    continue
                ck.eq(f"{FINDINGS_HTML} {v}/{p}/{t}/{r}: [passed, E, S, score]", [d[0], d[1], d[2], d[5]],
                      [int(rec["success"]), rec["E"], rec["S"], rec["score"]])
    ck.eq(f"{FINDINGS_HTML}: attempts in the data", sum(len(reps) for v in fdata for p in fdata[v] for reps in fdata[v][p].values()),
          count)

    products = products_of(results)
    means = [f"{shared_value(shared, p, 'mean_score'):.2f}" for p in products]
    cores = [frac(shared_value(shared, p, "core_accuracy")) for p in products]
    silents = [frac(shared_value(shared, p, "silent_error_rate")) for p in products]
    added, outputs, repair = shared["added_reviews"], shared["outputs"], results["repair"]
    ck.quoted(INDEX, index, f"added {added} blind reviews so all {outputs} answers have GPT, Claude and Grok judges")
    ck.quoted(INDEX, index, "Shared-panel means: " + ", ".join(f"{p} {m}" for p, m in zip(products, means))
              + f". Core successes: {', '.join(cores)}.")
    ck.quoted(INDEX, index, f"Silent errors under the shared panel: {', '.join(silents)}, respectively.")
    ck.quoted(INDEX, index, f"Original panel material disagreement: {repair['original_material_disagreement']}/{repair['outputs']}; "
              f"derived r4 panel: {repair['derived_material_disagreement']}/{repair['outputs']}.")
    ck.quoted(FINDINGS_HTML, findings_html, f"adds {added} blind reviews: all {outputs} answers now have GPT, Claude and Grok judges")
    ck.quoted(FINDINGS_HTML, findings_html, f"Shared-panel means are {join_and(means)} for {join_and(products)}, respectively; "
              f"core successes are {join_and(cores)}.")
    ck.quoted(FINDINGS_HTML, findings_html, f"Silent errors are {join_and(silents)}.")


def run_checks(root: Path = ROOT) -> Checker:
    root = Path(root)
    ck = Checker()
    results = json.loads((root / RESULTS).read_text(encoding="utf-8"))
    shared = json.loads((root / SHARED).read_text(encoding="utf-8"))
    results_sha256 = sha256(root / RESULTS)
    try:
        fdata = embedded_data((root / FINDINGS_HTML).read_text(encoding="utf-8"), FINDINGS_HTML)
    except ValueError as exc:
        ck.fail(str(exc))
        return ck
    check_recomputed(ck, results)
    check_shared_file(ck, results, shared, results_sha256)
    check_documents(ck, root, results, shared, fdata)
    check_dashboards(ck, root, results, shared, fdata, results_sha256)
    return ck


def write_dashboard(root: Path = ROOT) -> bool:
    """Rewrite the data line of docs/index.html from the results file; returns whether the file changed."""
    root = Path(root)
    path = root / INDEX
    html = path.read_text(encoding="utf-8")
    results = json.loads((root / RESULTS).read_text(encoding="utf-8"))
    line = "const DATA = " + dashboard_json(results, sha256(root / RESULTS)) + ";"
    if DATA_LINE.search(html) is None:
        raise ValueError(f"{INDEX}: no `const DATA = {{...}};` line to replace")
    new = DATA_LINE.sub(lambda _: line, html, count=1)
    if new == html:
        return False
    path.write_text(new, encoding="utf-8")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Recompute the published Pilot-1 numbers and check every place that reports them.")
    ap.add_argument("--write-dashboard", action="store_true", help="rewrite the data block of docs/index.html from the results file first")
    ap.add_argument("--root", type=Path, default=ROOT, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.write_dashboard:
        print(f"{INDEX}: data block {'rewritten' if write_dashboard(a.root) else 'already up to date'}")
    ck = run_checks(a.root)
    for problem in ck.problems:
        print("MISMATCH", problem)
    print(f"{ck.checks} checks, {len(ck.problems)} mismatches")
    return 1 if ck.problems else 0


if __name__ == "__main__":
    sys.exit(main())
