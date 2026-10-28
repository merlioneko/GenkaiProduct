"""保存済み原入力・Plot・草稿に対応する、未評価の人手評価票。LLM は使わない。"""

from pathlib import Path

from novel import run
from novel.phases.structure import load_plot


def _cell(text: str) -> str:
    """指定要素に区切り文字や改行があっても Markdown の表を壊さない。"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(
        ">", "&gt;").replace("|", "&#124;").replace("\r\n", "\n").replace(
        "\r", "\n").replace("\n", "<br>")


def render_template(plot) -> str:
    lines = [
        "# 人手評価", "", "評価状態: 未評価", "",
        "- 評価者: ", "- 評価日: ", "- 総合判定: ", "- 総合判定の根拠: ", "",
        "## 参照資料", "",
        "- [原入力](00_input.txt)", "- [Concept](02_concept.md)",
        "- [Plot](03_plot.json)", "- [シーン本文](04_scenes/)",
        "- [草稿](05_draft.md)", "- [開始時の設定](01_config.json)", "- [操作履歴](_history/)",
        "- [呼び出しログ](calls.jsonl)", "",
        "01だけを全成果物の生成条件と解釈しないでください。各成果物のハッシュと操作履歴を照合し、"
        "不一致は外部変更または来歴不明として扱います。旧runの01の元の生成条件は未記録です。", "",
        "原入力から本文まで照合してください。以下の指定リストはConceptからPlotに転記されたもので、"
        "原入力のすべての指定を保持している保証はありません。"
        "Concept照合・Plot機械検査のレポートも参考情報です。", "",
        "## 原入力との照合", "",
        "原入力にある指定の欠落・意味改変や、下のリストにない指定もここに記録してください。"
        "出来事の主語・動作・受け手と順序を確認してください。", "",
        "| 原入力の指定・順序 | Concept / Plotとの対応・差異 | 本文のシーン・引用 | 判定・根拠 |",
        "|---|---|---|---|", "|  |  |  |  |", "",
        "## 指定要素（順序なし）", "",
        "| 番号 | Plotに保存された指定 | 判定 | 本文のシーン・引用・根拠 |",
        "|---|---|---|---|",
    ]
    lines += [f"| {number} | {_cell(item)} |  |  |"
              for number, item in enumerate(plot.constraints, 1)]
    if not plot.constraints:
        lines += ["", "指定された制約リストは空です。原入力に指定がないか確認してください。"]
    lines += ["", "## 出来事（指定順）", "",
              "| 順序 | Plotに保存された出来事 | 本文での順序・判定 | 本文のシーン・引用・根拠 |",
              "|---|---|---|---|"]
    lines += [f"| {number} | {_cell(item)} |  |  |"
              for number, item in enumerate(plot.events, 1)]
    if not plot.events:
        lines += ["", "指定された出来事リストは空です。原入力を確認し、補完した展開と指定を区別してください。"]
    lines += [
        "", "## 評価項目", "",
        "成功基準はSPEC.mdのD51で確定した基準に従います。合否・警告・観察・改善の区分と閾値を維持します。",
        "", "- 使用した基準・比較試行への参照: ", "- 基準との差異と理由（ある場合）: ", "",
        "| 項目 | 扱い | 判定・件数 | 本文のシーン・引用・根拠 |",
        "|---|---|---|---|",
        "| 要素保持・出来事の順序 | 合否 |  |  |",
        "| ジャンル・トーン適合 | 合否 |  |  |",
        "| 設定一貫性（口調・外見・場所・天候・時間帯） | 合否 |  |  |",
        "| 物理的妥当性（身体動作・位置関係・物の性質） | 合否 |  |  |",
        "| 字数（空白・改行を除く、600字未満のシーン） | 警告のみ |  |  |",
        "| 伏線放置（余韻・矛盾と区別） | 観察のみ |  |  |",
        "| 非陳腐性（曖昧入力のベースライン比較） | 改善区分 |  |  |",
        "", "## 補足・比較", "", "- 比較対象の実行ディレクトリ: ",
        "- 実行条件の差異・未確認の条件: ", "- その他の観察・評価の限界: ", "",
    ]
    return "\n".join(lines)


def save_template(directory: Path | str) -> Path:
    """草稿保存後に呼ぶ。既存の人手評価は上書きしない。"""
    directory = run.open_run(directory)
    plot = load_plot(directory)
    if not (directory / run.DRAFT).is_file():
        raise run.RunError(f"{run.DRAFT} not found. Assemble the scenes first.")
    text = render_template(plot)
    path = directory / run.EVAL
    with path.open("x", encoding="utf-8") as stream:
        stream.write(text)
    from novel.history import record_output
    record_output(path)
    return path
