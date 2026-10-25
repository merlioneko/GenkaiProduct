"""保存済み原入力・Plot・草稿に対応する、未評価の人手評価票。LLM は使わない。"""

from pathlib import Path

from novel import run
from novel.phases.structure import load_plot


def _cell(text: str) -> str:
    """指定要素に区切り文字や改行があっても Markdown の表を壊さない。"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(
        ">", "&gt;").replace("|", "&#124;").replace("\r\n", "\n").replace(
        "\r", "\n").replace("\n", "<br>")


def save_template(directory: Path | str) -> Path:
    """草稿保存後に呼ぶ。既存の人手評価は上書きしない。"""
    directory = run.open_run(directory)
    plot = load_plot(directory)
    if not (directory / run.DRAFT).is_file():
        raise run.RunError(f"{run.DRAFT} not found. Assemble the scenes first.")
    lines = [
        "# 人手評価", "", "評価状態: 未評価", "",
        "- 評価者: ", "- 評価日: ", "- 総合判定: ", "- 総合判定の根拠: ", "",
        "## 参照資料", "",
        "- [原入力](00_input.txt)", "- [Concept](02_concept.md)",
        "- [Plot](03_plot.json)", "- [シーン本文](04_scenes/)",
        "- [草稿](05_draft.md)", "- [実行設定](01_config.json)",
        "- [呼び出しログ](calls.jsonl)", "",
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
    lines += ["", "## 出来事（指定順）", "",
              "| 順序 | Plotに保存された出来事 | 本文での順序・判定 | 本文のシーン・引用・根拠 |",
              "|---|---|---|---|"]
    lines += [f"| {number} | {_cell(item)} |  |  |"
              for number, item in enumerate(plot.events, 1)]
    lines += [
        "", "## 評価項目", "",
        "成功基準はSPEC.mdの案に基づきます。M5で事前に決めた暫定基準と、評価後の変更を区別してください。",
        "", "- 使用した暫定基準・比較試行への参照: ", "- 評価後の基準変更と理由: ", "",
        "| 項目 | 扱い | 判定・件数 | 本文のシーン・引用・根拠 |",
        "|---|---|---|---|",
        "| 要素保持・出来事の順序 | 合否案 |  |  |",
        "| ジャンル・トーン適合 | 合否案 |  |  |",
        "| 設定一貫性（口調・外見・場所・天候・時間帯） | 合否案 |  |  |",
        "| 物理的妥当性（身体動作・位置関係・物の性質） | 合否案 |  |  |",
        "| 字数（空白・改行を除く、600字未満のシーン） | 警告のみ |  |  |",
        "| 伏線放置（余韻・矛盾と区別） | 観察のみ |  |  |",
        "| 非陳腐性（曖昧入力のベースライン比較） | 改善区分 |  |  |",
        "", "## 補足・比較", "", "- 比較対象の実行ディレクトリ: ",
        "- 実行条件の差異・未確認の条件: ", "- その他の観察・評価の限界: ", "",
    ]
    path = directory / run.EVAL
    with path.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines))
    return path
