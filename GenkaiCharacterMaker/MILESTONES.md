# GenkaiCharacterMaker 作業計画・確認記録

## 現在の状態

2026-10-31（日本時間）：初期版を実装し、専用環境へ配置。オフライン25件とllama-server実生成3経路を確認した。LM Studio実機と本人による操作感・創作品質の確認は残る。要件は [SPEC.md](SPEC.md) を参照する。

## 実装段階

| 段階 | 作業 | 対応する条件 | 状態 |
|---|---|---|---|
| M1 | 専用環境、基本項目と自由項目の編集画面・モデル、JSON保存・読込、Markdown・互換出力。LLMなしで一人の文書を扱う | AC-05～08、AC-10、AC-12、AC-13の項目操作 | 実装・自動検証済み |
| M2 | 接続設定、非同期通信、基本項目と登録済み自由項目の全体生成、応答検証、候補の適用・破棄、キャンセル | AC-01、AC-03、AC-04、AC-10、AC-13の操作ロック、AC-14 | 実装・自動検証済み |
| M3 | 基本項目・自由項目各一件の生成・再生成、変更対象制限、候補比較、未保存確認を通した一連の操作 | AC-01～04、AC-06、AC-13 | 実装・自動検証済み |
| M4 | LM Studio・llama-server実機確認、自由項目を含む創作例の評価、日常利用のGUI起動方法とREADME | AC-01～14 | llama-server確認済み。残件は下記 |

ユーザーの実装依頼に基づきM1から順に実装した。今後仕様を変える場合は該当条件と計画を同時に更新する。

## 初期実装と検証（2026-10-31、日本時間）

- 根拠：ユーザーの「実装を行ってください。特に問題が発生しない限りは順次実行」の指示に基づき、Python 3.12・PySide6・Pydantic 2と設計の初期版を採用して実装した。接続先の既定値は指定されたllama-serverに合わせた。
- 対象：基準HEAD `d2343afe6ae2cbd493c5853886ba6233e1522d45` ＋ 既存未コミット変更 ＋ GenkaiCharacterMakerの新規実装。既存NovelWriterのコード・スキーマ・環境を使用・変更していない。
- 配置先：`H:\GenkaiProduct\GenkaiCharacterMaker`。本製品専用の `.venv` を構築済み。`start.bat` で起動できる。
- 環境：Windows、Python 3.12.0、PySide6-Essentials 6.12.0、Pydantic 2.14.2。開発用環境ではPySide6フル版も導入したが、配置先はEssentialsのみでテストした。
- オフライン：配置先から `.venv\Scripts\python.exe -m unittest discover -s test -t . -v` を実行し **25件PASS**。基本項目・自由項目の対象限定適用、不正応答拒否、項目定義・順序保持、保存往復・保存失敗、旧文書、モデル一覧取得、通信中断・遅延応答・期限切れ、GUIの台詞・自由項目操作・候補破棄・保存失敗時の切替防止・不正ファイル時の保持・コピーを確認した。
- 実モデル：`test/verify_backend.py` を実行し、通常JSON指示・非ストリーミングで全体→背景→自由項目の生成がPASS。実際のEditor・Qt Network・応答検証・候補適用を使用し、対象外の完全一致とファイル保存・再読込・両出力を確認した。開発用作業コピーで実施し、証拠を配置先の `creations/verification/` へ保存した。
- サーバー：`http://127.0.0.1:8080/v1`、llama.cpp `b10703-0b5be7e4a`。モデル：Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced-IQ4_XS.gguf。
- 実生成時間：全体 158.75秒、背景 121.16秒、自由項目 26.20秒。
- 最初の実生成は2048トークンを推論だけで消費してlength終了。正本を変更せずエラーとして拒否できた。実測に基づき初期上限を8192、期限を300秒へ変更し、SPECと接続設定を更新した。自動再送は追加していない。
- 日本語表示：Qtの画面画像で基本項目・自由項目・候補比較を目視確認。WindowsのMeiryo UIを明示し、ヘッドレスQtでも日本語が表示されるようにした。生成中も閲覧・スクロール・文字列選択を維持する。
- 配置先の専用Pythonで通常のWindowsプラットフォームから起動し、終了コード0、`platform=windows`、`font=Meiryo UI` を確認した。日本語ラベルを含む実画面は `creations/verification/preview-native.png` に保存した。IME入力と高DPIでの操作は未確認。
- 構文・文書確認：Python17ファイルの構文を確認。新規ソース・文書29ファイルの空白エラーと文書リンクを確認し問題なし。追跡前の新規ファイルも個別にgit diff --no-index --checkで確認した。
- 証拠：`creations/verification/report.json`、`response-0.json`～`response-2.json`、生成JSON・Markdown・互換JSON、`preview-main.png`・`preview-custom.png`・`preview-review.png`。最初の失敗は `initial-length-report.json` と `initial-length-response.json` に分けて保持した。生成物はGit対象外。

| 条件 | 確認状況 |
|---|---|
| AC-01 | 一連の構成機能を実装。保存往復・生成適用・出力は自動実行で確認。人によるGUI通し操作は未確認 |
| AC-02～08 | オフライン・Qt UIテストおよび実モデルで主要経路を確認。候補確認中もスクロール可能 |
| AC-09 | llama-serverはPASS。LM Studio実機は未確認 |
| AC-10 | 接続不要の編集・保存・出力と非同期通信・キャンセルをテスト確認 |
| AC-11 | 生成例に「明るく人懐っこい」「自身の命への執着が極端に薄い」があり、背景再生成後も性格の値を保持。作者本人の品質評価は未実施 |
| AC-12 | 独立環境でテストPASS。NovelWriterは実行時にimportしない |
| AC-13～14 | GUI項目操作、個別更新、全体生成のID照合と順序保持をテスト確認 |

残る確認は、LM Studio実機、日本語IME・高DPIを含む本人の操作感と創作品質。自動テスト・画面画像の確認を本人の評価の代わりにはしない。次の作業は実際に `start.bat` から使い、改善点があれば調整すること。

## 設計時点の調査記録（履歴）

- 確認日：2026-10-30（日本時間）。環境：Windows、PowerShell、Python 3.12。
- 実体のある既存リポジトリー：`H:\GenkaiProduct`。Codexに登録された別の `C:\Users\foriv\Documents\ChatGPT\GenkaiProduct` は、確認時に内容がないディレクトリだった。
- 参照元HEAD：`d2343afe6ae2cbd493c5853886ba6233e1522d45` ＋ 調査時点の既存未コミット変更。HEADだけの仕様としては扱わない。
- 既存変更：NovelWriterのSPEC、MILESTONES、main、評価・フェーズ・gateway・requirements等の変更と、progress関連の未追跡ファイルがあった。この作業の変更対象は新規GenkaiCharacterMakerディレクトリのみ。
- 作業規約：GenkaiProduct直下のAGENTS.mdを確認。NovelWriterのSPEC全体を新規アプリへ適用せず、Characterの互換境界だけ参照した。
- 既存モデル：`GenkaiNovelWriter/novel/schema.py` の `Character` と `GenkaiNovelWriter/SPEC.md` の対応箇所を確認。五項目、厳密型、余分なキー拒否、台詞配列1件以上を確認した。
- 既存プロンプト：`GenkaiNovelWriter/prompts/structure/system.md` に指定要素を守る方針と口調の台詞例の指定があった。ただし、これはキャラクター作成専用Skillそのものではない。
- Skill探索範囲：GenkaiProduct、Documents/ChatGPT、ローカルCodex skillsの関連ファイル名。専用キャラクター作成Skillは確認できなかった。OpenWebUIの内部データにはアクセスしておらず、存在しないとは断定しない。
- 技術資料：SPECにリンクしたQt、LM Studio、llama.cppの公式資料を確認。実機のサーバーバージョン・モデルや実際のAPI互換性は未確認。

## 設計成果物の検証

### 2026-10-30 初回設計の確認記録

確認日：2026-10-30（日本時間）。対象は上記基準リポジトリーの既存Character定義と、今回の新規文書・手作成データ例。検証環境はPython 3.12.0、Pydantic 2.13.4、PowerShell。

- コマンド：作業チャットの `work/verify_design.py` を `python` で実行。JSON例2件の構文、UUID・UTC日時・項目構造、背景統合の一致、Markdown例との一致、ローカル文書リンク10件、AC定義12件を確認しPASS。
- 既存モデルへの照合：`novel/schema.py` を読み、ASTから `Character` クラスだけを抽出して検証。互換JSON例が通り、余分なキーと空台詞配列は拒否されることを確認。元ファイルへの書込やアプリ全体の実行はしていない。
- 文書検査：新規成果物6ファイルに `git diff --no-index --check -- NUL <file>` を実施し、空白エラーなし。Gitの改行変換予告は内容エラーではない。追跡前の新規ファイルなので、通常の `git diff --check` だけでなく個別に確認した。
- 独立レビュー：部分再生成、キャンセル、保存・互換境界をレビュー。生成候補の非空条件と、構造化出力が任意の追加候補であることを明確化した。

この記録は自由項目追加前の設計例に対する確認であり、変更後のAC-02・AC-04～08や追加条件の合格記録には流用しない。

### 2026-10-31 自由項目の設計反映

- 根拠：ユーザーが自由項目の構造化保持を希望し、具体案の提示後に「設計に反映してください」と指示した。初期版へ採用する方針をSPEC第1・2節に反映した。
- 対象：基準HEAD `d2343afe6ae2cbd493c5853886ba6233e1522d45` ＋ 既存未コミット変更 ＋ 今回のGenkaiCharacterMaker設計変更。NovelWriterの既存変更は今回の作業対象外。
- 更新範囲：SPECの画面・モデル・生成契約・出力・受け入れ条件、README、実装順序、保存用JSON・互換JSON・Markdownの三例。
- 保存形式：未リリースの版1を改訂。以前の例でcustom_fieldsが省略されている場合の読込方針を明記した。項目の増減で版番号を変えない。
- 条件との対応：AC-02・AC-04～08を拡張し、AC-13・AC-14を追加。これらのアプリ動作確認は未実施。M1～M4に担当範囲を割り当てた。
- 検証環境：Windows / PowerShell / Python 3.12.0 / Pydantic 2.13.4。実施日2026-10-31（日本時間）。
- 成果物検査：`python work/verify_design_custom_fields.py` を作業チャットのディレクトリで実行しPASS。JSON例2件、自由項目2件の型・IDと項目名の一意性、既存Characterクラスへの互換例照合、notes・Markdownと正本の値・順序の一致、相対リンク10件、AC定義14件を確認した。例は手作成であり、アプリの動作検証ではない。
- 文書差分：`git -c core.autocrlf=false diff --no-index --check -- work/custom-fields-before outputs/GenkaiCharacterMaker` で空白エラーなし。更新前6ファイルの控えは作業チャットの `work/custom-fields-before/`、検証手順は `work/verify_design_custom_fields.py` に保持した。これらは検証用の作業ファイルでありアプリ本体には追加していない。
- 独立レビュー：保存・生成・編集ロック・外部出力・受け入れ条件と計画の整合を確認した。指摘された見出し用エスケープの検証手順との差異を修正し、成果物検査を再実行してPASSした。

### 設計時点で未検証だった範囲（履歴）

- アプリ動作テスト：未実施（本体未実装）。
- ローカルLLM生成：未実施（今回は設計作業）。
- GUI表示・日本語IME・高DPI表示：未確認。
- 創作内容の評価：examplesは設計説明用の手作成例であり、モデル出力や品質合格の証拠ではない。

## 設計時点の確認事項（履歴）

- PySide6の画面サイズ、日本語入力、候補比較の読みやすさ。配布用パッケージのサイズは後段で判断する。
- 利用する各サーバーのバージョン・モデルID・構造化出力の形式。SPECのtimeoutやmax_tokensは初期値案であり、実測して調整する。
- 既存キャラクター作成Skillを利用できれば、創作方針を取り込み、具体的な評価例を更新する。
- 本人による創作品質と操作感の確認は未実施。今回の設計例だけで承認・完成扱いにしない。

今後の検証では、日付、対象コミットまたは基準コミット＋未コミット差分、環境、コマンド・操作、結果、証拠、未確認範囲を記録する。
