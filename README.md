# PDF照合チェックツール (MarkVal)

技術計算書（ファイルA）の入力値と、その出典文書（ファイルB）の数値が一致しているかをAIで照合し、承認された項目をPDF上にチェックマークとして書き込むツールです。

## 主な機能

- **PDFテキスト構造化抽出**: `markitdown` + `pypdf` or `Yomitoku` + LLM を用いて、表情報を含むPDFから高精度にテキストデータを抽出・構造化。
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
│       ├── services/               # ビジネスロジック（抽出、照合、PDF描画）
│       └── static/                 # フロントエンド静的ファイル（SPA）
├── poc/
│   ├── poc-1/                      # Pure Match (テキスト照合) の PoC
│   ├── poc-2/                      # Bbox & Annotation (位置情報抽出・描画) の PoC
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
`.env.example` をコピーして `.env` を作成し、必要な API キーを設定します。

```bash
cp .env.example .env
```

`.env` の中に Google Gemini API のキーを設定します。

```env
GEMINI_API_KEY=your_gemini_api_key_here
```

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

過去の開発時に使用された PoC パイプラインは `poc` ディレクトリ内に保管されています。

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

## テスト

```bash
PYTHONPATH=src uv run pytest  
```
