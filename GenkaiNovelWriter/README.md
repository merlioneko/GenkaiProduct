# GenkaiNovelWriter

ローカルLLMを使い、アイデアから1話完結の短編小説を生成するPython製CLIツールです。構想・プロット・シーン本文を段階的に作り、途中の成果物を確認・編集してから続きを生成できます。

「設定やプロットを詰めてから、同じ文脈でシーンごとに執筆する」という手動の創作手順を自動化することを目指しています。総字数4000〜5000字、1シーン1000字前後を目安としますが、字数を保証するものではありません。

## できること

- **一括生成**：アイデアのテキストファイルから構想、プロット、本文を生成する。
- **段階的な制作**：構想やプロットをファイルで確認・編集し、次の工程だけを実行する。
- **途中からの再生成**：シーン1〜k-1を残し、シーンk以降を書き直す。先行シーンの手編集も引き継ぐ。
- **生成後の検査**：指定要素・順序、設定の矛盾、身体動作の破綻、英字・メタ表現などを検査して報告する。
- **一発生成との比較**：構想・プロットを経由せず、同じ入力を直接小説にする。

インターフェースはCLIです。GUI、連載管理、Web検索、GenkaiIllustrator連携、検査結果に基づく自動修正・自動再生成は対象外です。

## 生成の流れ

| 工程 | 役割 | 主な出力 |
|---|---|---|
| Concept | 入力の制約と出来事を抽出し、足りない設定を補う。原入力との照合も行う | `02_concept.md` |
| Structure | 構想から、登場人物・舞台・順序付きの出来事を持つシーン構成を作る | `03_plot.json` |
| Writing | 指定要素と先行シーンの全文を参照し、順に本文を書く | `04_scenes/scene_NN.md` |
| Assemble | 全シーンを空行で結合し、字数を集計する | `05_draft.md` |
| Check | 完成したプロット・本文を検査し、指摘を報告する | `06_check_report.md` |

**`run` はAssembleと人手評価票の作成までを実行します。Checkは、生成後に `stage check` で別途実行してください。** 検査は本文を書き換えません。

## 必要なもの

- **Python 3.10以上**。セキュリティ修正済みのバージョンを使用してください。推奨環境と導入の詳細は[テスト手順](test/README.md)を参照してください。
- **LM Studio**と、OpenAI互換APIのローカルサーバ。
- **`lms` CLI**。本ツールを起動するシェルから実行できるようにしてください。モデル切り替え時のアンロードに使用します。
- LM Studioにダウンロード済みの生成用モデル。配布モデルは本リポジトリに含まれません。
- 選んだモデルを動かせるメモリ・VRAM。参考の実行マシンは[仕様書](SPEC.md)に記載しており、最低動作要件ではありません。

主な実機検証はWindows / PowerShellで行っています。以下もPowerShellを基準とします。macOS / Linuxでの動作確認状況は[検証記録](MILESTONES.md)を参照してください。

**LM Studioは本ツール専用で使用してください。** 本ツールは、担当モデル以外のロード済みLLMを `lms unload` で解放します。同じLM Studioサーバを使う他のアプリは停止してから実行してください。

## セットアップ

### 1. Python環境を準備する

リポジトリを取得したら、`GenkaiNovelWriter/` に移動します。以降のコマンドはすべてこのディレクトリで実行します。

```powershell
cd GenkaiNovelWriter
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

別途ビルドする必要はありません。依存関係は[requirements.txt](requirements.txt)で管理しています。

macOS / Linuxで環境を準備する場合は、次のようにします。以降の例の `.\.venv\Scripts\python.exe` は `.venv/bin/python` に読み替えてください。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
```

### 2. LM Studioを準備する

1. 使用するモデルをダウンロードします。設定例は、Concept / Structureに **Qwen3.6-35B-A3B**、Writing / Check / Baselineに **Gemma 4 26B-A4B** を割り当てています。
2. ローカルサーバを起動します。既定の接続先は `http://localhost:1234/v1` です。
3. モデルのロード時コンテキスト長を **16384以上**に設定します。次のモデルはJITロードを利用するため、その設定も確認してください。
4. シェルで `lms --help` が実行できることを確認します。

2つのモデルを同時にロードしておく必要はありません。本ツールが先行モデルを解放し、次のモデルのロードはLM Studioに任せます。`local` バックエンドは、同じマシン上のLM Studio（`localhost` / `127.0.0.1` / `::1`）を前提とします。

モデル名・量子化によって必要なメモリや速度は変わります。設定例のモデル識別子は仮の値なので、必ず実際のモデルキーに合わせてください。モデルの採用根拠や量子化ごとの検証範囲は[仕様書](SPEC.md)・[検証記録](MILESTONES.md)を参照してください。

### 3. 接続設定を作る

初回のみ、設定例をコピーします。既存の設定がある場合は、そのファイルを編集してください。

```powershell
New-Item -ItemType Directory -Force .env
Copy-Item config/backends.example.json .env/backends.json
```

macOS / Linuxでは `mkdir -p .env`、`cp config/backends.example.json .env/backends.json` を使用します。

[config/backends.example.json](config/backends.example.json)を元に、`.env/backends.json` の `local` を編集します。

| 設定 | 指定する内容 |
|---|---|
| `base_url` | LM StudioのOpenAI互換APIのURL。既定例は `http://localhost:1234/v1` |
| `api_key` | 空でない値が必要。例は `lm-studio`。サーバで認証を設定した場合は実際のキー |
| `context_length` | 運用条件の記録用。例は `16384`。**この値でLM Studioのロード設定は変更されません** |
| `phases.*.model` | 各工程で使う、LM Studio上の実際のモデル識別子。量子化の接尾辞なども確認する |
| `phases.*.thinking` | LM Studioでは全工程 `null`。思考関連のパラメータを送らず、サーバ既定値に任せる |

`baseline` と `writing` は、モデル・思考設定を同一にしてください。`local` だけを使う場合、`remote` のAPIキーは不要です。

`thinking: true` / `false` は、切り替えに対応する接続先を検証するための設定です。利用時は `--thinking-options` にモデル別の追加リクエスト本文が必要です。LM Studioでの通常運用は `null` のままにし、詳細は[テスト手順](test/README.md)を参照してください。

## まず1本生成する

同梱のサンプル入力を使えます。

```powershell
.\.venv\Scripts\python.exe main.py run --input prompts/tests/concrete_01.txt --timeout 1800
```

新しい `creations/<日時>/` が作られ、実行ディレクトリのパスが表示されます。生成後は次の順で確認してください。

1. **`05_draft.md`**：結合済みの小説本文。
2. **`00_input.txt` と中間成果物**：指定した人物・展開・順序が保持されているか。
3. **`07_eval.md`**：人手評価票。判定や本文中の根拠を自分で記入するためのテンプレートです。

続けて検査する場合は、表示された実行ディレクトリを指定します。以下の `$run` の値は実際のパスに置き換えてください。

```powershell
$run = "creations/20261028-120000"
.\.venv\Scripts\python.exe main.py stage check --run $run --timeout 1800
```

結果は **`06_check_report.md`** にまとまります。英字の固有名を汚染検査から除外したい場合は、`--allow-name NASA` のように指定できます。複数ある場合はオプションを繰り返します。大文字小文字は区別されます。

生成には複数回の推論とモデル切り替えが必要です。`--timeout` の既定値は600秒で、例では長めの推論を待つため1800秒を指定しています。これはAPIリクエストのタイムアウト設定であり、一括処理全体の制限時間ではありません。

### 自分のアイデアを使う

UTF-8のテキストファイル（例：`idea.txt`）に、ジャンル、人物や舞台の条件、起こしたい出来事を記述します。

```text
閉店間際の喫茶店を舞台にした、穏やかなファンタジー短編。
主人公は店主の老婦人で、迷い込む客は言葉を話す黒猫。
黒猫が失くした鍵を探してほしいと頼み、老婦人は店内を一緒に探す。
最後に、鍵は老婦人が昔手放した家のものだと分かる。
```

```powershell
.\.venv\Scripts\python.exe main.py run --input idea.txt --timeout 1800
```

保持したい要素と出来事の順序は明示してください。Conceptは指定内容を保ったまま不足を補う設計ですが、LLMによる欠落や意味の変化を完全には防げません。現行実装では、指定された制約または出来事が空になる入力は構想の読み取りに失敗する場合があります。まずは両方を含む入力を使ってください。

## 途中を確認・編集しながら作る

工程ごとに止めたい場合は `stage` を使います。

```powershell
# 新規実行ディレクトリを作り、構想と照合結果を生成する
.\.venv\Scripts\python.exe main.py stage concept --input idea.txt --timeout 1800

# 表示されたパスを指定する
$run = "creations/20261028-120000"

# 02_concept.mdを確認・編集した後、プロットを生成する
.\.venv\Scripts\python.exe main.py stage structure --run $run --timeout 1800

# 03_plot.jsonを確認・編集した後、全シーンの執筆と結合を行う
.\.venv\Scripts\python.exe main.py stage writing --run $run --timeout 1800

.\.venv\Scripts\python.exe main.py stage check --run $run --timeout 1800
```

- **構想の編集**：`02_concept.md` の `# 制約`・`# 出来事`・`# 構想` の見出しと箇条書き・番号付きリストの形式を維持してください。[保存形式](SPEC.md#02_conceptmd-フォーマット)も参照できます。
- **プロットの編集**：`03_plot.json` はスキーマに適合するJSONである必要があります。シーン番号や参照先も含め、[スキーマ定義](novel/schema.py)・[仕様書](SPEC.md)を参照してください。手編集した不正なファイルは自動修復されません。
- **構想の再生成**：`stage concept --run $run` は既存の `00_input.txt` から構想を作り直します。新規作成の `--input` と既存指定の `--run` は同時には使えません。
- `stage` / `write` 単体では、新しい `07_eval.md` は自動生成されません。評価票の自動作成は `run` の終了時に行います。

### シーンk以降を書き直す・失敗したシーンから再開する

```powershell
# 例：シーン1〜2を残し、シーン3から最後まで再生成する
.\.venv\Scripts\python.exe main.py write --run $run --from 3 --timeout 1800
```

`--from` は1始まりで、プロットにあるシーン数まで指定できます。`--from 1` は全シーンの再生成です。先行シーンは保存済みファイルから全文を読み直すため、例えば `scene_02.md` を編集してから `--from 3` で続きを書けます。

シーンkを生成し直すと、その本文に依存するk+1以降も再生成します。途中でAPIエラーや打ち切りが起きた場合は、完成済みのシーンを確認し、失敗したシーン番号から同じコマンドで再開してください。

**最終シーンを手編集した場合には注意が必要です。** Checkはシーン本文と `05_draft.md` の一致を要求します。現行CLIには再生成せず結合だけをやり直すコマンドがないため、手編集後の再結合にはPythonの `assemble()` 関数の利用などが必要です。`stage writing` は編集済み本文を含めて全シーンを書き直します。詳細は[既知の課題](MILESTONES.md#review-after-m6)を参照してください。

### 再実行時の退避

既存の成果物は、再実行する工程とその下流について `_archive/<日時>/` に移動されます。

| 操作 | 退避する成果物 |
|---|---|
| `stage concept` | 構想・照合結果、プロット・検査結果、全シーン、草稿、Check結果、人手評価票 |
| `stage structure` | プロット・検査結果、全シーン、草稿、Check結果、人手評価票 |
| `stage writing` / `write --from 1` | 全シーン、草稿、Check結果、人手評価票 |
| `write --from k` | シーンk以降、草稿、Check結果、人手評価票 |
| `stage check` | Check結果のみ |

退避はバックアップ全体の代わりではありません。`creations/` はGit管理対象外なので、大切な作品は別途保存してください。また、Concept / Structureの再実行では入力形式や工程設定のエラーでも先に退避される場合があります。失敗後は `_archive/` も確認してください。

## 出力ファイル

通常の実行先は `GenkaiNovelWriter/creations/<YYYYMMDD-HHMMSS>/` です。ファイルは各工程の実行に応じて作られます。

| パス | 内容 |
|---|---|
| `00_input.txt` | 入力アイデアのコピー |
| `01_config.json` | バックエンド・モデル等の設定記録。APIキーは保存しない |
| `02_concept.md` | 制約・出来事・補完した構想 |
| `02_concept_report.json` | 原入力と構想の照合結果 |
| `03_plot.json` | 構造化されたプロット |
| `03_plot_report.json` | プロットの機械検査結果 |
| `04_scenes/scene_NN.md` | シーンごとの本文 |
| `05_draft.md` | 全シーンを結合した本文 |
| `06_check/` | 検査項目別JSON、検査条件・入力ハッシュ。失敗時はエラー情報なども保存 |
| `06_check_report.md` | 人が読むための検査結果要約 |
| `07_eval.md` | `run` が作る人手評価テンプレート |
| `calls.jsonl` | 呼び出しごとの工程・モデル・トークン使用量・所要時間・成否 |
| `_archive/` | 再実行前の成果物 |

`01_config.json` は生成工程の再実行で上書きされ、旧設定は退避されません。厳密に条件を比較する場合は、設定・入力・プロンプトも別途保存してください。比較実験向けの手順は[テスト手順](test/README.md)にあります。

## 検査結果の読み方と制約

Checkは、英字・メタ語・思考タグの混入と字数を機械的に調べ、指定要素・順序、設定の整合性、身体動作などを項目別にLLMで検査します。600字未満のシーンは警告されますが、字数だけで品質の合否は決まりません。

指摘のシーン番号と引用が原文に一致するかも検証します。ただし、引用の一致は指摘内容が正しいことの保証ではありません。検査には誤検出と見逃しがあり、現行実装には応答の `issues` 欠落を「指摘なし」と受理する既知の課題もあります。空の検査結果を品質保証とせず、原入力と本文を読み比べてください。Checkが参照する指定要素はプロット由来なので、構想段階で落ちた原入力の指定まで拾えるとは限りません。

先行シーンの全文を後続の執筆に渡すため、長いプロットや大幅に増量した本文ではコンテキストを超えることがあります。自動切り詰めは行わず停止します。一発生成に対する品質の優位性や、別モデル・別量子化での同等の結果も保証していません。評価根拠と未修正の課題は[MILESTONES.md](MILESTONES.md)を参照してください。

## その他のコマンド・設定

```powershell
# 構想・プロットを経由しない一発生成
.\.venv\Scripts\python.exe main.py baseline --input idea.txt --timeout 1800

# ヘルプ
.\.venv\Scripts\python.exe main.py --help
.\.venv\Scripts\python.exe main.py stage --help
```

`baseline` の出力先は `creations/baseline-<日時>/` で、`00_input.txt`・`baseline.md`・`calls.jsonl` が保存されます。

各コマンドで `--config <JSONファイル>` を指定すると、既定の `.env/backends.json` 以外の設定を使えます。`--backend` の既定値は `local` です。

OpenRouterを使う場合は、設定の `remote` にAPIキーとモデル識別子を設定し、`--backend remote` を指定します。**OpenRouterは動作確認・デバッグ専用で、作品の品質評価はローカルLLMで行う方針です。** リモート実行では生成・検査に使う文章が接続先に送信され、サービスの利用料金・規約が適用されます。

`.env/` はGit管理対象外です。APIキーや接続設定をコミットしないでください。生成物には入力や小説本文が残るので、共有前に内容を確認してください。

## 困ったとき

| 症状 | 確認すること |
|---|---|
| 設定ファイルを読み込めない | `.env/backends.json` の有無、JSONの形式、選択したバックエンドの必須項目 |
| LM Studioの状態を取得できない | サーバの起動、`base_url`、認証設定、同じマシンのloopbackを指定しているか |
| `lms unload failed` | シェルで `lms` が実行できるか、ロード済みモデルの状態 |
| モデルが見つからない・意図と違うモデルが解放される | 設定の識別子が実際のモデルキーまたはロード済みインスタンスIDと一致しているか。量子化も確認する |
| 構想・プロットの形式エラー | `02_concept.md` の固定見出しやリスト、`03_plot.json` のスキーマ。Structure生成のスキーマ違反は最大3回試行し、失敗時は `03_plot_raw.txt` に生出力を保存する |
| 空応答・途中打ち切り・タイムアウト | `calls.jsonl`、LM Studio側のログ・コンテキスト長・生成設定。必要に応じて `--timeout` を調整する |
| Checkが草稿との不一致で停止する | 全シーンの存在、余分なシーンファイル、手編集後の `05_draft.md` との対応 |
| Checkが形式エラーになる | `06_check/error.json`、`<項目>_raw.txt`、`06_check_report.md` の完了済み・未実行項目 |

エラー表示は秘密情報の露出を避けるため、例外の種類だけになる場合があります。API失敗時にトークン使用量が得られない場合、ログの該当値は `null` です。CheckではAPI応答が成功しても、その後の引用検証で失敗する場合があるため、`calls.jsonl` の `success` だけで検査完了とは判断しないでください。

## 開発・関連ドキュメント

オフラインテストは次のコマンドで実行できます。LM StudioやAPIキーは不要で、外部APIには通信しません。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s test -t . -p "test_*.py" -v
```

`-t .` を省略しないでください。コードは `main.py` がCLI、`novel/` がデータモデル・各工程・成果物管理、`util/` が設定・API接続・ログ、`prompts/` がプロンプトと入力例、`config/` が設定例、`test/` がテストと実機検証用スクリプトです。

- [SPEC.md](SPEC.md)：仕様、設計判断、データ形式、受け入れ条件。
- [MILESTONES.md](MILESTONES.md)：進捗、実機検証の根拠、既知の課題と未検証範囲。過去の検証成果物へのリンクには、Git管理外で手元に存在しないものもあります。
- [test/README.md](test/README.md)：環境構築の詳細、バックエンド検証、比較実験の手順。
- [AGENTS.md](../AGENTS.md)：リポジトリの開発・文書更新ルール。

不具合を報告する場合は、実行コマンド、Python / LM Studioのバージョン、モデルと量子化、再現手順、秘密情報を除いたエラー・ログを添えてください。コード変更時は関連するテストを実行し、仕様や検証状況が変わる場合は上記文書も更新してください。

## ライセンス

本リポジトリには、現時点でライセンスを明示する `LICENSE` ファイルがありません。コードの再利用・再配布条件は権利者に確認してください。使用するモデル・依存ライブラリ・外部サービスの利用条件は、それぞれのライセンス・規約に従ってください。
