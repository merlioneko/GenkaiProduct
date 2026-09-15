"""novel/schema.py のモデルが SPEC のスキーマどおりに振る舞うことを確認する。API 不要。"""

import json
import unittest

from pydantic import ValidationError

from novel.schema import CheckResult, Concept, Novel, NovelScene, Plot


def plot_data():
    return {
        "meta": {"genre": "ラブコメ", "tone": "軽快", "style": "三人称", "pov": "少女"},
        "constraints": ["ジャンル: ラブコメ"],
        "events": ["少女が魔人に出会う", "二人で帰る"],
        "characters": [{"name": "少女", "persona": "強気", "appearance": "制服",
                        "speech_examples": ["行くよ"], "notes": ""}],
        "settings": [{"name": "家", "kind": "place", "notes": "少女の家"}],
        "scenes": [{"name": "出会い", "opening": {"place": "家", "time_of_day": "朝", "weather": "晴れ"},
                    "beats": ["少女が家で魔人に出会う"], "covers": [1]}],
    }


class SchemaTest(unittest.TestCase):
    def test_plot_round_trips_and_defaults_target_chars(self):
        plot = Plot.model_validate(plot_data())
        self.assertEqual(plot.scenes[0].target_chars, 1000)
        self.assertEqual(Plot.model_validate_json(plot.model_dump_json()), plot)

    def test_plot_json_schema_forbids_extra_fields_everywhere(self):
        schema = Plot.model_json_schema()
        self.assertFalse(schema["additionalProperties"])
        for definition in schema["$defs"].values():
            self.assertFalse(definition["additionalProperties"], definition.get("title"))

    def test_plot_rejects_old_capitalized_keys_empty_lists_and_extras(self):
        with self.assertRaises(ValidationError):
            Plot.model_validate_json('{"Characters": [], "Settings": [], "Scenes": []}')
        for key in ("characters", "settings", "scenes"):
            data = plot_data()
            data[key] = []
            with self.assertRaises(ValidationError):
                Plot.model_validate(data)
        data = plot_data()
        data["scenes"][0]["beats"] = []
        with self.assertRaises(ValidationError):
            Plot.model_validate(data)
        data = plot_data()
        data["meta"]["unexpected"] = "value"
        with self.assertRaises(ValidationError):
            Plot.model_validate(data)
        data = plot_data()
        data["settings"][0]["kind"] = "mood"
        with self.assertRaises(ValidationError):
            Plot.model_validate(data)

    def test_concept_keeps_constraints_and_events_separate(self):
        concept = Concept(constraints=["ジャンル: ラブコメ"], events=["出会う", "帰る"], body="# 構想\n本文")
        self.assertEqual(concept.events, ["出会う", "帰る"])
        with self.assertRaises(ValidationError):
            Concept.model_validate({"constraints": [], "events": [], "body": "", "extra": 1})

    def test_novel_context_until_and_invalidate_from(self):
        novel = Novel(scenes=[NovelScene(index=i, title=f"S{i}", content=f"本文{i}") for i in (1, 2, 3)])
        self.assertEqual(novel.context_until(1), "")
        self.assertEqual(novel.context_until(3), "本文1\n\n本文2")
        self.assertEqual(novel.context_until(99), "本文1\n\n本文2\n\n本文3")
        novel.invalidate_from(2)
        self.assertEqual([scene.index for scene in novel.scenes], [1])
        self.assertEqual(Novel().context_until(1), "")
        with self.assertRaises(ValidationError):
            NovelScene(index=0, title="", content="")

    def test_check_result_matches_spec_json(self):
        data = {"item": "physical", "issues": [{"scene": 3, "quote": "抜粋", "reason": "説明"}]}
        result = CheckResult.model_validate(data)
        self.assertEqual(json.loads(result.model_dump_json()), data)
        self.assertEqual(CheckResult(item="length").issues, [])


if __name__ == "__main__":
    unittest.main()
