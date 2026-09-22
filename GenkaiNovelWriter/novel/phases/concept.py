"""Concept フェーズ(SPEC.md「Concept」D8, D9)と 02_concept.md の読み書き。

ファイル形式は SPEC.md「02_concept.md フォーマット」の固定見出しだけを正とする。
LLM にもこの形式で書かせ、書かれたものをパースして Concept にする。逆向き(モデル → Markdown)も
決定的に行える。パースできない場合は修復せず停止する(D24)。人が直して再実行する。
"""

import json
from pathlib import Path

from novel import run
from novel.schema import Concept, ConceptReport
from util.config import PROJECT_ROOT, BackendConfig, load_thinking_options, thinking_body
from util.gateway import OpenAICompatibleGateway, create_message

SYSTEM_PROMPT = PROJECT_ROOT / "prompts/concept/system.md"
VERIFY_PROMPT = PROJECT_ROOT / "prompts/concept/verify.md"

# SPEC.md「02_concept.md フォーマット」の固定見出し。
CONSTRAINTS_HEADING = "# 制約"
EVENTS_HEADING = "# 出来事"
BODY_HEADING = "# 構想"


class ConceptFormatError(ValueError):
    """02_concept.md が固定見出しの形式になっていない。"""


def render_concept(concept: Concept) -> str:
    """Concept → 02_concept.md。parse_concept と往復できる形にする。"""
    lines = [CONSTRAINTS_HEADING]
    lines += [f"- {item}" for item in concept.constraints]
    lines += ["", EVENTS_HEADING]
    lines += [f"{number}. {item}" for number, item in enumerate(concept.events, 1)]
    lines += ["", BODY_HEADING, "", concept.body.strip(), ""]
    return "\n".join(lines)


def parse_concept(text: str) -> Concept:
    """02_concept.md → Concept。指定要素(制約・出来事)を抽出する。"""
    sections = _split_sections(text)
    return Concept(
        constraints=_parse_bullets(sections[CONSTRAINTS_HEADING]),
        events=_parse_numbered(sections[EVENTS_HEADING]),
        body=_parse_body(sections[BODY_HEADING]),
    )


def load_concept(directory: Path | str) -> Concept:
    """02_concept.md を読む。手で編集された内容がそのまま後段に渡る。"""
    path = Path(directory) / run.CONCEPT
    if not path.is_file():
        raise ConceptFormatError(f"{run.CONCEPT} not found. Run 'stage concept' first.")
    return parse_concept(path.read_text(encoding="utf-8"))


def run_concept(directory: Path | str, config: BackendConfig, *, backend: str = "local",
                thinking_options=None, timeout: float = 600,
                gateway_factory=OpenAICompatibleGateway) -> Concept:
    """00_input.txt から 02_concept.md を作る。

    生成結果はまず 02_concept.md に書き、そのあとパースする。形式が崩れていた場合、
    ファイルは残したままエラーで止める。人がその場で直して次の stage に進めるようにするため。
    """
    directory = run.open_run(directory)
    idea = run.read_input(directory)
    phase = config.phase("concept")
    body = thinking_body(load_thinking_options(thinking_options), phase)
    system = SYSTEM_PROMPT.read_text(encoding="utf-8")

    with gateway_factory(
        model=phase.model, base_url=config.base_url, api_key=config.api_key.get_secret_value(),
        phase="concept", backend=backend, thinking=phase.thinking, request_body=body,
        log_path=directory / run.CALLS, timeout=timeout,
    ) as gateway:
        text = gateway.text(create_message(system=system, user=idea))

    (directory / run.CONCEPT).write_text(text.strip() + "\n", encoding="utf-8")
    return parse_concept(text)


def verify_concept(directory: Path | str, config: BackendConfig, *, backend: str = "local",
                   thinking_options=None, timeout: float = 600,
                   gateway_factory=OpenAICompatibleGateway) -> ConceptReport:
    """00_input.txt と 02_concept.md を照合し、02_concept_report.json を書く。

    報告のみで処理は止めない(SPEC.md「Concept」)。照合には Concept と同じモデルを使う。
    """
    directory = run.open_run(directory)
    idea = run.read_input(directory)
    concept_text = (directory / run.CONCEPT).read_text(encoding="utf-8")
    phase = config.phase("concept")
    body = thinking_body(load_thinking_options(thinking_options), phase)
    system = VERIFY_PROMPT.read_text(encoding="utf-8")
    user = f"""# ユーザ入力

{idea}

# 生成された構想

{concept_text}"""

    with gateway_factory(
        model=phase.model, base_url=config.base_url, api_key=config.api_key.get_secret_value(),
        phase="concept_verify", backend=backend, thinking=phase.thinking, request_body=body,
        log_path=directory / run.CALLS, timeout=timeout,
    ) as gateway:
        report = gateway.parse(create_message(system=system, user=user), ConceptReport)

    (directory / run.CONCEPT_REPORT).write_text(
        json.dumps(report.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


# ---- パーサの内部 ----

def _split_sections(text: str) -> dict[str, list[str]]:
    """レベル1見出しで区切る。3つの見出しがこの順に1回ずつ現れることを求める。"""
    expected = [CONSTRAINTS_HEADING, EVENTS_HEADING, BODY_HEADING]
    sections: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        heading = line.strip()
        if heading.startswith("# "):
            if heading in sections:
                raise ConceptFormatError(f"Duplicated heading: {heading}")
            if heading not in expected:
                raise ConceptFormatError(f"Unexpected heading: {heading}")
            current = heading
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
        elif line.strip():
            raise ConceptFormatError(f"Text before the first heading: {line.strip()[:30]}")
    if list(sections) != expected:
        raise ConceptFormatError("02_concept.md must have 制約 / 出来事 / 構想 in this order.")
    return sections


def _parse_bullets(lines: list[str]) -> list[str]:
    items = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if not stripped.startswith("- "):
            raise ConceptFormatError(f"制約 must be a '- ' list: {stripped[:30]}")
        items.append(stripped[2:].strip())
    if not items:
        raise ConceptFormatError("制約 must have at least one item.")
    return items


def _parse_numbered(lines: list[str]) -> list[str]:
    """`1. ` からの連番であることまで見る。番号は covers から参照されるため(D34)。"""
    items = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        number, separator, rest = stripped.partition(". ")
        if not separator or not number.isdigit():
            raise ConceptFormatError(f"出来事 must be a '1. ' list: {stripped[:30]}")
        if int(number) != len(items) + 1:
            raise ConceptFormatError(f"出来事 must be numbered from 1 without gaps: {stripped[:30]}")
        items.append(rest.strip())
    if not items:
        raise ConceptFormatError("出来事 must have at least one item.")
    return items


def _parse_body(lines: list[str]) -> str:
    body = "\n".join(lines).strip()
    if not body:
        raise ConceptFormatError("構想 must not be empty.")
    return body
