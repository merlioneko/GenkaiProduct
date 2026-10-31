# GenkaiCharacterMaker

ローカルLLMと一緒に人物設定を作成・編集するWindows向けデスクトップアプリです。

## 起動

この環境では `H:\GenkaiProduct\GenkaiCharacterMaker\start.bat` をダブルクリックしてください。

別の環境ではPython 3.12を用意して `setup.bat` を実行します。専用の `.venv` にPySide6-EssentialsとPydantic 2をインストールします。次回からは `start.bat` で起動できます。

PowerShellから直接起動する場合：

```powershell
cd H:\GenkaiProduct\GenkaiCharacterMaker
.\.venv\Scripts\python.exe main.py
```

## 使い方

1. 「接続設定」を開き、「接続確認・モデル一覧を取得」を押します。
2. 使用するモデルを一覧から選び、OKで保存します。既定の接続先は `http://127.0.0.1:8080/v1`。LM Studioの場合はポート等を変更してください。
3. 左側に人物イメージを入力します。特殊能力などを含める場合は「＋自由項目を追加」で項目名を登録します。
4. 「全体を生成」を押し、現在値と提案内容を見比べ、「適用」または「破棄」を選びます。
5. 各項目は直接編集できます。「生成・再生成」から、その項目だけへの指示を入力できます。
6. 「保存」で再編集用JSONを保存します。「Markdown出力」「Markdownコピー」で外部アプリへ渡せます。

モデルの読み込みは推論サーバー側で行います。認証が必要なら接続設定へ入力でき、認証値は起動中のみ保持します。その他の接続設定はユーザーのアプリ設定領域へ保存します。

推論モデルは思考にも出力トークンを使う場合があります。初期値は上限8192・期限300秒。上限超過・途中切れ・不正JSONはエラーとして示し、現在の文書を保持します。必要なら接続設定で上限や期限を調整して再試行してください。エラーの「詳細」で応答を確認できます。

## 編集・保存・出力

基本項目は名前・性格と価値観・容姿・口調の例・背景と過去・補足です。台詞は一件ずつ追加・編集・削除でき、台詞内の改行も保持します。

自由項目はID・項目名・複数行の本文で保存し、追加・削除・改名・上下移動と個別生成ができます。全体生成でも項目名・ID・順序を維持します。生成中と候補確認中は編集をロックし、キャンセル・破棄で編集に戻ります。

JSONは一人一ファイル、既定の保存先は `creations/characters/` です。空欄の下書きも保存できます。新規・開く・終了時は未保存変更を確認します。一時ファイルへの書込成功後に元ファイルを置換します。自動保存はありません。

五項目JSONはGenkaiNovelWriter向けの受け渡し用データで、背景・補足・自由項目をnotesへ統合します。構造を保つ再編集には保存用JSONを使います。五項目出力には口調の例が1件以上必要です。

## 検証と設計

オフラインテスト：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s test -t . -v
```

ローカルモデルでの実生成確認（明示的に実行）：

```powershell
.\.venv\Scripts\python.exe test\verify_backend.py
```

検証スクリプトは8080番の先頭モデルを検証用に選び、全体・背景・自由項目の生成を行います。通常UIではモデルを明示的に選択します。結果は `creations/verification/` に保存します。

- [SPEC.md](SPEC.md)：要件と設計。
- [MILESTONES.md](MILESTONES.md)：実装・検証記録と残る確認。
- [保存例](examples/character.gcm.json)、[五項目JSON例](examples/character.novelwriter.json)、[Markdown例](examples/character.md)。
