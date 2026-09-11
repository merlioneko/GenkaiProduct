# M1 テストと実機検証

現在の実装範囲は M1 です。実機検証はユーザが実施します。自動テストが成功しても、U2・U3・U4 は確定せず、M1 完了にもなりません。M2 以降には着手していません。

## 1. Python 環境と API 不要のテスト

以下は `GenkaiNovelWriter` ディレクトリで実行します。Python 3.10 以上、Pydantic 2 が必要です。この作業では Python 3.12 の `.venv` に `requirements.txt` の依存関係をインストールしています。

新しい環境で準備する場合:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

テストとヘルプ:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s test -t . -p 'test*.py' -v
.\.venv\Scripts\python.exe main.py --help
.\.venv\Scripts\python.exe test/verify_backend.py --help
```

`-t .` は必要です。`test/test.py` という旧手動スクリプトと `test` パッケージの名前の衝突を避けます。旧手動スクリプトは直接実行した場合だけ動作します。

テストは実際の OpenAI SDK にメモリ上の HTTP トランスポートを注入します。LM Studio・OpenRouter・Tavily への通信は行いません。設定エラー、思考設定の未指定、正常生成、空応答、途中打ち切り、接続失敗、コンテキストエラー、使用量の欠落、JSON Schema 違反、検証の試行回数、UTF-8 の成果物保存を確認します。

## 2. バックエンド設定

`config/backends.example.json` を参考に `.env/backends.json` を用意してください。実際の秘密設定ファイルは、この作業では作成・表示しません。

- `local.base_url`: LM Studio の OpenAI 互換エンドポイント。通常 `http://localhost:1234/v1`。
- `local.api_key`: 認証なしの構成では `lm-studio`。認証ありの場合は実際のトークン。
- `phases.*.model`: LM Studio 上の実際の識別子に置き換えます。例のモデル名は仮です。
- `baseline` は `writing` とモデル・思考設定を同一にします。不一致は実行前にエラーになります。
- `context_length`: 計測時の設定値。これを書くだけでは LM Studio のロード設定は変わりません。サーバー側も 16384 以上に設定し、実際のロード状態を確認してください。
- `remote` のキーは `local` 実行時には不要です。`--backend remote` は動作確認専用です。

旧構成で `.env` が**ファイル**になっている場合、同名ディレクトリは作れません。自動で移動・上書きはしません。既存設定を整理するか、無視対象の `.env.m1/backends.json` などへ保存し、各コマンドに `--config .env.m1/backends.json` を指定してください。新しい必須経路は `util/settings.py` や Tavily を読み込みません。

## 3. 思考モードの検証用設定 (U2)

`thinking` の API への対応付けは未確定です。コード内でオン／オフの方式を仮決定しません。`config/thinking-options.template.json` を公開可能な作業ファイルにコピーし、モデル名を合わせ、`on` と `off` の `null` を**検証するリクエスト本文の追加パラメータ**に置き換えてください。

例えば、サーバー側の仕様に基づいて `chat_template_kwargs.enable_thinking` を試す場合、次のように記述します。この例は試験候補であり、LM Studio や両モデルでの有効性を確認した設定ではありません。

```json
{
  "実際のQwenモデルID": {
    "on": {"chat_template_kwargs": {"enable_thinking": true}},
    "off": {"chat_template_kwargs": {"enable_thinking": false}}
  },
  "実際のGemmaモデルID": {
    "on": {"chat_template_kwargs": {"enable_thinking": true}},
    "off": {"chat_template_kwargs": {"enable_thinking": false}}
  }
}
```

モデルごとに違うパラメータを指定できます。各オブジェクトを SDK の `extra_body` として送信します。`model`・`messages`・出力形式などの上書きは拒否します。キーやトークンはこのファイルに入れないでください。

```powershell
.\.venv\Scripts\python.exe test/verify_backend.py --checks thinking --thinking-options config/thinking-options.json
```

`thinking-structure-on/off.json` と `thinking-writing-on/off.json` で、本文、思考タグ混入、別フィールドの思考内容を比較します。パラメータが無視される場合もあるため、HTTP 成功やタグがないことだけでは U2 成功と判定しません。LM Studio のログやテンプレート設定も併せて確認してください。

未設定なら U2 は `not_run` と記録されます。`baseline` は思考オフを黙って省略せず、設定エラーで停止します。検証スクリプトの U3/U4/U7 は、思考パラメータ未設定でもサーバー既定値で測定可能で、その場合 `calls.jsonl` の `thinking` は `null` になります。

## 4. 構造化出力・切り替え・速度 (U3/U4/U7)

```powershell
.\.venv\Scripts\python.exe test/verify_backend.py --checks schema switching speed
```

全項目とベースライン4件を実行する場合:

```powershell
.\.venv\Scripts\python.exe test/verify_backend.py --thinking-options config/thinking-options.json --baseline-suite
```

検証対象は常に設定の `local` です。各呼び出しのタイムアウトは既定600秒で、両CLIの `--timeout` で変更できます。SDK の自動リトライは無効です。U3 は失敗を含めてちょうど10回試行し、スキーマ違反と API/生成エラーを別々に数えます。APIエラーや U3 のスキーマ違反、選択した思考検証の未実施がある場合は終了コード1です。ロード・メモリの観測可否と U2/U4 の合格は、終了コードだけでは判断せずレポートを確認してください。

`creations/verify-<日時>/` に次を保存します。同じ秒の実行には連番を付け、既存成果物を上書きしません。

| ファイル | 内容 |
|---|---|
| `00_input.txt` | U3 の入力 |
| `plot_schema.json` | 今回送信した SPEC の Plot スキーマ |
| `verification.json` | 各試行の観測、件数、ロード状態、メモリ計測 |
| `thinking-*.json` | オン／オフの本文・分離された思考内容 |
| `schema-01.json`〜`schema-10.json` | 生の生成本文。JSON 不正でも保存。応答自体がない場合は生成されない |
| `switch-*.json` / `speed-*.json` | 切り替え・速度測定時の出力 |
| `calls.jsonl` | フェーズ、バックエンド、モデル、思考指定、トークン数、時間、成功／エラー種別 |

U4 は Qwen → Gemma → Qwen の順に生成し、前後に `/api/v1/models` でロード状態を取得します。Windows ではホストRAM、LM Studio関連プロセスのメモリ、GPUアダプターのメモリカウンターも採取します。取得できない項目は `unavailable` または空配列になり、成功扱いしません。GPUカウンターはアダプター全体なので、他のアプリの使用量も含みます。前モデルが解放され、同時ロードになっていないか、人手で判断してください。自動アンロードは行わないため、JIT/Auto-Evict の挙動そのものを観測できます。

速度は `output_tokens_per_second_end_to_end` に記録します。これは出力トークン数÷呼び出し全体の時間で、ロード・入力処理も含みます。サーバーが `stats.tokens_per_second` を返した場合は `server_tokens_per_second` に別途記録します。純粋なデコード速度と混同しないでください。使用量が返らなければ `null` になり、推定値で埋めません。空応答や打ち切りもログに残ります。例外の本文・APIキーはログに書きません。

U3 用モデルは `test/plot_schema.py` に隔離しています。M2 で正式な `novel/schema.py` を導入した際に共通化してください。旧大文字キーのスキーマは受理しません。

## 5. ベースラインを単独で実行

```powershell
.\.venv\Scripts\python.exe main.py baseline --input prompts/tests/concrete_01.txt --thinking-options config/thinking-options.json
.\.venv\Scripts\python.exe main.py baseline --input prompts/tests/vague_01.txt --thinking-options config/thinking-options.json
```

各入力を2回ずつ実行するか、上の `--baseline-suite` を使います。`creations/baseline-*/` ごとに `00_input.txt`・`baseline.md`・`calls.jsonl` を保存します。空応答・途中打ち切り・APIエラーでは `baseline.md` を作らず、入力とログを保持して停止します。思考タグの削除や自動修復は行いません。

## 6. 実測後の記録

以下を記入し、`SPEC.md` の U2/U3/U4 を確定、U7 に速度を追記してください。モデル名・量子化・コンテキスト長・LM Studio/ランタイムのバージョンと、使用した思考パラメータを一緒に残します。

| 項目 | 記入内容 |
|---|---|
| U2 | Qwen/Gemmaそれぞれの切り替え可否、思考内容の分離、本文への漏れ、採用する方式 |
| U3 | 10回中の正常件数、スキーマ違反件数、API/生成エラー件数 |
| U4 | ロード順、前モデル解放の有無、RAM/VRAMの観測値 |
| U7 | モデル別の速度、ロード込みかどうか |
| baseline | concrete/vague 各2回の保存先 |

U2/U4 の可否をプログラムが自動で確定したり、SPEC を書き換えたりすることはありません。

参照: [LM Studio Chat Completions](https://lmstudio.ai/docs/developer/openai-compat/chat-completions)、[構造化出力](https://lmstudio.ai/docs/developer/openai-compat/structured-output)、[ロード状態取得API](https://lmstudio.ai/docs/developer/rest/list)。
