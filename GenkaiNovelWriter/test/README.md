# テストと実機検証

以下は `GenkaiNovelWriter` ディレクトリで実行する。Python 3.10 以上、Pydantic 2 が必要。

## 1. 環境構築

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

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

観測結果は `SPEC.md` の「M1 実機検証の記録」に書く。そこで確定できたものは未確定事項の表から消し、確定事項に D番号で移す。U2/U3/U4 は 2026-09-18 に D37/D38/D39 として確定済み。U7 は M5 まで未確定なので、速度は参考値として追記する。モデル名・量子化・コンテキスト長・LM Studio のバージョン・使用した思考パラメータも残す。プログラムが SPEC を自動更新することはない。

## 8. M2 の実行(Concept・Structure)

LM Studio を起動し、`.env/backends.json` の `concept` / `structure` に Qwen を割り当てた状態で実行する。

```powershell
.\.venv\Scripts\python.exe main.py stage concept --input prompts/tests/concrete_01.txt
.\.venv\Scripts\python.exe main.py stage structure --run creations/<日時>
```

`stage concept` は `--input` で新しい実行ディレクトリを作り、`--run` は既存のディレクトリに対して実行する。どちらか一方を指定する。`stage structure` は `--run` のみ。

出力は `creations/<日時>/` に `00_input.txt`・`01_config.json`・`02_concept.md`・`02_concept_report.json`・`03_plot.json`・`03_plot_report.json`・`calls.jsonl`。

確認すること(MILESTONES.md の M2 完了条件)。

- `concrete_01.txt` と `vague_01.txt` の両方で、2つの stage が最後まで通る。
- `concrete_01.txt` の `02_concept.md` の「# 制約」にジャンル(ドタバタラブコメ)が、「# 出来事」に「魔人到着 → 自力で再起 → 攻撃を受けて気絶」の順序が含まれている。
- `02_concept.md` を手で編集してから `stage structure` を再実行すると、編集内容が `03_plot.json` に反映され、旧成果物が `_archive/<日時>/` に退避される。
- `03_plot.json` を手で壊してから `stage structure` を再実行すると、パースエラーで停止する(退避された旧 Plot は `_archive/` に残る)。
- `03_plot_report.json` が、意図的に仕込んだ未使用キャラ・未定義の場所・「または」・出来事の順序違反を検出する。`03_plot.json` を手で書き換えてから、機械検査だけを呼び出して確かめる。

`02_concept.md` の形式が崩れていた場合は、ファイルを残したままエラーで停止する。手で直してから `stage structure` に進める。`03_plot.json` がスキーマに適合しなかった場合は、3回試したあと最後の生出力が `03_plot_raw.txt` に残る。

## 9. M3 の実行(Writing・再開・Assemble)

通常の `.venv/Scripts/python.exe` は 2026-10-19 に Python 3.12.0・Pydantic 2.13.5・OpenAI SDK 3.14.1・httpx 0.28.1 で起動できることを確認した。以前の起動不能は現在再現しない。

実機実行前に、LM Studio 側で執筆モデルのロード時コンテキスト長を **16384** にする。設定ファイルの `context_length` は記録用で、ロード設定を変更しない。`thinking` は `null`、タイムアウトは M2 の実績に従い1800秒を使う。

```powershell
.\.venv\Scripts\python.exe main.py stage writing --run creations/20261001-234342 --timeout 1800
# scene_02.md を手で編集してから再開
.\.venv\Scripts\python.exe main.py write --run creations/20261001-234342 --from 3 --timeout 1800
```

- `stage writing` と `write --from 1` は `04_scenes/` 全体・05・06を退避して全シーンを執筆する。`--from k` はシーンk以降・05・06のみ退避し、前のシーンには書き込まない。
- 再開番号は1〜Plotのシーン数。範囲外の番号、壊れた Plot、再利用する本文の欠落・空ファイルは退避前に停止する。各シーン生成時に先行本文をファイルから全文読み直す。
- 生成完了ごとに `04_scenes/scene_NN.md` を保存する。全シーン成功後に `05_draft.md` を結合し、標準出力に空白・改行を除いた各シーン字数と合計字数を出す。600字未満の警告は標準エラーに出す。
- API エラー、空応答、途中打ち切りでは停止し、完成済みシーンは残す。失敗シーンから `write --from k` で再開する。入力の自動切り詰め・自動修復・自動再生成はしない。
- `calls.jsonl` の `phase: writing` と `scene` で呼び出しを特定する。最終シーンの `input_tokens + output_tokens` が16384以下かを確認して U5 の判断材料とする。API が失敗時に usage を返さない場合は `null` のまま残し、推定値を実測扱いしない。
- 各シーンの見出し・Scene Title・思考タグの混入、およびビートの指示文や役割名の不自然な流用を通読で確認する。Writing は本文を後処理で修正しない。機械的な汚染検査は M4 の作業。

ローカルの実クライアントは、最初の生成前に `/api/v1/models` で実際のロード状態を取得する。担当モデル以外の LLM インスタンスを `lms unload <id>` で解放し、解放後の状態を再確認してから生成する(D39)。`lms` が見つからない、状態を取得できない、解放できない場合は生成を始めず停止する。`local` は loopback の LM Studio を使う。`remote` ではモデル管理を行わない。

モデル一覧のキーと設定済み識別子が一致しない場合は、同じモデル・量子化であることを確認し、一覧にある正確なキーへ設定を合わせるか、`lms load <正確なキー> --identifier <設定済み識別子> --context-length 16384 --yes` で明示ロードする。モデルの自動代替は行わない。
