# GenkaiNovelWriter

## 実行

以下はGenkaiNovelWriterディレクトリで実行します。

```shell
python main.py
python main.py --stage writing --input creations/output-example/03_plot.json
python main.py --stage borders --input creations/output-example/04_novel.json
python -m unittest discover -s test -p "test*.py" -v
```

相対的な入出力パスはGenkaiNovelWriterディレクトリを基準にします。
`--output`で保存先を指定できます。既存ファイルと同じ名前は上書きするため、
再実行には新しい保存先を使ってください。省略時は実行ごとに新規ディレクトリを作ります。
執筆にはAPI接続が必要です。境界検査と自動テストには不要です。

## 保存形式

- `01_model_config.json`: 検証済みのwriter/editor設定（APIキーは含みません）。
- `03_plot.json`: Plot。`Plot.model_validate_json()`で復元できます。
- `scenes/scene-0000.json`: 0始まりのシーン番号ごとのSceneWritingResult。生成直後に保存します。
- `04_novel.json`: WritingResult。失敗したシーンも元の位置に残します。
- `04_novel.txt`: 従来の表示形式。失敗箇所は「未生成」と明示します。
- `05_borders.json`: 境界の抜粋、抽出条件、検査方式、判定理由。
- `events.jsonl`: 実行ID、時刻、工程、使用モデル、所要時間、成果物、実行状態。

本文と生成エラーのメッセージは成果物に保存し、イベントログには本文を重複保存しません。
WritingResult.completeがfalseなら部分成功または全件失敗です。CLIも終了コード1を返します。
イベントのborders成功は検査処理が完了した意味です。検査の合否は05_borders.jsonで確認します。

`writing()`の戻り値は従来のlist[NovelScene]からWritingResultに変更しています。
各要素はresultsにあり、成功時だけsceneが入ります。失敗時はerrorが入ります。
JSONは`util.file.output_model()`と`read_model()`で保存・復元できます。
旧手作業形式（Scene Title / Content配列 / Notes）は新しいJSON形式とは異なります。

## テスト・拡張

writingにはgenerate、prompt、on_sceneを注入できます。
mainのrun_pipelineにはclientを注入でき、import時のAPI接続・対話入力はありません。
test/test.pyとtest/test_extract.pyは明示的に実行する手動確認用です。

境界検査は現在の句読点・会話括弧による簡易判定を記録します。
シーン生成失敗や空の抜粋はnot_checkedとし、欠落を飛び越えて検査しません。
extract_head/extract_tailの抽出方式は維持しているため、短文でも空になる場合があります。
bool互換のcheck_borderは未判定でもfalseを返します。
意味的な矛盾検査・自動再生成・ElaborationResultは後続工程です。
現在のelaborationは本文を変更せずBorderCheckReportを返します。
LLMには引き続き平文で小説を書かせ、Python側でNovelSceneとして検証します。
