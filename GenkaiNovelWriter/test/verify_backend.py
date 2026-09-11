"""User-run local M1 probes. Observations are not automatic U2/U4 acceptance."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import baseline, create_output_dir
from test.plot_schema import Plot
from util.config import DEFAULT_CONFIG, ConfigError, load_backend, load_thinking_options, thinking_body
from util.gateway import OpenAICompatibleGateway, create_message

THINK_TAG = re.compile(r"</?(?:think|thinking|analysis|reasoning)(?:\s[^>]*)?>", re.I)


def save_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def model_snapshot(config):
    """Read model state with the native API; generation still uses the single gateway."""
    import httpx
    url = urlsplit(config.base_url)
    endpoint = urlunsplit((url.scheme, url.netloc, "/api/v1/models", "", ""))
    try:
        with httpx.Client(timeout=15, trust_env=False) as client:
            response = client.get(endpoint, headers={"Authorization": "Bearer " + config.api_key.get_secret_value()})
            response.raise_for_status()
            data = response.json()
        models = data["models"]
        return {"status": "observed", "models": [
            {key: item.get(key) for key in ("key", "type", "quantization", "loaded_instances")}
            for item in models
        ]}
    except Exception as error:
        return {"status": "unavailable", "error_type": type(error).__name__}


def memory_snapshot():
    """Windows host/process/GPU counters, not an estimate from model file sizes."""
    if sys.platform != "win32":
        return {"status": "unavailable", "reason": "Record RAM/VRAM manually on this OS."}
    command = (
        "$ErrorActionPreference='Stop'; "
        "$os=Get-CimInstance Win32_OperatingSystem; "
        "$processes=@(Get-Process | Where-Object { $_.ProcessName -match 'lm.?studio|llmster|llama' } "
        "| Select-Object ProcessName,Id,WorkingSet64,PrivateMemorySize64); "
        "$gpu=@(Get-CimInstance Win32_PerfFormattedData_GPUPerformanceCounters_GPUAdapterMemory "
        "-ErrorAction SilentlyContinue | Select-Object Name,DedicatedUsage,SharedUsage); "
        "@{total_ram_kib=$os.TotalVisibleMemorySize;free_ram_kib=$os.FreePhysicalMemory;"
        "processes=$processes;gpu_adapters=$gpu} | ConvertTo-Json -Depth 5 -Compress"
    )
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                                capture_output=True, text=True, timeout=20, check=True,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        return {"status": "observed", **json.loads(result.stdout)}
    except Exception as error:
        return {"status": "unavailable", "error_type": type(error).__name__}


def thinking_observation(response):
    message = response.choices[0].message
    content = message.content or ""
    extra = message.model_dump()
    reasoning = {key: extra[key] for key in ("reasoning", "reasoning_content", "reasoning_details")
                 if extra.get(key)}
    return {"content": content, "content_has_thinking_tag": bool(THINK_TAG.search(content)),
            "separate_reasoning": reasoning, "has_separate_reasoning": bool(reasoning),
            "finish_reason": response.choices[0].finish_reason}


def run_probes(config, options, directory, idea, checks, *, timeout=600,
               gateway_factory=OpenAICompatibleGateway, snapshot=model_snapshot, memory=memory_snapshot):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    report = {"backend": "local", "quality_evaluated": False,
              "U2": {"status": "not_run", "observations": []},
              "U3": {"status": "not_run", "attempts": 0, "valid": 0, "schema_violations": 0, "api_errors": 0},
              "U4": {"status": "not_run", "observations": []},
              "U7": {"status": "not_run", "measurements": []}}
    save_json(directory / "plot_schema.json", Plot.model_json_schema())

    def persist():
        save_json(directory / "verification.json", report)

    def invoke(label, phase, prompt, schema=None, require_thinking=False):
        try:
            body = thinking_body(options, phase)
        except ConfigError:
            if require_thinking:
                return {"status": "not_run", "reason": "thinking options missing or invalid"}, None
            body = {}
        with gateway_factory(model=phase.model, base_url=config.base_url,
                             api_key=config.api_key.get_secret_value(), phase=label, backend="local",
                             thinking=phase.thinking if body else None, request_body=body,
                             log_path=directory / "calls.jsonl", timeout=timeout) as gateway:
            try:
                response = gateway.chat_response(create_message(
                    system="指示に回答してください。", user=prompt), response_schema=schema)
                observation = thinking_observation(response)
                save_json(directory / f"{label}.json", observation)
                return {"status": "observed", "artifact": f"{label}.json",
                        "thinking_request_supplied": bool(body),
                        "content_has_thinking_tag": observation["content_has_thinking_tag"],
                        "has_separate_reasoning": observation["has_separate_reasoning"]}, response
            except Exception as error:
                response = gateway.last_response
                if response is not None and response.choices:
                    save_json(directory / f"{label}.json", thinking_observation(response))
                return {"status": "error", "error_type": type(error).__name__}, None

    persist()
    if "thinking" in checks:
        for role in ("structure", "writing"):
            for enabled in (True, False):
                phase = config.phase(role).model_copy(update={"thinking": enabled})
                mode = "on" if enabled else "off"
                item, _ = invoke(f"thinking-{role}-{mode}", phase,
                                 "赤玉3個、青玉2個から同時に2個取り出すとき、同じ色になる確率を求めてください。",
                                 require_thinking=True)
                report["U2"]["observations"].append({"model": phase.model, "thinking": enabled, **item})
                persist()
        report["U2"]["status"] = "needs_review"

    if "schema" in checks:
        phase = config.phase("structure")
        for index in range(1, 11):
            label = f"schema-{index:02d}"
            item, response = invoke(label, phase,
                                    "次のアイデアを1話完結のPlotとしてJSON Schemaに従って構造化してください。"
                                    "指定要素は入力の順序を守ってS1から列挙してください。\n" + idea,
                                    schema=Plot.model_json_schema())
            report["U3"]["attempts"] += 1
            if response is None:
                report["U3"]["api_errors"] += 1
            else:
                try:
                    Plot.model_validate_json(response.choices[0].message.content)
                    report["U3"]["valid"] += 1
                except ValueError:
                    report["U3"]["schema_violations"] += 1
            persist()
        report["U3"]["status"] = "measured"

    if "switching" in checks:
        report["U4"]["before"] = {"models": snapshot(config), "memory": memory()}
        for index, role in enumerate(("structure", "writing", "structure"), 1):
            phase = config.phase(role)
            item, _ = invoke(f"switch-{index}", phase, "短い日本語の挨拶を一つ書いてください。")
            report["U4"]["observations"].append({
                "model": phase.model, **item, "models_after": snapshot(config), "memory_after": memory(),
            })
            persist()
        report["U4"]["status"] = "needs_review"

    if "speed" in checks:
        for role in ("structure", "writing"):
            phase = config.phase(role)
            item, _ = invoke(f"speed-{role}", phase, "雨の日に二人が出会う場面を日本語で800字程度書いてください。")
            report["U7"]["measurements"].append({"model": phase.model, **item})
            persist()
        report["U7"]["status"] = "see_calls_jsonl"
    persist()
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="M1 local backend verification (no automatic SPEC updates)")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--thinking-options", type=Path)
    parser.add_argument("--input", type=Path, default=PROJECT_ROOT / "prompts/tests/concrete_01.txt")
    parser.add_argument("--checks", nargs="+", choices=("thinking", "schema", "switching", "speed"),
                        default=["thinking", "schema", "switching", "speed"])
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--baseline-suite", action="store_true", help="Also generate both inputs twice")
    args = parser.parse_args(argv)
    try:
        config = load_backend(args.config, "local")
        options = load_thinking_options(args.thinking_options)
        idea = args.input.read_text(encoding="utf-8")
        directory = create_output_dir(PROJECT_ROOT / "creations", "verify-")
        (directory / "00_input.txt").write_text(idea, encoding="utf-8")
        report = run_probes(config, options, directory, idea, args.checks, timeout=args.timeout)
        if args.baseline_suite:
            report["baselines"] = []
            for name in ("concrete_01.txt", "vague_01.txt"):
                for index in range(2):
                    try:
                        result = baseline(PROJECT_ROOT / "prompts/tests" / name, config_path=args.config,
                                          thinking_options=args.thinking_options, timeout=args.timeout)
                        item = {"input": name, "repeat": index + 1, "directory": str(result), "status": "generated"}
                    except Exception as error:
                        item = {"input": name, "repeat": index + 1, "status": "error", "error_type": type(error).__name__}
                    report["baselines"].append(item)
                    save_json(directory / "verification.json", report)
        print(directory)
        print("U2/U4 は人手確認が必要です。SPEC.md は実測結果の確認後に更新してください。")
        failed = any(item.get("status") in ("error", "not_run")
                     for key in ("U2", "U4") for item in report[key]["observations"])
        failed = failed or bool(report["U3"]["api_errors"] or report["U3"]["schema_violations"])
        failed = failed or any(item["status"] == "error" for item in report.get("baselines", []))
        failed = failed or any(item["status"] == "error" for item in report["U7"]["measurements"])
        return 1 if failed else 0
    except Exception as error:
        print(str(error) if isinstance(error, ConfigError) else type(error).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
