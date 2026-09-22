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

`creations/verify-<日時>/` に `verification.json`・`calls.jsonl`・各試行の出力が保存される。`schema` は10回試行し、スキーマ違反と API エラーを別々に数える。`switching` は Qwen → Gemma → Qwen の順に呼び、前後の `/api/v1/models` とメモリを記録する。前モデルが解放されているかは人手で判断する。

## 7. 実測後の記録

観測結果は `SPEC.md` の「M1 実機検証の記録」に書く。そこで確定できたものは未確定事項の表から消し、確定事項に D番号で移す。U2/U3/U4 は 2026-09-18 に D37/D38/D39 として確定済み。U7 は M5 まで未確定なので、速度は参考値として追記する。モデル名・量子化・コンテキスト長・LM Studio のバージョン・使用した思考パラメータも残す。プログラムが SPEC を自動更新することはない。
