"""F: 承認した11資料でphysicalの旧/候補を各2回比較する。採用・採点は人手で行う。"""

import argparse
import json
import shutil
import sys
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from novel import history, run
from novel.phases.check import CheckFormatError, check_messages, load_inputs, validate_result
from novel.schema import CheckResult
from test.compare_generation import fingerprint, runtime_versions, save
from test.measure_check import verify_state
from test.verify_backend import model_snapshot
from util.config import DEFAULT_CONFIG, load_backend, public_url
from util.gateway import OpenAICompatibleGateway

FIXED = PROJECT_ROOT / "test/fixtures/check"
ADDITIONAL = PROJECT_ROOT / "test/fixtures/remediation/physical"
CANDIDATE = PROJECT_ROOT / "test/fixtures/remediation/physical-candidate.md"


def conditions(config) -> dict:
    if urlsplit(config.base_url).hostname not in ("localhost", "127.0.0.1", "::1"):
        raise run.RunError("Physical comparison requires local loopback LM Studio (D1).")
    phase = config.phase("writing")  # M6と同じGemma担当の明示識別子を用いる。
    if phase.thinking is not None:
        raise run.RunError("Physical comparison requires thinking=null (D37).")
    return {"base_url": public_url(config.base_url), "phase": phase.model_dump(),
            "configured_context_length": config.context_length}


def code_hashes() -> dict:
    return {**fingerprint(), "test/compare_physical.py": history.digest(Path(__file__).read_bytes())}


def hashes(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): history.digest(p.read_bytes())
            for p in sorted(folder.rglob("*")) if p.is_file()}


def prepare(study: Path, config_path=DEFAULT_CONFIG, *, evaluator: str, snapshot=model_snapshot) -> Path:
    study = Path(study)
    config = load_backend(config_path)
    public = conditions(config)
    original = json.loads((FIXED / "manifest.json").read_text(encoding="utf-8"))
    additional = json.loads((ADDITIONAL / "manifest.json").read_text(encoding="utf-8"))
    if additional["status"] != "human_approved_2026-10-27":
        raise run.RunError("Physical gold materials require human approval before prepare.")
    if len(original["cases"]) != 5 or len(additional["cases"]) != 6:
        raise run.RunError("Physical comparison expects five fixed and six additional cases.")
    observation = snapshot(config)
    verify_state(observation, config.phase("writing").model, config.context_length)
    cases = []
    sources = {}
    for group, material, root in (("m6", original, FIXED), ("new", additional, ADDITIONAL)):
        for case in material["cases"]:
            folder = root / case["id"]
            load_inputs(folder)
            if hashes(folder) != case["files"]:
                raise run.RunError("Physical source artifacts do not match the approved hashes.")
            cid = f"{group}-{case['id']}"
            sources[cid] = folder
            cases.append({"id": cid, "split": case.get("split", "tuning"),
                          "source": group, "kind": case["kind"], "files": case["files"],
                          "known_issues": [issue for issue in case["known_issues"]
                                           if issue.get("item", "physical") == "physical" and issue["id"] != "R02"],
                          "excluded": [issue for issue in case["known_issues"] if issue["id"] == "R02"],
                          "rationale": case.get("rationale", case.get("source")),
                          "exclusion_reason": "R02 is accepted exaggeration by the existing user judgment (D53)"})
    prompts = {"old": (PROJECT_ROOT / "prompts/check/physical.md").read_text(encoding="utf-8"),
               "candidate": CANDIDATE.read_text(encoding="utf-8")}
    trials = []
    for split in ("tuning", "holdout"):
        for repeat in (1, 2):
            for case in cases:
                if case["split"] != split:
                    continue
                versions = ("old", "candidate") if repeat == 1 else ("candidate", "old")
                for version in versions:
                    trials.append({"id": f"{len(trials)+1:02d}-{case['id']}-{version}-r{repeat}",
                                   "case": case["id"], "split": split, "version": version, "repeat": repeat})
    if len(trials) != 44:
        raise run.RunError("The approved comparison must contain 44 calls.")
    study.mkdir(parents=True)
    (study / "fixtures").mkdir()
    for case in cases:
        shutil.copytree(sources[case["id"]], study / "fixtures" / case["id"])
    (study / "prompts").mkdir()
    for version, text in prompts.items():
        (study / "prompts" / f"{version}.md").write_text(text, encoding="utf-8", newline="")
    save(study / "materials.json", {"cases": cases, "source_manifests": {
        "m6": history.digest((FIXED / "manifest.json").read_bytes()),
        "new": history.digest((ADDITIONAL / "manifest.json").read_bytes())}})
    save(study / "plan.json", {
        "schema_version": 1, "created_at": history.now(), "evaluator": evaluator,
        "approval": "User approved six added gold cases, candidate and 44 calls on 2026-10-27",
        "conditions": public, "runtime": runtime_versions(), "code": code_hashes(),
        "materials_sha256": history.digest((study / "materials.json").read_bytes()),
        "fixtures": {case["id"]: hashes(study / "fixtures" / case["id"]) for case in cases},
        "prompts": {version: history.text_hash(text) for version, text in prompts.items()},
        "observed_before_sampling": observation, "trials": trials,
        "scoring": "Human cause-level mapping; no automatic precision threshold or deployment",
    })
    save(study / "results.json", {"plan_sha256": history.digest((study / "plan.json").read_bytes()), "trials": []})
    return study


def execute(study: Path, config_path=DEFAULT_CONFIG, *, gateway_factory=OpenAICompatibleGateway,
            snapshot=model_snapshot, timeout=1800) -> Path:
    study = Path(study)
    config = load_backend(config_path)
    phase = config.phase("writing")
    trial_config = config.model_copy(update={"phases": {**config.phases, "check": phase}})
    plan = json.loads((study / "plan.json").read_text(encoding="utf-8"))
    results = json.loads((study / "results.json").read_text(encoding="utf-8"))
    if history.digest((study / "plan.json").read_bytes()) != results["plan_sha256"]:
        raise run.RunError("Physical fixed plan changed.")
    if conditions(config) != plan["conditions"] or code_hashes() != plan["code"]:
        raise run.RunError("Physical conditions/code changed after freeze.")
    if history.digest((study / "materials.json").read_bytes()) != plan["materials_sha256"]:
        raise run.RunError("Physical gold materials changed after freeze.")
    for version, fingerprint_value in plan["prompts"].items():
        text = (study / "prompts" / f"{version}.md").read_text(encoding="utf-8")
        if history.text_hash(text) != fingerprint_value:
            raise run.RunError("Physical prompt changed after freeze.")
    for case, files in plan["fixtures"].items():
        if hashes(study / "fixtures" / case) != files:
            raise run.RunError("Physical source artifacts changed after freeze.")
    for previous in results["trials"]:
        folder = study / previous["id"]
        if previous.get("files") is not None and hashes(folder) != previous["files"]:
            raise run.RunError("Physical saved trial changed; no implicit resampling.")
    seen = {trial["id"] for trial in results["trials"]}
    for spec in plan["trials"]:
        if spec["id"] in seen:
            continue
        if code_hashes() != plan["code"]:
            raise run.RunError("Physical code changed during sampling.")
        system = (study / "prompts" / f"{spec['version']}.md").read_text(encoding="utf-8")
        if history.text_hash(system) != plan["prompts"][spec["version"]]:
            raise run.RunError("Physical prompt changed after freeze.")
        before = snapshot(config)
        verify_state(before, phase.model, config.context_length)
        folder = study / spec["id"]
        shutil.copytree(study / "fixtures" / spec["case"], folder)
        inputs = {}
        plot, novel = load_inputs(folder, fingerprints=inputs)
        trial = {**spec, "status": "running", "started_at": history.now(), "before": before}
        results["trials"].append(trial)
        save(study / "results.json", results)
        print(f"[physical] {spec['id']}", flush=True)
        gateway = None
        started = perf_counter()
        try:
            with history.Operation(folder, "physical_comparison", config=trial_config, new=True,
                                   inputs=inputs, prompts={spec["version"]: system}) as operation:
                operation.step = "check_physical"
                try:
                    with gateway_factory(model=phase.model, base_url=config.base_url,
                                         api_key=config.api_key.get_secret_value(), log_path=folder / run.CALLS,
                                         phase="check_physical", thinking=phase.thinking, timeout=timeout) as gateway:
                        result = gateway.parse(check_messages(plot, novel, system), CheckResult)
                        validate_result(result, "physical", novel)
                    path = folder / "physical.json"
                    path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
                    history.record_output(path)
                except BaseException as error:
                    if isinstance(error, CheckFormatError):
                        operation.last_error_code = error.code
                    raise
                finally:
                    response = getattr(gateway, "last_response", None)
                    if response is not None and response.choices:
                        raw = response.choices[0].message.content
                        if isinstance(raw, str):
                            path = folder / "physical_raw.txt"
                            path.write_text(raw, encoding="utf-8")
                            history.record_output(path)
            trial["status"] = "success"
        except Exception as error:
            trial.update(status="error", error_type=type(error).__name__,
                         error_code=error.code if isinstance(error, CheckFormatError)
                         else getattr(gateway, "last_error_code", None) or "operation_failed")
        except BaseException as error:
            trial.update(status="interrupted", error_type=type(error).__name__)
            raise
        finally:
            trial["wall_seconds"] = perf_counter() - started
            trial["call_id"] = getattr(gateway, "last_call_id", None)
            trial["after"] = snapshot(config)
            trial["files"] = hashes(folder)
            save(study / "results.json", results)
        try:
            verify_state(trial["after"], phase.model, config.context_length)
        except run.RunError:
            trial["observation_status"] = "error"
            save(study / "results.json", results)
            raise
    write_review(study)
    return study


def write_review(study: Path) -> None:
    path = study / "human_review.md"
    if path.exists():
        return
    results = json.loads((study / "results.json").read_text(encoding="utf-8"))
    lines = ["# physical 旧/候補の人手照合", "", "状態: 未評価。本番プロンプトの採否は未確定。", "",
             "[計画](plan.json) / [資料と正解](materials.json) / [台帳](results.json)", "",
             "各指摘を既知原因へ対応付け、TP/FP/FN、新規妥当指摘、重複、失敗、所要時間を比較してください。"
             "R02の既存の許容判断を保持します。旧M6の実測は今回の対照群に流用しません。", "",
             "| 試行 | 分割 | 版 | 状態 | 指摘数 | 人手TP/FP/FN・新規指摘・根拠 |", "|---|---|---|---|---|---|"]
    for trial in results["trials"]:
        report = study / trial["id"] / "physical.json"
        count = len(json.loads(report.read_text(encoding="utf-8"))["issues"]) if report.is_file() else "未測定"
        lines.append(f"| [{trial['id']}]({trial['id']}/) | {trial['split']} | {trial['version']} | {trial['status']} | {count} | 未評価 |")
    with path.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "execute"))
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--evaluator", default="ユーザ")
    args = parser.parse_args(argv)
    if args.command == "prepare":
        prepare(args.study, args.config, evaluator=args.evaluator)
    else:
        execute(args.study, args.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
