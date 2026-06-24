# PDF照合チェックツール (MarkVal)

技術計算書（ファイルA）の入力値と、その出典文書（ファイルB）の数値が一致しているかをAIで照合し、承認された項目をPDF上にチェックマークとして書き込むツールです。

## 主な機能

- **PDFテキスト構造化抽出 (ブロックID参照方式)**: Yomitoku OCR を用いた解析結果からブロック（段落・テーブル行）を構築し、ID付きテキストとして LLM に入力。LLM には ID のみを選択させることでハルシネーションを極小化しつつ、高精度な構造化データ抽出を実現。
- **マルチ・バリュータイプ抽出**: 数値データ（`numeric`）に加え、地盤種別や鋼材名などの名称データ（`name`）、数式（`formula`）の抽出にも対応。
- **二段階 Bbox 解決**: LLM が選択したブロック ID から粗い Bbox を特定したのち（Phase 1）、ブロック内の個別 Word レベルまで精密検索して位置を特定（Phase 2）。
- **カテゴリフィルタリング照合 (トークン節約)**: ユーザーが指定したカテゴリに基づいてデータを抽出し、同一カテゴリ内でのみ照合候補を絞り込むことで、LLM使用トークンの大幅な削減と照合精度の向上を実現。
- **AI照合ロジック**: LLM を用いて、計算書（ファイルA）と出典（ファイルB）の項目を突き合わせ、一致判定と根拠（AI Reasoning）を生成。
- **PDFアノテーション描画**: 承認されたチェック項目に対し、`reportlab` を用いてPDF上にチェックマーク（✓）と出典注釈を描画。

---

## ディレクトリ構成

```
markval/
├── src/
│   └── app/                        # FastAPI アプリケーションコード
│       ├── main.py                 # エントリーポイント
│       ├── core/                   # 共通処理・並行制御（セマフォ）等
│       ├── db/                     # SQLAlchemyモデルおよびデータベース接続定義
│       ├── routers/                # FastAPI ルートハンドラー (file_a, file_b, match, templates)
│       ├── services/               # ビジネスロジック
│       │   ├── yomitoku_models.py  # Yomitoku OCR Pydantic モデル定義
│       │   ├── block_builder.py    # OCR からブロック構造を構築
│       │   ├── bbox_resolver.py    # ブロック ID から座標解決 (Word精密検索)
│       │   ├── document_providers.py# OCRプロバイダー抽象 (YomitokuProvider)
│       │   ├── extractor.py        # LLM 構造化データ抽出パイプライン
│       │   ├── matcher.py          # 抽出パラメータ間の照合・スコアリング
│       │   ├── annotator.py        # PDF チェックマーク＆注釈描画
│       │   └── excel_exporter.py   # 照合結果 Excel エクスポート
│       └── static/                 # フロントエンド静的ファイル（SPA）
├── poc/
│   ├── poc-1/                      # Pure Match (テキスト照合) の PoC
│   ├── poc-2/                      # Bbox & Annotation (位置情報抽出・描画) の PoC
│   ├── poc-3/                      # Block ID Reference (ブロックID参照方式・マルチタイプ) の PoC
│   └── poc_data/                   # PoC 実行データの出力・検証用ディレクトリ
├── alembic/                        # Alembic によるDBマイグレーションスクリプト
├── alembic.ini                     # Alembic 設定ファイル
├── pyproject.toml                  # 統合された Python パッケージ定義 (uv管理)
├── uv.lock                         # パッケージロックファイル
├── markval.db                      # SQLite データベース（自動生成・.gitignore対象）
├── uploads/                        # アップロードファイル保存先（自動生成・.gitignore対象）
├── .env                            # 環境変数設定ファイル
├── .env.example                    # 環境変数設定サンプル
├── .gitignore                      # Git 除外設定
└── README.md                       # 本ドキュメント
```

---

## 技術スタック

- **バックエンド**: FastAPI (Python >= 3.12)
- **データベース**: SQLite / SQLAlchemy / Alembic (マイグレーション)
- **パッケージ・環境管理**: `uv`
- **PDF処理**: `markitdown` (Microsoft) / `pypdf` / `reportlab`
- **AI/LLM**: `LangChain` / `langchain-google-genai` (Gemini API)
- **フロントエンド**: HTML5 / Vanilla CSS / JavaScript (Alpine.js)

---

## セットアップ手順

### 1. 前提条件のインストール
Python パッケージ管理ツール `uv` がインストールされている必要があります。未インストールの場合は以下を実行してインストールしてください。

```bash
# macOS / Linux の場合
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. リポジトリの準備と環境変数の設定
`.env.example` をコピーして `.env` を作成し、必要な環境変数を設定します。

```bash
cp .env.example .env
```

## 環境変数一覧

`.env` で設定可能な主な環境変数は以下の通りです。

| 環境変数名 | 必須/任意 | 初期値 | 説明 |
|---|---|---|---|
| `GEMINI_API_KEY` | **必須** | - | Google Gemini API を利用するための API キー。 |
| `GEMINI_MODEL` | 任意 | `gemini-2.5-flash` | 利用する Gemini モデル。構造化抽出と照合に利用。 |
| `YOMITOKU_API_URL` | 任意 | `http://localhost:8080` | Yomitoku OCR API サーバーのエンドポイント。 |
| `AZURE_OPENAI_API_KEY` | 任意 | - | Azure OpenAI を利用する場合の API キー（Gemini 失敗時のフォールバック用）。 |
| `AZURE_OPENAI_ENDPOINT` | 任意 | - | Azure OpenAI サービスのエンドポイント。 |
| `AZURE_OPENAI_DEPLOYMENT_NAME`| 任意 | - | Azure OpenAI デプロイメント名。 |
| `AZURE_OPENAI_API_VERSION` | 任意 | `2024-02-15-preview` | Azure OpenAI API バージョン。 |

### 3. 依存関係のインストール
プロジェクトルートで以下を実行し、仮想環境の作成とライブラリのインストールを行います。

```bash
uv sync
```

### 4. データベースの初期化（マイグレーション）
Alembic を使用して SQLite データベースに必要なテーブルを作成します。

```bash
uv run alembic upgrade head
```

---

## 起動と実行方法

### Web アプリケーションの起動
開発サーバーを起動するには、以下のコマンドを実行します。

```bash
uv run uvicorn src.app.main:app --reload
```

起動後、ブラウザで [http://127.0.0.1:8000](http://127.0.0.1:8000) にアクセスすると、WebUI を利用できます。

---

## PoC（概念実証）スクリプトの実行

開発および性能検証用に使用された PoC パイプラインは `poc` ディレクトリ内に保管されています。

### PoC-1 (Pure Match: テキスト抽出・照合パイプライン)
```bash
bash poc/poc-1/run_all.sh
```
抽出テキストデータのみを用いた純粋な照合精度の検証を行います。結果は `poc/poc_data/` 以下に出力されます。

### PoC-2 (Bbox & Annotation: 位置情報マッピング・描画パイプライン)
```bash
bash poc/poc-2/run_all.sh
```
PDFから出現座標（bbox）を抽出し、照合結果に基づいてPDFへチェックマークと出典アノテーションを描画・出力する検証を行います。結果は `poc/poc_data/` 以下に出力されます。

### PoC-3 (Block ID Reference: ブロックID参照方式・マルチタイプ)
```bash
cd poc/poc-3 && bash run_all.sh --step1
# または LLM を用いたフル実行:
# cd poc/poc-3 && bash run_all.sh --step2-llm && bash run_all.sh --step3-4
```
ブロック ID 参照方式と二段階 Bbox 解決による、数値・名称両対応の位置特定と構造化抽出の検証を行います。

## テスト

```bash
PYTHONPATH=src uv run pytest  
```
