"""U13: 人手承認した8資料×2回を固定条件で採取する。自動採点・再試行はしない。"""

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from novel import history, run
from novel.phases import concept
from novel.schema import Concept
from test.compare_generation import fingerprint, runtime_versions, save
from test.measure_check import verify_state
from test.verify_backend import model_snapshot
from util.config import DEFAULT_CONFIG, load_backend, public_url
from util.gateway import OpenAICompatibleGateway

MATERIAL = PROJECT_ROOT / "test/fixtures/remediation/concept-verification.json"


def conditions(config) -> dict:
    if urlsplit(config.base_url).hostname not in ("localhost", "127.0.0.1", "::1"):
        raise run.RunError("U13 evaluation requires local loopback LM Studio (D1).")
    phase = config.phase("concept")
    if phase.thinking is not None:
        raise run.RunError("U13 evaluation requires thinking=null (D37).")
    return {"base_url": public_url(config.base_url), "phase": phase.model_dump(),
            "configured_context_length": config.context_length}


def code_hashes() -> dict:
    return {**fingerprint(), "test/measure_concept.py": history.digest(Path(__file__).read_bytes())}


def prepare(study: Path, config_path=DEFAULT_CONFIG, *, evaluator: str, snapshot=model_snapshot) -> Path:
    study = Path(study)
    config = load_backend(config_path)
    public = conditions(config)
    materials = json.loads(MATERIAL.read_text(encoding="utf-8"))
    if materials["status"] != "human_approved_2026-10-27":
        raise run.RunError("The U13 gold materials require human approval before prepare.")
    cases = materials["cases"]
    if len(cases) != 8 or len({case["id"] for case in cases}) != 8:
        raise run.RunError("U13 expects eight distinct approved cases.")
    observation = snapshot(config)
    verify_state(observation, config.phase("concept").model, config.context_length)
    # パース・準備は保存前に済ませる。実行中に原資料を読み直さない。
    texts = {}
    for case in cases:
        parsed = Concept.model_validate(case["concept"])
        text = concept.render_concept(parsed)
        concept.parse_concept(text)
        if not case["input"].strip():
            raise run.RunError("U13 inputs must not be empty.")
        texts[case["id"]] = text
    prepared = concept.prepare_concept(cases[0]["input"], config)
    trials = [{"id": f"{index:02d}-{case['id']}-r{repeat}", "case": case["id"], "repeat": repeat}
              for index, (case, repeat) in enumerate(((case, repeat) for repeat in (1, 2) for case in cases), 1)]
    study.mkdir(parents=True)  # 既存studyへ上書きしない。
    materials_path = study / "materials.json"
    materials_path.write_bytes(MATERIAL.read_bytes())
    inputs = {}
    for spec in trials:
        case = next(case for case in cases if case["id"] == spec["case"])
        folder = study / spec["id"]
        folder.mkdir()
        (folder / run.INPUT).write_text(case["input"], encoding="utf-8")
        (folder / run.CONCEPT).write_text(texts[spec["case"]], encoding="utf-8")
        inputs[spec["id"]] = {name: history.digest((folder / name).read_bytes())
                              for name in (run.INPUT, run.CONCEPT)}
    save(study / "plan.json", {
        "schema_version": 1, "created_at": history.now(), "evaluator": evaluator,
        "approval": "User approved gold cases and 16 calls on 2026-10-27",
        "conditions": public, "runtime": runtime_versions(), "code": code_hashes(),
        "materials_sha256": history.digest(materials_path.read_bytes()), "inputs": inputs,
        "verify_prompt_sha256": history.text_hash(prepared.verify_system),
        "observed_before_sampling": observation, "trials": trials,
        "scoring": "Human cause-level TP/FP/FN mapping; failures and unconfirmed results are not zero findings",
    })
    save(study / "results.json", {"plan_sha256": history.digest((study / "plan.json").read_bytes()), "trials": []})
    return study


def execute(study: Path, config_path=DEFAULT_CONFIG, *, gateway_factory=OpenAICompatibleGateway,
            snapshot=model_snapshot, timeout=1800) -> Path:
    study = Path(study)
    config = load_backend(config_path)
    plan = json.loads((study / "plan.json").read_text(encoding="utf-8"))
    results = json.loads((study / "results.json").read_text(encoding="utf-8"))
    if history.digest((study / "plan.json").read_bytes()) != results["plan_sha256"]:
        raise run.RunError("U13 fixed plan changed.")
    if conditions(config) != plan["conditions"] or code_hashes() != plan["code"]:
        raise run.RunError("U13 conditions/code changed after plan freeze.")
    if history.digest((study / "materials.json").read_bytes()) != plan["materials_sha256"]:
        raise run.RunError("U13 materials changed after plan freeze.")
    for spec in plan["trials"]:
        for name, fingerprint in plan["inputs"][spec["id"]].items():
            if history.digest((study / spec["id"] / name).read_bytes()) != fingerprint:
                raise run.RunError("U13 input artifacts changed after plan freeze.")
    for previous in results["trials"]:
        for name, fingerprint in previous.get("outputs", {}).items():
            if history.digest((study / previous["id"] / name).read_bytes()) != fingerprint:
                raise run.RunError("U13 saved results changed; no implicit resampling.")
    seen = {trial["id"] for trial in results["trials"]}
    for spec in plan["trials"]:
        if spec["id"] in seen:
            continue  # 失敗・runningを含め、試行は上書き・再試行しない。
        if code_hashes() != plan["code"]:
            raise run.RunError("U13 code changed during sampling.")
        folder = study / spec["id"]
        idea, input_hash = history.read_source(folder / run.INPUT)
        text, concept_hash = history.read_source(folder / run.CONCEPT)
        concept.parse_concept(text)
        prepared = concept.prepare_concept(idea, config)
        if history.text_hash(prepared.verify_system) != plan["verify_prompt_sha256"]:
            raise run.RunError("U13 verification prompt changed during sampling.")
        before = snapshot(config)
        verify_state(before, config.phase("concept").model, config.context_length)
        trial = {**spec, "status": "running", "started_at": history.now(), "before": before}
        results["trials"].append(trial)
        save(study / "results.json", results)
        print(f"[U13] {spec['id']}", flush=True)
        started = perf_counter()
        gateway = None

        def factory(**kwargs):
            nonlocal gateway
            gateway = gateway_factory(**kwargs)
            return gateway

        try:
            with history.Operation(folder, "concept_verify_evaluation", config=config, new=True,
                                   inputs={run.INPUT: input_hash, run.CONCEPT: concept_hash},
                                   prompts={"prompts/concept/verify.md": prepared.verify_system},
                                   request_bodies={"concept_verify": prepared.body}) as operation:
                operation.step = "concept_verify"
                concept.verify_concept(folder, config, timeout=timeout, gateway_factory=factory, prepared=prepared)
            trial["status"] = "success"
        except Exception as error:
            trial.update(status="error", error_type=type(error).__name__,
                         error_code=getattr(gateway, "last_error_code", None) or "operation_failed")
            response = getattr(gateway, "last_response", None)
            if response is not None and response.choices:
                raw = response.choices[0].message.content
                if isinstance(raw, str):
                    (folder / "verify_raw.txt").write_text(raw, encoding="utf-8")
        except BaseException as error:
            trial.update(status="interrupted", error_type=type(error).__name__)
            raise
        finally:
            trial["wall_seconds"] = perf_counter() - started
            trial["call_id"] = getattr(gateway, "last_call_id", None)
            trial["after"] = snapshot(config)
            trial["outputs"] = {p.relative_to(folder).as_posix(): history.digest(p.read_bytes())
                                for p in folder.rglob("*") if p.is_file()
                                and p.name not in (run.INPUT, run.CONCEPT)}
            save(study / "results.json", results)
        try:
            verify_state(trial["after"], config.phase("concept").model, config.context_length)
        except run.RunError:
            trial["observation_status"] = "error"
            save(study / "results.json", results)
            raise
    write_review(study)
    return study


def write_review(study: Path) -> None:
    materials = json.loads((study / "materials.json").read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in materials["cases"]}
    results = json.loads((study / "results.json").read_text(encoding="utf-8"))
    lines = ["# U13 人手照合", "", "状態: 未評価。モデル出力の有無だけでTP/FP/FNを確定しない。", "",
             "[固定計画](plan.json) / [原入力・Concept・正解](materials.json) / [台帳](results.json)", "",
             "各試行で原入力・Concept・findingsを読み、正解原因と指摘を対応付けてください。"
             "同じ原因は重複加算せず、別分類でも妥当な説明なら理由を記録します。正常例への誤検出、"
             "異常例の見逃し、新規妥当指摘、形式/API失敗を分けてください。", "",
             "| 試行 | 正解候補 | 実行状態 | 指摘数 | 人手TP/FP/FN・根拠 |", "|---|---|---|---|---|"]
    for trial in results["trials"]:
        expected = cases[trial["case"]]["expected"]
        path = study / trial["id"] / run.CONCEPT_REPORT
        count = len(json.loads(path.read_text(encoding="utf-8"))["findings"]) if path.is_file() else "未測定"
        label = expected["kind"] if expected["abnormal"] else "正常"
        lines.append(f"| [{trial['id']}]({trial['id']}/) | {label} | {trial['status']} | {count} | 未評価 |")
    path = study / "human_review.md"
    if path.exists():
        return
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
