# GenkaiNovelWriter マイルストーン計画

仕様は `SPEC.md` を唯一の正とする。各マイルストーンの完了条件は「実行して確認できること」であり、ビルドやimportが通ることは完了条件ではない。

## 全体の順序

| M | 内容 | 着手条件 | 確定させる未確定事項 |
|---|---|---|---|
| M1 | 接続基盤・前提検証・ベースライン | なし | U2, U3, U4, U7(速度計測のみ) |
| M2 | 実行ディレクトリ・Concept・Structure | U3 確定 | なし |
| M3 | Writing(B'方式)・再開・Assemble | M2 完了、U2 確定 | U5 |
| M4 | Check | M3 完了 | U6 |
| M5 | フルスクラッチ・評価 | M4 完了 | U1, U7, U8 |

---

## M1: 接続基盤・前提検証・ベースライン

最もリスクが高いのは、LM Studio上で2モデルが想定どおり動くかどうかである。パイプラインの実装より先に確認する。

### 作業(コミット単位)

1. **リファクタ**: `util/gateway.py` をOpenAI互換クライアント1クラスに統合する。`LmStudioGateway` / `OpenRouterGateWay` を廃止する。Tavilyへのimportを除去する。ミュータブルなデフォルト引数(`history: list = []` など)を `None` に変える。
2. **機能**: `util/config.py` で `.env/backends.json` を読み、フェーズ名からモデル・思考設定を引けるようにする。
3. **機能**: `util/log.py` で、LLM呼び出しごとに `calls.jsonl` へ記録する(フェーズ、モデル、入力/出力トークン、所要時間)。
4. **機能**: `main.py baseline --input <file>` を実装する。
5. **検証スクリプト**: `test/verify_backend.py` を作成し、下記の検証を実行して結果を出力する。

### 検証項目

| 対象 | 検証内容 | 記録先 |
|---|---|---|
| U2 | Qwen・Gemmaそれぞれで、思考モードをリクエスト単位でオン/オフできるか。オフ時に `content` に思考タグが含まれないか | SPEC.md の U2 を確定事項に移す |
| U3 | Qwenで、SPEC.md のPlotスキーマを使った構造化出力を10回実行し、スキーマ違反の件数を数える | 同上 |
| U4 | Qwen → Gemma → Qwen の順に呼び出し、JITロードでモデルが切り替わるか、前のモデルが解放されるか | 同上 |
| U7 | 各モデルの生成速度(tok/s)を計測する | SPEC.md の U7 に実測値を追記 |

### 完了条件

- `baseline` コマンドを、ローカルのGemmaで `concrete_01.txt` と `vague_01.txt` について各2回実行し、`creations/baseline-*/baseline.md` が4件保存されている。
- `calls.jsonl` にトークン数と所要時間が記録されている。
- U2・U3・U4の検証結果がSPEC.mdに反映されている。
- `main.py` の実行経路でTavilyのキーファイルがなくても起動できる。

### 検証結果が否定的だった場合

| 結果 | 対応 |
|---|---|
| U2 不可(思考を切れない) | 思考タグを後処理で除去する方式に変え、SPEC.md を更新してから M3 に進む |
| U3 違反が多い | スキーマの簡略化、または Structure のモデル変更を検討する。SPEC.md を更新してから M2 に進む |
| U4 不可 | `lms` CLI で明示的にロード/アンロードする方式に変える |

---

## M2: 実行ディレクトリ・Concept・Structure

### 作業(コミット単位)

1. **機能**: `novel/run.py` を実装する。実行ディレクトリの作成、成果物パスの解決、退避処理(SPEC.md「退避」の表)を含む。
2. **機能**: `novel/schema.py` に新しいPlotスキーマを定義する。旧 `novel/plot.py` は削除する。
3. **機能**: Conceptフェーズと `prompts/concept/system.md` を実装する。`02_concept.md` のパーサ(指定要素の抽出)も含む。
4. **機能**: Concept照合(`prompts/concept/verify.md`、`02_concept_report.json`)を実装する。
5. **機能**: Structureフェーズと `prompts/structure/system.md` を実装する。リトライ、指定要素の転記・上書きも含む。
6. **機能**: Plot機械検査(`03_plot_report.json`)を実装する。
7. **機能**: `stage concept` / `stage structure` コマンドを実装する。

### 完了条件

- `concrete_01.txt` と `vague_01.txt` の両方で、`stage concept` → `stage structure` が通り、`02_concept.md`・`03_plot.json`・両レポートが出力される。
- `concrete_01.txt` の指定要素に、ジャンル(ドタバタラブコメ)と、「魔人到着 → 自力で再起 → 攻撃を受けて気絶」の順序が含まれている。
- `02_concept.md` を手で編集してから `stage structure` を再実行すると、編集内容が `03_plot.json` に反映され、旧成果物が `_archive/` に退避される。
- `03_plot.json` を手で壊すと、後続の実行がパースエラーで停止する(LLMで修復しない)。
- Plot機械検査が、意図的に仕込んだ未使用キャラ・未定義の場所・「または」を検出する。

---

## M3: Writing(B'方式)・再開・Assemble

着手条件: M2 完了、かつ U2 が確定していること。

### 作業(コミット単位)

1. **機能**: `novel/context.py` に、SPEC.md「Writing」の入力組み立て順を実装する。
2. **機能**: Writingフェーズと `prompts/writing/system.md` を実装する。
3. **機能**: `stage writing` と `write --run <dir> --from <k>` を実装する。
4. **機能**: Assemble(結合・字数集計・600字未満の警告)を実装する。
5. **削除**: `extract_tail` / `extract_head` / `check_border` / `elaboration` を削除する。

### 完了条件

- `concrete_01.txt` の実行ディレクトリで `stage writing` が最後まで通り、全シーンと `05_draft.md` が出力される。
- `calls.jsonl` で、最終シーンの入力トークン + 出力トークンがコンテキスト長(16384)に収まっていることを確認し、SPEC.md の U5 を確定する。
- `scene_02.md` を手で編集してから `write --from 3` を実行すると、シーン3以降が再生成され、シーン1・2は変更されず、旧シーン3以降が退避される。
- 各シーン本文に、見出し・「Scene Title」・思考タグが含まれていない。

---

## M4: Check

### 作業(コミット単位)

1. **準備**: 旧実装のNemotron出力(`creations/output-20260904-*`)と既知の問題一覧を `test/fixtures/nemotron_20260904/` に置く。既知の問題一覧は、壁打ちで洗い出した失敗表(要素欠落・設定矛盾・物理的破綻・出力汚染)を `expected.md` として保存する。
2. **機能**: 機械検査(contamination、length)を `novel/checks.py` に実装する。
3. **機能**: LLM検査(elements、consistency、physical)を項目別プロンプトで実装する。
4. **機能**: `06_check_report.md` の生成と `stage check` を実装する。
5. **検証スクリプト**: `test/measure_check.py` で、フィクスチャに対する検出結果を出力する。検出率の判定(既知の問題と一致するか)は人手で行う。

### 完了条件

- フィクスチャに対して、機械検査が「黒ish」と「Episode 1 はここで幕を閉じた」を検出する。
- フィクスチャに対して、Qwenでの検出率・誤検出数が記録されている。同じデータでGemmaにも検査させた結果も記録されている。
- 上記の結果から、SPEC.md の U6 を確定する(検査担当モデルを決める)。

---

## M5: フルスクラッチ・評価

### 作業(コミット単位)

1. **機能**: `run` コマンド(全フェーズの一括実行)を実装する。
2. **機能**: 実行ディレクトリに、指定要素リストを埋め込んだ人手評価用テンプレート `07_eval.md` を生成する。
3. **評価(コード変更なし)**: `concrete_01.txt` と `vague_01.txt` で `run` を各2回実行し、`07_eval.md` を記入する。M1のベースラインと比較する。

### 完了条件

- ローカルバックエンドで、`run` が両入力について最後まで通る。
- フルスクラッチ1回の所要時間が記録され、許容できるかをユーザが判断している(U7)。
- ベースラインとの比較結果が記録され、U1(パイプラインの有効性)とU8(成功基準の閾値)が確定している。

### U1 が否定された場合

パイプラインが一発生成を上回らなかった場合、改善区分の作業(プロンプト調整など)に進む前に、目的に対する手段を再検討する。評価結果から、どのフェーズで品質が落ちているかを成果物ごとに特定してから判断する。

---

## 範囲外(本計画では着手しない)

- UI
- 改変許容度の可変化
- 連載対応
- Tavily検索、GenkaiIllustrator連携
- 検査結果に基づく自動再生成
- 非陳腐性の改善策(複数案生成など)
