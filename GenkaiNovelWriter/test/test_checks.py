"""Plot 機械検査(SPEC.md「Plot機械検査」)。LLM を使わないので API 不要。"""

import json
import tempfile
import unittest
from pathlib import Path

from novel import checks, run
from novel.schema import Plot


def healthy_plot(**overrides):
    """検査に何も引っかからない Plot。テストごとに1箇所だけ壊す。"""
    data = {
        "meta": {"genre": "ドタバタラブコメ", "tone": "軽快", "style": "三人称", "pov": "ギャル"},
        "constraints": ["ジャンル: ドタバタラブコメ"],
        "events": ["魔人が住み着く", "ギャルがカチコミに行く", "魔人が助けに来る"],
        "characters": [{"name": "ギャル", "persona": "強気", "appearance": "金髪",
                        "speech_examples": ["行くよ"], "notes": ""},
                       {"name": "魔人", "persona": "傲慢", "appearance": "角",
                        "speech_examples": ["ふん"], "notes": ""}],
        "settings": [{"name": "ギャルの家", "kind": "place", "notes": "散らかっている"},
                     {"name": "廃工場", "kind": "place", "notes": "決戦の場"}],
        "scenes": [
            {"name": "同居", "opening": {"place": "ギャルの家", "time_of_day": "朝", "weather": "晴れ"},
             "beats": ["魔人がギャルの家に居座る", "ギャルが魔人に文句を言う"], "covers": [1],
             "target_chars": 1000},
            {"name": "決戦", "opening": {"place": "廃工場", "time_of_day": "夕方", "weather": "曇り"},
             "beats": ["ギャルが廃工場に乗り込む", "魔人が助けに来る"], "covers": [2, 3],
             "target_chars": 1000},
        ],
    }
    data.update(overrides)
    return Plot(**data)


def kinds(report):
    return [finding.check for finding in report.findings]


class PlotCheckTest(unittest.TestCase):
    def test_a_healthy_plot_has_no_findings(self):
        self.assertEqual(checks.check_plot(healthy_plot()).findings, [])

    def test_undecided_wording_is_detected(self):
        plot = healthy_plot()
        plot.scenes[0].beats[0] = "魔人がギャルの家、または近所の神社に居座る"
        report = checks.check_plot(plot)
        self.assertEqual(kinds(report), ["undecided"])
        self.assertEqual(report.findings[0].location, "scenes[0].beats[0]")

    def test_undecided_wording_is_detected_in_full_width_examples(self):
        plot = healthy_plot()
        plot.characters[0].notes = "口調は乱暴（例: あぁ？）"
        self.assertEqual(kinds(checks.check_plot(plot)), ["undecided"])

    def test_an_unused_character_is_detected(self):
        plot = healthy_plot()
        plot.characters.append(plot.characters[0].model_copy(update={"name": "神社の巫女"}))
        report = checks.check_plot(plot)
        self.assertEqual(kinds(report), ["unused"])
        self.assertEqual(report.findings[0].location, "characters[2].name")

    def test_an_unused_setting_is_detected(self):
        plot = healthy_plot()
        plot.settings.append(plot.settings[0].model_copy(update={"name": "神社跡地"}))
        self.assertEqual(kinds(checks.check_plot(plot)), ["unused"])

    def test_a_place_used_only_as_a_scene_location_is_not_unused(self):
        # 実測で出た誤検出。舞台として使われていても beats に名前が出ないことがある。
        plot = healthy_plot()
        for setting, scene in zip(plot.settings, plot.scenes):
            setting.name = "住宅街の" + setting.name
            scene.opening.place = setting.name
        self.assertEqual(checks.check_plot(plot).findings, [])

    def test_an_undefined_place_is_detected(self):
        plot = healthy_plot()
        plot.scenes[0].opening.place = "自宅"
        report = checks.check_plot(plot)
        # settings の「ギャルの家」は beats に残っているので、未使用にはならない。
        self.assertEqual(kinds(report), ["place"])
        self.assertIn("「自宅」", report.findings[0].detail)

    def test_a_place_kind_mismatch_is_detected(self):
        plot = healthy_plot()
        plot.settings[1].kind = "item"
        self.assertIn("place", kinds(checks.check_plot(plot)))

    def test_an_unassigned_event_is_detected(self):
        plot = healthy_plot()
        plot.scenes[1].covers = [2]
        report = checks.check_plot(plot)
        self.assertEqual(kinds(report), ["uncovered"])
        self.assertEqual(report.findings[0].location, "events[2]")

    def test_an_out_of_order_event_is_detected(self):
        plot = healthy_plot()
        plot.scenes[0].covers = [3]
        plot.scenes[1].covers = [1, 2]
        report = checks.check_plot(plot)
        self.assertEqual(kinds(report), ["order"])
        self.assertEqual(report.findings[0].location, "scenes[1].covers")

    def test_an_event_number_that_does_not_exist_is_detected(self):
        plot = healthy_plot()
        plot.scenes[1].covers = [2, 3, 9]
        self.assertEqual(kinds(checks.check_plot(plot)), ["covers"])

    def test_an_event_covered_by_two_scenes_is_not_an_order_violation(self):
        plot = healthy_plot()
        plot.scenes[0].covers = [1, 2]
        plot.scenes[1].covers = [2, 3]
        self.assertEqual(checks.check_plot(plot).findings, [])

    def test_the_report_is_saved_as_json(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            plot = healthy_plot()
            plot.scenes[0].opening.place = "自宅"
            path = checks.save_plot_report(directory, checks.check_plot(plot))
            self.assertEqual(path.name, run.PLOT_REPORT)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["findings"]), 1)
            self.assertIn("自宅", json.dumps(saved, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
