# テストと実機検証

以下は `GenkaiNovelWriter` ディレクトリで実行する。Pydantic 2 が必要。
検証済みの推奨環境は Python 3.12.15。古い Python 3.12.0 は使わず、セキュリティ修正済みの Python を使う。

本書は検証の実行手順を管理する。受け入れ条件の正本は [SPEC.md](../SPEC.md)、実施結果・環境・未検証事項の正本は [MILESTONES.md](../MILESTONES.md)。

## 1. 環境構築

```powershell
# uv でプロジェクト内に修正版 Python を配置する(PATH・レジストリは変更しない)
uv python install 3.12.15 --install-dir .python --no-bin --no-registry
.\.python\cpython-3.12.15-windows-x86_64-none\python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade "pip>=26.2.2"
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

既存 `.venv` の Python が古い場合は、先に `.venv` を `creations/` 内へ退避してから新規作成する。
`pip install --upgrade` だけでは Python 本体は更新されない。
uv を使わない場合は、別途セキュリティ修正済み Python を導入し、その実行ファイルで `-m venv .venv` を実行する。
2026-10-22 の更新で `.venv` は Python 3.12.15・pip 26.2.2 に切り替えた。第9節の Python 3.12.0 は M3 検証当時の記録。

## 2. API 不要のテスト

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s test -t . -p "test_*.py" -v
```

`-t .` は必須(`test` をパッケージとして読ませるため)。実際の OpenAI SDK にメモリ上の HTTP トランスポートを注入するので、LM Studio・OpenRouter へは通信しない。

## 3. バックエンド設定

`config/backends.example.json` を `.env/backends.json` にコピーし、`phases.*.model` を LM Studio 上の実際の識別子に置き換える。

- `thinking` は `true` / `false` / `null`(SPEC D26)。**LM Studio では切り替えが効かないので `null` にする(SPEC D37)。** `null` のときは思考関連のパラメータを付けず、サーバ既定値で動く。
- `true` / `false` にした場合は、そのモデルの on/off 用リクエスト本文を `--thinking-options` で渡す必要がある(下記)。無ければ実行前にエラーになる。
- `baseline` は `writing` とモデル・思考設定を同一にする。
- `context_length` は記録用。LM Studio 側のロード設定は別途 16384 以上にする。
- `remote` の鍵は `local` 実行時には不要。`--backend remote` は動作確認専用(D2)。

## 4. ベースライン(M1)

```powershell
.\.venv\Scripts\python.exe main.py baseline --input prompts/tests/concrete_01.txt
.\.venv\Scripts\python.exe main.py baseline --input prompts/tests/vague_01.txt
```

各入力を2回ずつ実行する。`creations/baseline-*/` ごとに `00_input.txt`・`baseline.md`・`calls.jsonl` が保存される。空応答・途中打ち切り・API エラーでは `baseline.md` を作らず、入力とログだけ残して停止する。

## 5. 思考モードの検証(SPEC D37、再確認用)

`config/thinking-options.template.json` をコピーし、モデル名を合わせ、`on` / `off` の `null` を検証したいリクエスト本文の追加パラメータに置き換える。例(有効性は未確認):

```json
{
  "実際のQwenモデルID": {
    "on": {"chat_template_kwargs": {"enable_thinking": true}},
    "off": {"chat_template_kwargs": {"enable_thinking": false}}
  }
}
```

```powershell
.\.venv\Scripts\python.exe test/verify_backend.py --checks thinking --thinking-options config/thinking-options.json
```

`thinking-*-on/off.json` で本文・思考タグ混入・別フィールドの思考内容を比較する。パラメータが無視される場合もあるので、HTTP 成功やタグが無いことだけで切り替え成功とは判定しない。現状は切り替え不可と確定済み(D37)。LM Studio を更新したときに、この手順で再確認する。

## 6. 構造化出力・切り替え・速度(SPEC D38/D39、U7)

```powershell
.\.venv\Scripts\python.exe test/verify_backend.py --checks schema switching speed
```

`creations/verify-<日時>/` に `verification.json`・`calls.jsonl`・各試行の出力が保存される。`schema` は10回試行し、スキーマ違反と API エラーを別々に数える。`switching` は Qwen → Gemma → Qwen の順に呼び、前後の `/api/v1/models` とメモリを記録する。M3 以降は D39 の明示アンロードを適用した状態の検証になる。M1 の JIT のみによる検証とは区別し、前モデルが解放されているかは人手で判断する。

## 7. 実測後の記録

観測結果は [MILESTONES.md](../MILESTONES.md) の該当マイルストーンに、検証日・対象コミット・コマンド・結果・成果物の場所・未検証範囲とともに記録する。モデル名・量子化・コンテキスト長・LM Studio のバージョン・使用した思考パラメータも残す。初回のバックエンド検証記録は [M1 検証記録](../MILESTONES.md#evidence-m1)を参照する。未確定事項を確定できた場合は、`SPEC.md` の U番号から D番号へ移し、結論・理由と検証記録への参照を残す。未確定の速度観測は MILESTONES.md に参考値として記録し、観測だけで U7 を確定しない。プログラムが文書を自動更新することはない。

## 8. M2 の実行(Concept・Structure)

LM Studio を起動し、`.env/backends.json` の `concept` / `structure` に Qwen を割り当てた状態で実行する。

```powershell
.\.venv\Scripts\python.exe main.py stage concept --input prompts/tests/concrete_01.txt
.\.venv\Scripts\python.exe main.py stage structure --run creations/<日時>
```

`stage concept` は `--input` で新しい実行ディレクトリを作り、`--run` は既存のディレクトリに対して実行する。どちらか一方を指定する。`stage structure` は `--run` のみ。

出力は `creations/<日時>/` に `00_input.txt`・`01_config.json`・`02_concept.md`・`02_concept_report.json`・`03_plot.json`・`03_plot_report.json`・`calls.jsonl`。

以下の操作で [SPEC.md の M2 受け入れ条件](../SPEC.md#acceptance-m2)を確認し、結果を MILESTONES.md に記録する。

- `concrete_01.txt` と `vague_01.txt` の両方で、2つの stage が最後まで通る。
- `concrete_01.txt` の `02_concept.md` の「# 制約」にジャンル(ドタバタラブコメ)が、「# 出来事」に「魔人到着 → 自力で再起 → 攻撃を受けて気絶」の順序が含まれている。
- `02_concept.md` を手で編集してから `stage structure` を再実行すると、編集内容が `03_plot.json` に反映され、旧成果物が `_archive/<日時>/` に退避される。
- 検証用コピーの `03_plot.json` を手で壊してから、Plot を読む後続の `stage writing --run <検証用コピー>` を実行し、パースエラーで退避・LLM 呼び出し前に停止することを確認する(AC-M2-4)。`stage structure` は Plot を再生成するため、この確認には使わない。確認後はコピーの Plot を元に戻す。
- `03_plot_report.json` が、意図的に仕込んだ未使用キャラ・未定義の場所・「または」・出来事の順序違反を検出する。`03_plot.json` を手で書き換えてから、機械検査だけを呼び出して確かめる。

`02_concept.md` の形式が崩れていた場合は、ファイルを残したままエラーで停止する。手で直してから `stage structure` に進める。`03_plot.json` がスキーマに適合しなかった場合は、3回試したあと最後の生出力が `03_plot_raw.txt` に残る。

## 9. M3 の実行(Writing・再開・Assemble)

実行前に、使用する環境の Python と依存ライブラリで通常の CLI が起動することを確認する。過去の環境確認は [M3 検証記録](../MILESTONES.md#evidence-m3)、確認対象は [SPEC.md の M3 受け入れ条件](../SPEC.md#acceptance-m3)を参照する。

実機実行前に、LM Studio 側で執筆モデルのロード時コンテキスト長を **16384** にする。設定ファイルの `context_length` は記録用で、ロード設定を変更しない。`thinking` は `null`、タイムアウトは M2 の実績に従い1800秒を使う。

```powershell
.\.venv\Scripts\python.exe main.py stage writing --run creations/20261001-234342 --timeout 1800
# scene_02.md を手で編集してから再開
.\.venv\Scripts\python.exe main.py write --run creations/20261001-234342 --from 3 --timeout 1800
```

- `stage writing` と `write --from 1` は `04_scenes/` 全体・05・06・07を退避して全シーンを執筆する。`--from k` はシーンk以降・05・06・07のみ退避し、前のシーンには書き込まない。
- 再開番号は1〜Plotのシーン数。範囲外の番号、壊れた Plot、再利用する本文の欠落・空ファイルは退避前に停止する。各シーン生成時に先行本文をファイルから全文読み直す。
- 生成完了ごとに `04_scenes/scene_NN.md` を保存する。全シーン成功後に `05_draft.md` を結合し、標準出力に空白・改行を除いた各シーン字数と合計字数を出す。600字未満の警告は標準エラーに出す。
- API エラー、空応答、途中打ち切りでは停止し、完成済みシーンは残す。失敗シーンから `write --from k` で再開する。入力の自動切り詰め・自動修復・自動再生成はしない。
- `calls.jsonl` の `phase: writing` と `scene` で呼び出しを特定する。最終シーンの `input_tokens + output_tokens` が16384以下かを確認して U5 の判断材料とする。API が失敗時に usage を返さない場合は `null` のまま残し、推定値を実測扱いしない。
- 各シーンの見出し・Scene Title・思考タグの混入、およびビートの指示文や役割名の不自然な流用を通読で確認する。Writing は本文を後処理で修正しない。機械的な汚染検査は [M6](../MILESTONES.md#milestone-m6) の作業。

ローカルの実クライアントは、最初の生成前に `/api/v1/models` で実際のロード状態を取得する。担当モデル以外の LLM インスタンスを `lms unload <id>` で解放し、解放後の状態を再確認してから生成する(D39)。`lms` が見つからない、状態を取得できない、解放できない場合は生成を始めず停止する。`local` は loopback の LM Studio を使う。`remote` ではモデル管理を行わない。

モデル一覧のキーと設定済み識別子が一致しない場合は、同じモデル・量子化であることを確認し、一覧にある正確なキーへ設定を合わせるか、`lms load <正確なキー> --identifier <設定済み識別子> --context-length 16384 --yes` で明示ロードする。モデルの自動代替は行わない。

## 10. M4 の実行（一括生成・人手評価票）

LM Studioを本ツール専用で使用する(D46、旧U16)。同じサーバを使う他アプリを停止し、モデル識別子・量子化・実ロード長を確認してから実行する。Qwen→Gemmaの切替では、担当モデル以外のロード済みLLMが解放される。

```powershell
.\.venv\Scripts\python.exe main.py run --input prompts/tests/concrete_01.txt --timeout 1800
.\.venv\Scripts\python.exe main.py run --input prompts/tests/vague_01.txt --timeout 1800
```

各実行は新しい `creations/<日時>/` を作る。Concept・照合・Structure・Plot機械検査・Writing・Assembleを順に実行し、草稿の後に `07_eval.md` を保存する。Checkは実行せず、06のファイルは不要。レポートの指摘は報告のみだが、APIエラーや形式不正では後続を呼ばず停止する。入力・設定・ログ・生成済み成果物は残る。失敗時の `Run: <パス>` は標準エラーに表示される。

- [M4受け入れ条件](../SPEC.md#acceptance-m4)に沿って、00〜05・07・呼び出しログの保存、草稿と全シーンの順次結合の一致、Check未実行を確認する。
- `07_eval.md` の指定リストはConcept由来である。リンク先の原入力を必ず読み、リスト自体の欠落・意味改変と本文中の根拠を人手で確認する。評価者・判定・根拠は未記入で生成される。
- 生成部分のstage再実行・`write --from k` では記入済みの07も退避される。stage・write単体では新しい評価票を自動生成しない。将来の `stage check` の退避対象は06のみ。
- `test/test_pipeline.py` は実フェーズとSDKにメモリ上のHTTP応答を与え、一括実行・各呼び出しでの失敗・不正な成果物・評価票生成/退避を検証する。第2節のオフラインテストに含まれる。

各呼び出し前後の `/api/v1/models` を保存し、QwenのみからGemmaのみへの切替と実ロード長を記録する。設定値を実ロード長の証拠に代えない。今回の実機手順・環境制約・証拠は [M4検証記録](../MILESTONES.md#evidence-m4)を参照する。M4の動作確認はM5の比較評価とは別に扱う。

## 11. M5 の比較採取

[比較計画](../docs/m5-comparison-plan.md)のもとで `test/compare_generation.py` を使う。LM Studioを専用運用し、量子化まで含む正確なモデルキーと `thinking: null` を設定しておく。

```powershell
.\.venv\Scripts\python.exe test/compare_generation.py prepare --study creations/m5-<日時> --config .env/m4-verification.json --evaluator ユーザ
.\.venv\Scripts\python.exe test/compare_generation.py execute --study creations/m5-<日時> --config .env/m4-verification.json
```

`prepare` は両モデルを順に明示ロードして実ロード設定を観測し、生成前の `plan.json` と `preflight.json` を保存する。既存のstudyディレクトリは上書きしない。`execute` は未実行の8試行を順に採取する。設定・コード・プロンプト・入力・既存成果物の変更やロード条件の不一致を検出すると停止する。API失敗時は成果物と台帳を残し、同じ試行を自動再生成しない。

`results.json` と `status.md` に状況・経過時間・計測内訳・本文リンクが出る。失敗・中断済みの試行は再度executeしても再実行せず、台帳に残す。再試行が必要なら理由付きの別計画とし、失敗を隠して成功例だけを選ばない。人手の `human_review.md` は再実行時も上書きしない。本文や中間成果物は無編集のまま、全採取後に人手評価を記入する。

環境制約で通常Pythonが使えない場合は、[M5記録](../MILESTONES.md#evidence-m5)の実際の実行手順・Python・依存バージョンを参照する。テスト方法と過去の成功記録を区別する。
