"""novel/run.py が SPEC の「実行ディレクトリ」「退避」の表どおりに振る舞うことを確認する。API 不要。"""

import json
import tempfile
import unittest
from pathlib import Path

from novel import run
from util.config import PROJECT_ROOT, load_backend


class RunDirectoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def make_run(self, *names):
        """成果物が一通り揃った実行ディレクトリを作る。"""
        idea = self.root / "idea.txt"
        idea.write_text("不良少女と魔人の話。", encoding="utf-8")
        directory = run.create_run(idea, output_root=self.root / "creations")
        for name in names:
            path = directory / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{name} の中身", encoding="utf-8")
        return directory

    def all_artifacts(self):
        return [run.CONCEPT, run.CONCEPT_REPORT, run.PLOT, run.PLOT_REPORT,
                f"{run.SCENES}/scene_01.md", f"{run.SCENES}/scene_02.md", f"{run.SCENES}/scene_03.md",
                run.DRAFT, f"{run.CHECK}/elements.json", run.CHECK_REPORT, run.EVAL]

    def test_create_run_writes_input_and_rejects_empty_idea(self):
        directory = self.make_run()
        self.assertEqual(run.read_input(directory), "不良少女と魔人の話。")
        empty = self.root / "empty.txt"
        empty.write_text("   \n", encoding="utf-8")
        with self.assertRaises(ValueError):
            run.create_run(empty, output_root=self.root / "creations")

    def test_directories_created_in_the_same_second_do_not_collide(self):
        made = {run.create_output_dir(self.root / "creations", "") for _ in range(3)}
        self.assertEqual(len(made), 3)

    def test_open_run_rejects_a_directory_without_input(self):
        with self.assertRaises(run.RunError):
            run.open_run(self.root / "missing")
        plain = self.root / "plain"
        plain.mkdir()
        with self.assertRaises(run.RunError):
            run.open_run(plain)

    def test_config_snapshot_records_models_without_the_api_key(self):
        directory = self.make_run()
        config_path = self.root / "backends.json"
        config_path.write_text((PROJECT_ROOT / "config/backends.example.json").read_text(encoding="utf-8"),
                               encoding="utf-8")
        config = load_backend(config_path)
        path = run.save_config_snapshot(directory, "local", config)
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(snapshot["backend"], "local")
        self.assertEqual(snapshot["phases"]["writing"]["model"], "gemma-4-26b-a4b")
        self.assertNotIn("api_key", snapshot)
        self.assertNotIn("lm-studio", path.read_text(encoding="utf-8"))

    def test_stage_structure_archives_03_and_later_but_keeps_02(self):
        directory = self.make_run(*self.all_artifacts())
        destination = run.archive_downstream(directory, "structure")
        self.assertTrue((directory / run.CONCEPT).exists())
        self.assertTrue((directory / run.CONCEPT_REPORT).exists())
        for name in (run.PLOT, run.PLOT_REPORT, run.SCENES, run.DRAFT, run.CHECK, run.CHECK_REPORT, run.EVAL):
            self.assertFalse((directory / name).exists(), name)
        # 退避であって削除ではない(D23)。元の相対パスを保つ。
        self.assertEqual((destination / run.PLOT).read_text(encoding="utf-8"), "03_plot.json の中身")
        self.assertTrue((destination / run.SCENES / "scene_02.md").exists())
        self.assertEqual(destination.parent.name, run.ARCHIVE)

    def test_stage_concept_archives_02_and_later(self):
        directory = self.make_run(*self.all_artifacts())
        run.archive_downstream(directory, "concept")
        self.assertTrue((directory / run.INPUT).exists())
        for name in self.all_artifacts():
            self.assertFalse((directory / name).exists(), name)

    def test_stage_check_archives_only_06(self):
        directory = self.make_run(*self.all_artifacts())
        run.archive_downstream(directory, "check")
        self.assertTrue((directory / run.DRAFT).exists())
        self.assertTrue((directory / run.EVAL).exists())
        self.assertTrue((directory / run.SCENES / "scene_01.md").exists())
        self.assertFalse((directory / run.CHECK).exists())
        self.assertFalse((directory / run.CHECK_REPORT).exists())

    def test_stage_writing_archives_evaluation_with_the_draft(self):
        directory = self.make_run(*self.all_artifacts())
        destination = run.archive_downstream(directory, "writing")
        self.assertFalse((directory / run.EVAL).exists())
        self.assertEqual((destination / run.EVAL).read_text(encoding="utf-8"), "07_eval.md の中身")
        self.assertTrue((directory / run.PLOT).exists())

    def test_write_from_k_keeps_earlier_scenes(self):
        directory = self.make_run(*self.all_artifacts())
        destination = run.archive_from_scene(directory, 3)
        self.assertEqual([path.name for path in run.scene_paths(directory)],
                         ["scene_01.md", "scene_02.md"])
        self.assertTrue((destination / run.SCENES / "scene_03.md").exists())
        self.assertFalse((directory / run.DRAFT).exists())
        self.assertFalse((directory / run.CHECK_REPORT).exists())
        self.assertFalse((directory / run.EVAL).exists())
        self.assertEqual((destination / run.EVAL).read_text(encoding="utf-8"), "07_eval.md の中身")

    def test_write_from_one_archives_every_scene(self):
        directory = self.make_run(*self.all_artifacts())
        run.archive_from_scene(directory, 1)
        self.assertEqual(run.scene_paths(directory), [])

    def test_archiving_nothing_creates_no_archive_directory(self):
        directory = self.make_run()
        self.assertIsNone(run.archive_downstream(directory, "concept"))
        self.assertFalse((directory / run.ARCHIVE).exists())

    def test_repeated_archives_are_kept_side_by_side(self):
        directory = self.make_run(run.PLOT)
        first = run.archive_downstream(directory, "structure")
        (directory / run.PLOT).write_text("作り直した Plot", encoding="utf-8")
        second = run.archive_downstream(directory, "structure")
        self.assertNotEqual(first, second)
        self.assertEqual((first / run.PLOT).read_text(encoding="utf-8"), "03_plot.json の中身")
        self.assertEqual((second / run.PLOT).read_text(encoding="utf-8"), "作り直した Plot")

    def test_scene_paths_are_numeric_order_not_text_order(self):
        directory = self.make_run(*[f"{run.SCENES}/scene_{index:02d}.md" for index in (1, 2, 10)])
        self.assertEqual([run.scene_number(path) for path in run.scene_paths(directory)], [1, 2, 10])
        self.assertEqual(run.scene_path(directory, 7).name, "scene_07.md")

    def test_unexpected_file_in_scenes_stops_instead_of_being_skipped(self):
        directory = self.make_run(f"{run.SCENES}/メモ.md")
        with self.assertRaises(run.RunError):
            run.scene_paths(directory)

    def test_scene_numbers_start_at_one(self):
        directory = self.make_run()
        with self.assertRaises(run.RunError):
            run.scene_path(directory, 0)
        with self.assertRaises(run.RunError):
            run.archive_from_scene(directory, 0)

    def test_unknown_stage_is_rejected(self):
        directory = self.make_run()
        with self.assertRaises(run.RunError):
            run.archive_downstream(directory, "unknown")


if __name__ == "__main__":
    unittest.main()
