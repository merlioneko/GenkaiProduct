"""Structure フェーズ(SPEC.md「Structure」D13〜D16)。

02_concept.md を読み、JSON Schema 制約付き生成で 03_plot.json を作る(D38)。
スキーマ違反は最大2回まで再生成し、すべて失敗したら生出力を残して停止する。修復はしない(D24)。
"""

from pathlib import Path
from dataclasses import dataclass

from pydantic import ValidationError

from novel import run
from novel.phases.concept import parse_concept, ConceptFormatError
from novel.history import read_source, record_output
from novel.schema import Plot
from util.config import PROJECT_ROOT, BackendConfig, PhaseConfig, load_thinking_options, thinking_body
from util.gateway import OpenAICompatibleGateway, create_messages

SYSTEM_PROMPT = PROJECT_ROOT / "prompts/structure/system.md"
RETRIES = 2


class StructureError(RuntimeError):
    """規定回数を試してもスキーマに適合した Plot が得られなかった。"""


class PlotFormatError(ValueError):
    """03_plot.json が Plot スキーマになっていない。"""


@dataclass(frozen=True)
class StructurePreparation:
    phase: PhaseConfig
    body: dict
    system: str


def prepare_structure(config: BackendConfig, thinking_options=None) -> StructurePreparation:
    phase = config.phase("structure")
    return StructurePreparation(phase, thinking_body(load_thinking_options(thinking_options), phase),
                                SYSTEM_PROMPT.read_text(encoding="utf-8"))


def prepare_input(directory: Path):
    path = directory / run.CONCEPT
    if not path.is_file():
        raise ConceptFormatError(f"{run.CONCEPT} not found. Run 'stage concept' first.")
    text, fingerprint = read_source(path)
    return parse_concept(text), text, {run.CONCEPT: fingerprint}


def load_plot(directory: Path | str, *, fingerprints=None) -> Plot:
    """03_plot.json を読む。手で壊されていれば、修復せずここで止まる(D24)。"""
    path = Path(directory) / run.PLOT
    if not path.is_file():
        raise PlotFormatError(f"{run.PLOT} not found. Run 'stage structure' first.")
    try:
        text, fingerprint = read_source(path)
        plot = Plot.model_validate_json(text)
        if fingerprints is not None:
            fingerprints[run.PLOT] = fingerprint
        return plot
    except ValidationError as error:
        locations = [".".join(map(str, item["loc"])) for item in error.errors()]
        raise PlotFormatError(f"{run.PLOT} does not match the Plot schema: " + ", ".join(locations)) from None


def save_plot(directory: Path | str, plot: Plot) -> Path:
    path = Path(directory) / run.PLOT
    path.write_text(plot.model_dump_json(indent=2) + "\n", encoding="utf-8")
    record_output(path)
    return path


def run_structure(directory: Path | str, config: BackendConfig, *, backend: str = "local",
                  thinking_options=None, timeout: float = 600, retries: int = RETRIES,
                  gateway_factory=OpenAICompatibleGateway, prepared=None, inputs=None) -> Plot:
    """02_concept.md から 03_plot.json を作る。"""
    directory = run.open_run(directory)
    concept, concept_text, _ = inputs if inputs is not None else prepare_input(directory)
    prepared = prepared or prepare_structure(config, thinking_options)
    phase, body, system = prepared.phase, prepared.body, prepared.system

    plot = None
    raw = ""
    with gateway_factory(
        model=phase.model, base_url=config.base_url, api_key=config.api_key.get_secret_value(),
        phase="structure", backend=backend, thinking=phase.thinking, request_body=body,
        log_path=directory / run.CALLS, timeout=timeout,
    ) as gateway:
        for _ in range(retries + 1):
            try:
                plot = gateway.parse(create_messages(system=system, user=concept_text), Plot)
                break
            except ValidationError:
                raw = _last_text(gateway)
    if plot is None:
        (directory / run.PLOT_RAW).write_text(raw, encoding="utf-8")
        record_output(directory / run.PLOT_RAW)
        raise StructureError(
            f"Plot did not match the schema in {retries + 1} attempts. "
            f"The last raw output is in {run.PLOT_RAW}."
        )

    # 指定要素は Concept の値をそのまま転記し、生成結果に上書きする(SPEC.md「Structure」)。
    plot = plot.model_copy(update={"constraints": list(concept.constraints),
                                   "events": list(concept.events)})
    if not concept.events:
        plot = plot.model_copy(update={"scenes": [scene.model_copy(update={"covers": []}) for scene in plot.scenes]})
    save_plot(directory, plot)
    return plot


def _last_text(gateway) -> str:
    """スキーマ違反時の生出力。取れなければ空文字。"""
    response = getattr(gateway, "last_response", None)
    choices = getattr(response, "choices", None)
    if not choices:
        return ""
    content = choices[0].message.content
    return content if isinstance(content, str) else ""
