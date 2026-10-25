"""M5の固定条件比較。prepareで計画を保存し、executeで未実行の8試行を採取する。

生成物の編集・stage再実行は行わない。失敗を成功例で置き換えず台帳へ残す。
採点・有効性・許容速度は人手で記入する。
"""

import argparse
import contextlib
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import baseline, run_pipeline
from novel import run
from test.verify_backend import model_snapshot
from util.config import DEFAULT_CONFIG, load_backend
from util.gateway import OpenAICompatibleGateway
from util.models import prepare_local_model

ORDER = [("concrete_01.txt", "baseline", 1), ("concrete_01.txt", "pipeline", 1),
         ("vague_01.txt", "baseline", 1), ("vague_01.txt", "pipeline", 1),
         ("vague_01.txt", "pipeline", 2), ("vague_01.txt", "baseline", 2),
         ("concrete_01.txt", "pipeline", 2), ("concrete_01.txt", "baseline", 2)]


def save(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def public_config(config) -> dict:
    if urlsplit(config.base_url).hostname not in ("localhost", "127.0.0.1", "::1"):
        raise run.RunError("The M5 comparison requires a loopback LM Studio server.")
    return {"backend": "local", "base_url": config.base_url,
            "context_length": config.context_length,
            "phases": {name: config.phase(name).model_dump()
                       for name in ("concept", "structure", "writing", "baseline")}}


def fingerprint() -> dict:
    files = [PROJECT_ROOT / "main.py", Path(__file__).resolve(),
             PROJECT_ROOT / "test/verify_backend.py"]
    for folder, pattern in (("novel", "*.py"), ("util", "*.py"), ("prompts", "*.md"),
                            ("prompts/tests", "*.txt")):
        files.extend((PROJECT_ROOT / folder).rglob(pattern))
    return {p.relative_to(PROJECT_ROOT).as_posix(): digest(p) for p in sorted(set(files))}


def runtime_versions() -> dict:
    return {"python": sys.version, "platform": platform.platform(),
            "dependencies": {name: importlib.metadata.version(name)
                             for name in ("pydantic", "openai", "httpx")}}


def loaded(snapshot: dict) -> list[dict]:
    if snapshot.get("status") != "observed":
        raise run.RunError("LM Studio model state is unavailable.")
    return [{"key": model["key"], "quantization": model["quantization"], **instance}
            for model in snapshot["models"] if model["type"] == "llm"
            for instance in model["loaded_instances"]]


def unload_all(config, snapshot=model_snapshot, command=subprocess.run) -> None:
    for instance in loaded(snapshot(config)):
        command(["lms", "unload", instance["id"]], check=True, capture_output=True,
                timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if loaded(snapshot(config)):
        raise run.RunError("Cannot establish an empty model state for the comparison trial.")


def prepare(study: Path, config_path: Path, evaluator: str, *, snapshot=model_snapshot,
            command=subprocess.run) -> Path:
    """実ロード条件を事前観測し、生成を始めず計画と空の台帳を確定する。"""
    config = load_backend(config_path)
    conditions = public_config(config)
    if any(phase["thinking"] is not None for phase in conditions["phases"].values()):
        raise run.RunError("M5 comparison requires thinking=null (D37).")
    if not evaluator.strip():
        raise run.RunError("A human evaluator must be recorded before generation.")
    study = Path(study).resolve()
    study.mkdir(parents=True, exist_ok=False)
    observations = []
    save(study / "preflight.json", {"status": "running", "observations": observations})
    try:
        for model in dict.fromkeys(p["model"] for p in conditions["phases"].values()):
            unload_all(config, snapshot, command)
            command(["lms", "load", model, "--context-length", str(config.context_length), "--yes"],
                    check=True, capture_output=True, timeout=600,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            state = snapshot(config)
            instances = loaded(state)
            if len(instances) != 1 or model not in (instances[0]["key"], instances[0]["id"]):
                raise run.RunError("Preflight loaded model does not match the planned identifier.")
            if instances[0]["config"]["context_length"] != config.context_length:
                raise run.RunError("Preflight actual context length does not match the plan.")
            observations.append({"model": model, "snapshot": state})
            save(study / "preflight.json", {"status": "running", "observations": observations})
        unload_all(config, snapshot, command)
    except BaseException as error:
        save(study / "preflight.json", {"status": "error", "error_type": type(error).__name__,
                                        "observations": observations})
        raise
    save(study / "preflight.json", {"status": "success", "observations": observations})
    plan = {"created_utc": datetime.now(timezone.utc).isoformat(), "evaluator": evaluator,
            "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"],
                                                   cwd=PROJECT_ROOT, text=True).strip(),
            "lms_version": command(["lms", "--version"], check=True, capture_output=True,
                                   text=True, timeout=30,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.strip(),
            "runtime": runtime_versions(), "config": conditions, "fingerprint": fingerprint(),
            "preflight_sha256": digest(study / "preflight.json"), "timeout": 1800,
            "model_start_state": "empty before each trial; inter-trial reset excluded from wall time",
            "timing": "wall time through final artifact save, including switching and observation; observation and preparation also reported separately",
            "U13": "independent detection performance unverified; human checks original input",
            "U15": "immutable study conditions, per-trial artifacts and hashes; no stage or write reruns",
            "limitations": ["Gemma Q3_K_M: not a Q4 speed/quality measurement",
                            "OS/file cache is not cleared by model unload; server sampling defaults are not fixed by the client",
                            "CPU/GPU expert placement is not fully reported by the model API",
                            "JIT load time remains inside LLM request time; model preparation measures state queries and explicit unload",
                            "Two repeats per input/method do not establish general superiority"],
            "provisional_criteria": {"elements_and_order": "zero missing elements/order violations",
                                     "genre_tone": "human judges fit", "consistency": "zero contradictions",
                                     "physical": "zero obvious failures on reading", "length": "warning only below 600 chars per scene",
                                     "foreshadowing": "observation only", "originality": "observation only"},
            "trials": [{"id": f"{number:02d}-{Path(name).stem}-{method}-{repeat}",
                        "input": f"prompts/tests/{name}", "method": method, "repeat": repeat}
                       for number, (name, method, repeat) in enumerate(ORDER, 1)]}
    save(study / "plan.json", plan)
    save(study / "results.json", {"plan_sha256": digest(study / "plan.json"), "trials": []})
    write_review(study, plan, {"trials": []})
    return study


def validate_plan(study: Path, config) -> tuple[dict, dict]:
    plan, results = read(study / "plan.json"), read(study / "results.json")
    if digest(study / "plan.json") != results["plan_sha256"]:
        raise run.RunError("Comparison plan changed after it was recorded.")
    if public_config(config) != plan["config"] or fingerprint() != plan["fingerprint"]:
        raise run.RunError("Comparison configuration, input, prompt or code changed; create a new study.")
    if runtime_versions() != plan["runtime"] or digest(study / "preflight.json") != plan["preflight_sha256"]:
        raise run.RunError("Comparison runtime or preflight record changed.")
    for trial in results["trials"]:
        for name, expected in trial.get("artifact_hashes", {}).items():
            path = study / trial["directory"] / name
            if not path.is_file() or digest(path) != expected:
                raise run.RunError("A saved comparison artifact changed; generation stopped.")
    return plan, results


def write_review(study: Path, plan: dict, results: dict) -> None:
    """機械的な採取状況と別ファイルの人手記入欄。記入済み評価は上書きしない。"""
    rows = ["# M5 採取状況", "", f"評価者: {plan['evaluator']}", "",
            "| 試行 | 状態 | 経過秒 | 観測秒 | モデル準備秒 | LLM呼び出し秒 | 字数 | 本文 |",
            "|---|---|---|---|---|---|---|---|"]
    for trial in results["trials"]:
        text = "baseline.md" if trial["method"] == "baseline" else run.DRAFT
        rows.append(f"| {trial['id']} | {trial['status']} | {trial.get('wall_seconds', '')} | "
                    f"{trial.get('observation_seconds', '')} | {trial.get('model_prepare_seconds', '')} | "
                    f"{trial.get('llm_request_seconds', '')} | {trial.get('chars', '')} | "
                    f"[本文]({trial['directory']}/{text}) |")
    rows += ["", "経過時間はモデル切替・生成・保存を含む。観測APIの時間も含むため、観測秒を別記する。",
             "モデル準備秒は経過時間・LLM呼び出し秒の内数。LLM呼び出し秒との単純加算はしない。",
             "失敗・未実行は品質不合格または問題なしとして採点しない。", ""]
    (study / "status.md").write_text("\n".join(rows), encoding="utf-8")
    review = study / "human_review.md"
    if review.exists():
        return
    lines = ["# M5 人手比較", "", f"評価者: {plan['evaluator']}", "評価状態: 未評価", "",
             "[計画](plan.json)・[採取状況と本文](status.md)・原入力を参照して記入してください。",
             "LLMのコメントやConcept照合レポートを人手判定の代わりにしません。",
             "", "## 各試行の評価", "",
             "| 試行 | 要素・順序 | ジャンル・トーン | 設定矛盾 | 物理的破綻 | 伏線放置・非陳腐性 | 本文の引用・根拠 |",
             "|---|---|---|---|---|---|---|"]
    lines += [f"| {trial['id']} |  |  |  |  |  |  |" for trial in plan["trials"]]
    lines += ["", "## 原入力との照合", "",
              "[具体入力](../../prompts/tests/concrete_01.txt) / [曖昧入力](../../prompts/tests/vague_01.txt)",
              "", "- 指定の欠落・意味改変・順序と該当試行・引用: ",
              "- Concept / Plot / 本文のどこで変わったか: ", "",
              "## 入力別の比較・ばらつき", "",
              "| 入力 | 一発生成2回の結果・ばらつき | 一括生成2回の結果・ばらつき | 優位・同等・判断保留と根拠 |",
              "|---|---|---|---|", "| concrete_01 |  |  |  |", "| vague_01 |  |  |  |", "",
              "## 最終判断", "", "- U1（有効・無効・保留と根拠）: ",
              "- U7（許容できる速度か、許容時間と根拠）: ",
              "- U8（最終基準・暫定基準からの変更と理由）: ",
              "- M6へ進むか、生成方針を再検討するか: ",
              "- 条件差・少数試行・Concept照合未検証などの限界: ", ""]
    review.write_text("\n".join(lines), encoding="utf-8")


def execute(study: Path, config_path: Path, *, snapshot=model_snapshot,
            reset=unload_all, gateway_class=OpenAICompatibleGateway) -> dict:
    study = Path(study).resolve()
    config = load_backend(config_path)
    plan, results = validate_plan(study, config)
    for specification in plan["trials"]:
        # running/errorも再利用しない。失敗した計画の再試行は別の計画として明記する。
        if any(t["id"] == specification["id"] for t in results["trials"]):
            continue
        validate_plan(study, load_backend(config_path))
        reset(config)
        folder = study / specification["id"]
        folder.mkdir()
        trial = {**specification, "directory": folder.name, "status": "running",
                 "started_utc": datetime.now(timezone.utc).isoformat()}
        results["trials"].append(trial)
        save(study / "results.json", results)
        observations = []
        observation_seconds = 0.0
        prepare_seconds = 0.0

        def measured_prepare(*args, **kwargs):
            nonlocal prepare_seconds
            preparing = perf_counter()
            try:
                return prepare_local_model(*args, **kwargs)
            finally:
                prepare_seconds += perf_counter() - preparing

        class ObservedGateway(gateway_class):
            def _request(self, *args, **kwargs):
                nonlocal observation_seconds
                try:
                    return super()._request(*args, **kwargs)
                finally:
                    observing = perf_counter()
                    state = snapshot(config)
                    observations.append({"phase": self.phase, "scene": self.scene_index,
                                         "target": self.model, "snapshot": state})
                    save(folder / "models.json", {"observations": observations})
                    observation_seconds += perf_counter() - observing

        print(f"Start: {trial['id']}", flush=True)
        started = perf_counter()
        directory = None
        try:
            with (folder / "stdout.log").open("w", encoding="utf-8") as stdout, \
                    (folder / "stderr.log").open("w", encoding="utf-8") as stderr, \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr), \
                    patch("util.gateway.prepare_local_model", side_effect=measured_prepare):
                function = baseline if trial["method"] == "baseline" else run_pipeline
                directory = function(PROJECT_ROOT / trial["input"], config_path=config_path,
                                     output_root=folder, timeout=plan["timeout"],
                                     gateway_factory=ObservedGateway)
            expected_quantization = {o["model"]: loaded(o["snapshot"])[0]["quantization"]
                                     for o in read(study / "preflight.json")["observations"]}
            for observation in observations:
                instances = loaded(observation["snapshot"])
                target = observation["target"]
                if (len(instances) != 1 or target not in (instances[0]["key"], instances[0]["id"])
                        or instances[0]["config"]["context_length"] != config.context_length
                        or instances[0]["quantization"] != expected_quantization[target]):
                    raise run.RunError("Actual model state changed from the recorded preflight conditions.")
            # 実行途中の設定・入力・プロンプト・コード変更も成功試行として採用しない。
            validate_plan(study, load_backend(config_path))
            trial["status"] = "success"
        except Exception as error:
            trial["status"] = "error"
            trial["error_type"] = type(error).__name__
        finally:
            trial["wall_seconds"] = perf_counter() - started
            trial["observation_seconds"] = observation_seconds
            trial["model_prepare_seconds"] = prepare_seconds
            if directory is None:
                directories = [p for p in folder.iterdir() if p.is_dir() and (p / run.INPUT).is_file()]
                directory = directories[0] if len(directories) == 1 else None
            if directory is not None:
                trial["artifact_directory"] = directory.relative_to(study).as_posix()
                # status.mdの本文リンクには実際の実行サブディレクトリを使う。
                trial["directory"] = trial["artifact_directory"]
                calls = directory / run.CALLS
                records = [json.loads(line) for line in calls.read_text(encoding="utf-8").splitlines()] if calls.exists() else []
                trial["llm_request_seconds"] = sum(r["duration_seconds"] for r in records)
                text = directory / ("baseline.md" if trial["method"] == "baseline" else run.DRAFT)
                if text.is_file():
                    trial["chars"] = sum(not c.isspace() for c in text.read_text(encoding="utf-8"))
                trial["artifact_hashes"] = {p.relative_to(directory).as_posix(): digest(p)
                                              for p in directory.rglob("*") if p.is_file()}
            save(study / "results.json", results)
            write_review(study, plan, results)
        print(f"Done: {trial['id']} {trial['status']}", flush=True)
        if trial["status"] != "success":
            break
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "execute"))
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--evaluator", default="ユーザ")
    args = parser.parse_args(argv)
    try:
        if args.action == "prepare":
            prepare(args.study, args.config, args.evaluator)
        else:
            result = execute(args.study, args.config)
            return 0 if len(result["trials"]) == len(ORDER) and all(t["status"] == "success" for t in result["trials"]) else 1
    except Exception as error:
        print(f"{type(error).__name__}: comparison stopped; inspect study records.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
