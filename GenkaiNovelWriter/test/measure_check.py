"""M6: 同じ固定資料をQwen/Gemmaで検査し、人手の対応付けから集計する。

prepare / execute / summarize の順。失敗を自動再試行せず、未判定を0件としない。
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from novel import run
from novel.phases.check import ITEMS, LLM_ITEMS, load_inputs, run_check
from test.compare_generation import (digest, fingerprint, loaded, read, runtime_versions, save)
from test.verify_backend import model_snapshot
from util.config import DEFAULT_CONFIG, load_backend
from util.gateway import OpenAICompatibleGateway
from util.models import prepare_local_model

FIXTURES = PROJECT_ROOT / "test/fixtures/check"


def fixture_hashes(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(root.rglob("*")) if p.is_file()}


def code_hashes() -> dict:
    return {**fingerprint(), "test/measure_check.py": digest(Path(__file__))}


def public_conditions(config) -> dict:
    from urllib.parse import urlsplit
    if urlsplit(config.base_url).hostname not in ("localhost", "127.0.0.1", "::1"):
        raise run.RunError("Check comparison requires loopback LM Studio (D1).")
    phases = {label: config.phase(role).model_dump()
              for label, role in (("qwen", "structure"), ("gemma", "writing"))}
    if any(p["thinking"] is not None for p in phases.values()):
        raise run.RunError("Check comparison requires thinking=null (D37).")
    if phases["qwen"]["model"] == phases["gemma"]["model"]:
        raise run.RunError("Qwen and Gemma must have distinct identifiers.")
    return {"base_url": config.base_url, "context_length": config.context_length, "models": phases}


def validate_fixtures(root: Path) -> dict:
    manifest = read(root / "manifest.json")
    if len({c["id"] for c in manifest["cases"]}) != len(manifest["cases"]):
        raise run.RunError("Duplicate fixture identifiers.")
    for case in manifest["cases"]:
        folder = root / case["id"]
        if fixture_hashes(folder) != case["files"]:
            raise run.RunError("Fixture files differ from the pre-recorded manifest.")
        _, novel = load_inputs(folder)
        for issue in case["known_issues"]:
            if not any(s.index == issue["scene"] and issue["quote"] in s.content for s in novel.scenes):
                raise run.RunError("Known issue does not match its recorded original scene.")
        if case["kind"] == "real-output":
            for name, source in case["provenance"].items():
                if source["source_sha256"] != digest(folder / name):
                    raise run.RunError("Real-output fixture is not byte-identical to its source hash.")
    return manifest


def prepare(study: Path, config_path: Path, evaluator: str, *, fixtures=FIXTURES) -> Path:
    config = load_backend(config_path)
    conditions = public_conditions(config)
    manifest = validate_fixtures(fixtures)
    if not evaluator.strip():
        raise run.RunError("Record the human evaluator before comparison.")
    study = Path(study)
    study.mkdir(parents=True, exist_ok=False)
    shutil.copytree(fixtures, study / "fixtures")
    plan = {"created_utc": datetime.now(timezone.utc).isoformat(), "evaluator": evaluator,
            "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True).strip(),
            "runtime": runtime_versions(), "conditions": conditions,
            "code": code_hashes(), "fixtures": fixture_hashes(study / "fixtures"),
            "timeout": 1800,
            "protocol": "model groups qwen then gemma, case order fixed; before each group explicitly load writing model, then let production Check switch or retain it; group preparation excluded from wall time",
            "metrics": "human-adjudicated known-only recall and incorrect-finding count, per item; unknown/new valid findings separate; failed/not_run not scored",
            "limitations": ["Small fixed dataset; no general accuracy guarantee or automatic quality acceptance",
                            "Qwen Q4 / Gemma Q3 must be verified against actual snapshots; not Gemma Q4 evidence",
                            "OS cache and server sampling are not fully controlled; observation time included in wall time",
                            "Ground truth and generated findings require human confirmation; literal quotes do not establish TP",
                            "M3 contains hand edits; M5 subjective concerns are not automatically confirmed faults"],
            "trials": [{"id": f"{label}-{case['id']}", "model": label, "case": case["id"]}
                       for label in conditions["models"] for case in manifest["cases"]]}
    save(study / "plan.json", plan)
    save(study / "results.json", {"plan_sha256": digest(study / "plan.json"), "trials": []})
    return study


def validate_study(study: Path, config) -> tuple[dict, dict]:
    plan, results = read(study / "plan.json"), read(study / "results.json")
    if digest(study / "plan.json") != results["plan_sha256"]:
        raise run.RunError("Comparison plan changed.")
    if public_conditions(config) != plan["conditions"] or code_hashes() != plan["code"]:
        raise run.RunError("Comparison code/configuration changed; create a new study.")
    if fixture_hashes(study / "fixtures") != plan["fixtures"]:
        raise run.RunError("Comparison fixtures changed.")
    for trial in results["trials"]:
        for name, expected in trial.get("hashes", {}).items():
            if digest(study / trial["id"] / name) != expected:
                raise run.RunError("A saved comparison artifact changed.")
    return plan, results


def verify_state(state: dict, model: str, length: int) -> None:
    instances = loaded(state)
    if len(instances) != 1 or model not in (instances[0]["key"], instances[0]["id"]):
        raise run.RunError("Actual loaded model differs from the planned model.")
    if instances[0]["config"]["context_length"] != length:
        raise run.RunError("Actual context length differs from the plan.")


def execute(study: Path, config_path: Path, *, gateway_factory=OpenAICompatibleGateway,
            snapshot=model_snapshot, command=subprocess.run) -> Path:
    study = Path(study)
    config = load_backend(config_path)
    plan, results = validate_study(study, config)
    manifest = read(study / "fixtures/manifest.json")
    cases = {c["id"]: c for c in manifest["cases"]}
    seen = {t["id"] for t in results["trials"]}
    group = None
    for spec in plan["trials"]:
        if spec["id"] in seen:
            continue
        folder = study / spec["id"]
        shutil.copytree(study / "fixtures" / spec["case"], folder)
        trial = {**spec, "status": "running", "started_utc": datetime.now(timezone.utc).isoformat(),
                 "items": {item: "not_run" for item in ITEMS}, "observations": []}
        results["trials"].append(trial)
        save(study / "results.json", results)
        observations = trial["observations"]
        started = None
        phase = config.phase("structure" if spec["model"] == "qwen" else "writing")
        trial_config = config.model_copy(update={"phases": {**config.phases, "check": phase}})

        def observed_factory(**kwargs):
            delegate = gateway_factory(**kwargs)

            class Observed:
                def __enter__(self):
                    delegate.__enter__()
                    return self

                def __exit__(self, *args):
                    return delegate.__exit__(*args)

                @property
                def last_response(self):
                    return delegate.last_response

                @property
                def last_call_id(self):
                    return getattr(delegate, "last_call_id", None)

                @property
                def last_error_code(self):
                    return getattr(delegate, "last_error_code", None)

                def parse(self, messages, model_cls):
                    before = snapshot(config)
                    entry = {"phase": kwargs["phase"], "before": before}
                    observations.append(entry)
                    try:
                        value = delegate.parse(messages, model_cls)
                    finally:
                        entry["after"] = snapshot(config)
                        save(folder / "models.json", observations)
                    verify_state(entry["after"], phase.model, config.context_length)
                    return value

            return Observed()

        print(f"[M6] {spec['id']}", flush=True)
        try:
            if group != spec["model"]:
                # D46専用運用。書き手と異なる/同じ検査モデルの両経路を確認。
                writing = config.phase("writing").model
                prepare_local_model(config.base_url, config.api_key.get_secret_value(), writing)
                command(["lms", "load", writing, "--context-length", str(config.context_length), "--yes"],
                        capture_output=True, check=True, timeout=600,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                state = snapshot(config)
                verify_state(state, writing, config.context_length)
                save(folder / "group_start.json", state)
                group = spec["model"]
            started = perf_counter()
            run_check(folder, trial_config, timeout=plan["timeout"], allowed_names=cases[spec["case"]]["allowed_names"],
                      gateway_factory=observed_factory)
            trial["status"] = "success"
        except Exception as error:
            trial["status"] = "error"
            trial["error_type"] = type(error).__name__
        finally:
            trial["wall_seconds"] = perf_counter() - started if started is not None else None
            for item in ITEMS:
                if run.check_path(folder, item).is_file():
                    trial["items"][item] = "success"
            error_path = folder / run.CHECK / "error.json"
            if error_path.exists():
                trial["items"][read(error_path)["item"]] = "error"
            if trial["status"] == "error" and all(s == "success" for s in trial["items"].values()):
                trial["observation_status"] = "error"
            trial["hashes"] = fixture_hashes(folder)
            save(study / "results.json", results)
    write_review(study)
    return study


def write_review(study: Path) -> None:
    """採点欄は一度だけ作成し、既存の人手評価を上書きしない。"""
    plan, results = read(study / "plan.json"), read(study / "results.json")
    cases = {c["id"]: c for c in read(study / "fixtures/manifest.json")["cases"]}
    rows = []
    lines = ["# M6 検査モデル比較", "", f"評価者: {plan['evaluator']} / 状態: 人手未評価", "",
             "[固定計画](plan.json) / [実行台帳](results.json) / [既知一覧・照合基準](fixtures/manifest.json)", "",
             "各指摘を原文・Plot・既知一覧で照合し、human_review.jsonを記入してください。引用一致だけでは正解としません。", "",
             "verdict: tp=既知問題の正しい指摘 / fp=誤検出 / new_valid=一覧外の妥当な指摘 / duplicate=重複指摘 / pending=未判定。tpにはknown_ids、全判定に根拠reasonを記入。各行のconfirmed=trueは、その項目全体(見逃しを含む)の人手照合完了を意味します。", "",
             "実出力の曖昧な正解は ground_truth の include/exclude/pending と根拠を人手で記入。除外は理由と件数を残し、評価後の基準変更として記録します。正常例や既知以外の指摘も確認してください。", ""]
    for trial in results["trials"]:
        lines.extend([f"## {trial['id']}: {trial['status']}", "",
                      f"経過: {trial['wall_seconds']}秒 / [検査報告]({trial['id']}/{run.CHECK_REPORT}) / [原文・Plot]({trial['id']}/{run.PLOT})", ""])
        case = cases[trial["case"]]
        for item in LLM_ITEMS:
            known = [i for i in case["known_issues"] if i["item"] == item]
            status = trial["items"][item]
            data = read(run.check_path(study / trial["id"], item)) if status == "success" else {"issues": []}
            rows.append({"trial": trial["id"], "item": item, "status": status, "confirmed": False,
                         "ground_truth": [{"id": i["id"], "decision": "pending", "reason": ""} for i in known],
                         "findings": [{"index": n, "verdict": "pending", "known_ids": [], "reason": ""}
                                      for n, _ in enumerate(data["issues"])]})
            lines.extend([f"### {item}: {status}; 既知: {', '.join(i['id'] for i in known) or 'なし(実出力の完全正常を意味しない)'}", ""])
            for n, finding in enumerate(data["issues"]):
                lines.append(f"- 指摘{n}: シーン{finding['scene']} {json.dumps(finding['quote'], ensure_ascii=False)} — {' '.join(finding['reason'].splitlines())}")
            lines.append("")
    if not (study / "human_review.json").exists():
        save(study / "human_review.json", {"plan_sha256": digest(study / "plan.json"),
                                            "evaluator": plan["evaluator"], "rows": rows,
                                            "selection": {"decision": "pending", "reason": "", "limitations": "", "next_action": ""}})
    if not (study / "human_review.md").exists():
        (study / "human_review.md").write_text("\n".join(lines), encoding="utf-8")


def summarize(study: Path) -> dict:
    """人手の対応付けを検証して集計する。失敗・未判定に数値0を与えない。"""
    plan, results = read(study / "plan.json"), read(study / "results.json")
    if digest(study / "plan.json") != results["plan_sha256"]:
        raise run.RunError("Comparison plan changed.")
    review = read(study / "human_review.json")
    if review["plan_sha256"] != results["plan_sha256"]:
        raise run.RunError("Review does not refer to this plan.")
    for trial in results["trials"]:
        for name, value in trial["hashes"].items():
            if digest(study / trial["id"] / name) != value:
                raise run.RunError("Saved comparison artifact changed.")
    cases = {c["id"]: c for c in read(study / "fixtures/manifest.json")["cases"]}
    rows = {(r["trial"], r["item"]): r for r in review["rows"]}
    if len(rows) != len(review["rows"]):
        raise run.RunError("Duplicate review rows.")
    summaries = []
    shared_truth = {}
    for trial in results["trials"]:
        for item in LLM_ITEMS:
            result = {"trial": trial["id"], "model": trial["model"], "item": item, "status": trial["items"][item],
                      "tp": None, "fp": None, "fn": None, "recall": None}
            if result["status"] != "success":
                summaries.append(result)
                continue
            row = rows.get((trial["id"], item))
            if row is None:
                raise run.RunError("Missing review row.")
            findings = read(run.check_path(study / trial["id"], item))["issues"]
            known = {i["id"] for i in cases[trial["case"]]["known_issues"] if i["item"] == item}
            truth = row["ground_truth"]
            decisions = {r["id"]: r for r in truth}
            if set(decisions) != known or len(decisions) != len(truth):
                raise run.RunError("Ground truth IDs differ from the fixed list.")
            matched = row["findings"]
            if sorted(r["index"] for r in matched) != list(range(len(findings))):
                raise run.RunError("Each finding must be reviewed exactly once.")
            if (not row["confirmed"] or any(r["verdict"] == "pending" for r in matched)
                    or any(r["decision"] == "pending" for r in truth)):
                result["status"] = "pending_human"
                summaries.append(result)
                continue
            if any(r["decision"] not in ("include", "exclude") or not r["reason"].strip() for r in truth):
                raise run.RunError("Ground truth decisions need include/exclude and rationale.")
            included = {key for key, value in decisions.items() if value["decision"] == "include"}
            truth_key = (trial["case"], item)
            if truth_key in shared_truth and shared_truth[truth_key] != included:
                raise run.RunError("Ground truth must be identical across models for the same case/item.")
            shared_truth[truth_key] = included
            detected = set()
            fp = new_valid = duplicates = 0
            for match in matched:
                verdict, ids = match["verdict"], set(match["known_ids"])
                if not match["reason"].strip() or verdict not in ("tp", "fp", "new_valid", "duplicate"):
                    raise run.RunError("Every finding needs a valid verdict and rationale.")
                if verdict in ("tp", "duplicate"):
                    if not ids or not ids <= included:
                        raise run.RunError("Matched IDs must refer to included known issues.")
                    if verdict == "tp":
                        if detected & ids:
                            raise run.RunError("Repeated detections must be marked duplicate.")
                        detected.update(ids)
                    else:
                        duplicates += 1
                elif ids:
                    raise run.RunError("FP/new_valid cannot claim a known issue.")
                fp += verdict == "fp"
                new_valid += verdict == "new_valid"
            result.update(status="reviewed", tp=len(detected), fp=fp, fn=len(included-detected),
                          recall=len(detected)/len(included) if included else None,
                          new_valid=new_valid, duplicates=duplicates, excluded=sorted(known-included))
            summaries.append(result)
    totals = []
    for model in plan["conditions"]["models"]:
        for item in LLM_ITEMS:
            group = [r for r in summaries if r["model"] == model and r["item"] == item]
            complete = len(group) == len(cases) and all(r["status"] == "reviewed" for r in group)
            total = {"model": model, "item": item, "status": "reviewed" if complete else "incomplete",
                     "reviewed_cases": sum(r["status"] == "reviewed" for r in group),
                     "failures_or_not_run": sum(r["status"] in ("error", "not_run") for r in group),
                     "tp": None, "fp": None, "fn": None, "recall": None}
            if complete:
                for key in ("tp", "fp", "fn"):
                    total[key] = sum(r[key] for r in group)
                denominator = total["tp"]+total["fn"]
                total["recall"] = total["tp"]/denominator if denominator else None
            totals.append(total)
    selection = review["selection"]
    if selection["decision"] not in ("pending", "adopt_qwen", "adopt_gemma", "defer", "reject"):
        raise run.RunError("Unknown model-selection decision.")
    if selection["decision"] != "pending":
        if not all(str(selection[key]).strip() for key in ("reason", "limitations", "next_action")):
            raise run.RunError("Model-selection decision requires rationale, limitations and next action.")
        if not all(r["status"] in ("reviewed", "error", "not_run") for r in summaries):
            raise run.RunError("Finish human review before model selection.")
    report = {"rows": summaries, "totals": totals, "selection": selection}
    save(study / "metrics.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "execute", "summarize"):
        command = commands.add_parser(name)
        command.add_argument("--study", type=Path, required=True)
        if name != "summarize":
            command.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
        if name == "prepare":
            command.add_argument("--evaluator", required=True)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        prepare(args.study, args.config, args.evaluator)
    elif args.command == "execute":
        execute(args.study, args.config)
    else:
        summarize(args.study)
    print(args.study)


if __name__ == "__main__":
    main()
