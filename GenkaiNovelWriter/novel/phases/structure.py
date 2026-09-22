"""Structure フェーズ(SPEC.md「Structure」D13〜D16)。

02_concept.md を読み、JSON Schema 制約付き生成で 03_plot.json を作る(D38)。
スキーマ違反は最大2回まで再生成し、すべて失敗したら生出力を残して停止する。修復はしない(D24)。
"""

from pathlib import Path

from pydantic import ValidationError

from novel import run
from novel.phases.concept import load_concept
from novel.schema import Plot
from util.config import PROJECT_ROOT, BackendConfig, load_thinking_options, thinking_body
from util.gateway import OpenAICompatibleGateway, create_message

SYSTEM_PROMPT = PROJECT_ROOT / "prompts/structure/system.md"
RETRIES = 2


class StructureError(RuntimeError):
    """規定回数を試してもスキーマに適合した Plot が得られなかった。"""


class PlotFormatError(ValueError):
    """03_plot.json が Plot スキーマになっていない。"""


def load_plot(directory: Path | str) -> Plot:
    """03_plot.json を読む。手で壊されていれば、修復せずここで止まる(D24)。"""
    path = Path(directory) / run.PLOT
    if not path.is_file():
        raise PlotFormatError(f"{run.PLOT} not found. Run 'stage structure' first.")
    try:
        return Plot.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as error:
        locations = [".".join(map(str, item["loc"])) for item in error.errors()]
        raise PlotFormatError(f"{run.PLOT} does not match the Plot schema: " + ", ".join(locations)) from None


def save_plot(directory: Path | str, plot: Plot) -> Path:
    path = Path(directory) / run.PLOT
    path.write_text(plot.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def run_structure(directory: Path | str, config: BackendConfig, *, backend: str = "local",
                  thinking_options=None, timeout: float = 600, retries: int = RETRIES,
                  gateway_factory=OpenAICompatibleGateway) -> Plot:
    """02_concept.md から 03_plot.json を作る。"""
    directory = run.open_run(directory)
    concept = load_concept(directory)
    concept_text = (directory / run.CONCEPT).read_text(encoding="utf-8")
    phase = config.phase("structure")
    body = thinking_body(load_thinking_options(thinking_options), phase)
    system = SYSTEM_PROMPT.read_text(encoding="utf-8")

    plot = None
    raw = ""
    with gateway_factory(
        model=phase.model, base_url=config.base_url, api_key=config.api_key.get_secret_value(),
        phase="structure", backend=backend, thinking=phase.thinking, request_body=body,
        log_path=directory / run.CALLS, timeout=timeout,
    ) as gateway:
        for _ in range(retries + 1):
            try:
                plot = gateway.parse(create_message(system=system, user=concept_text), Plot)
                break
            except ValidationError:
                raw = _last_text(gateway)
    if plot is None:
        (directory / run.PLOT_RAW).write_text(raw, encoding="utf-8")
        raise StructureError(
            f"Plot did not match the schema in {retries + 1} attempts. "
            f"The last raw output is in {run.PLOT_RAW}."
        )

    # 指定要素は Concept の値をそのまま転記し、生成結果に上書きする(SPEC.md「Structure」)。
    plot = plot.model_copy(update={"constraints": list(concept.constraints),
                                   "events": list(concept.events)})
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
