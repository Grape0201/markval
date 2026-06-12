# PDF照合チェックツール 実装プラン

技術計算書（ファイルA）の入力値と、その出典文書（ファイルB）の数値が一致しているかをAIで照合し、承認済み項目をPDF上にチェックマークとして書き込むツール。

## 新規追加機能: カテゴリ指定による抽出と照合の絞り込み（トークン節約）

ユーザ指定の `category` 一覧に基づいてファイルA（計算書）およびファイルB（出典文書）からデータを抽出し、照合時に同一カテゴリ内のみに候補を絞り込むことで、LLM使用トークンの大幅な削減と照合精度の向上を実現します。

## User Review Required

> [!IMPORTANT]
> - 今回の改訂では、`pdfplumber`の代わりに`markitdown` + `pypdf`を用いたMarkdownテキストベースの構造化抽出と照合に舵を切ります。
> - PoCは2つのフェーズに分割して進めます：
>   - **PoC-1 (Pure Match)**: bboxやPDFのアノテーション（markup）は行わず、純粋にテキストベースでデータの構造化抽出と照合が行えるかを検証します。
>   - **PoC-2 (Bbox & Annotation)**: `pdfplumber`を用いてPDFからbbox（座標情報）を抽出し、PoC-1の照合結果と紐付けることで、PDF上にアノテーション（チェックマーク✓と出典注釈）を描画・出力する部分を検証します。
> - **データベース移行**: `source_items` および `check_items` テーブルに `category` カラムを追加するため、Alembicによるマイグレーションを実行します。
> - **デフォルトカテゴリ**: ユーザが明示的にカテゴリを指定しない場合、標準的な建築構造用のカテゴリ（`"固定荷重, 積載荷重, 積雪荷重, 風荷重, 地震荷重, 材料強度, その他"`）をデフォルトとして適用します。
> - **フロントエンドUI**: 計算書（ファイルA）のアップロード画面および出典文書（ファイルB）の登録画面に、「抽出カテゴリ設定（カンマ区切り）」の入力欄を追加し、ユーザが動的にカテゴリ群を指定できるようにします。

## Open Questions

> [!NOTE]
> カテゴリが部分一致または表記揺れした場合（例: "固定荷重" と "固定荷重（屋根）" など）、LLM側での分類をロバストにするため、カテゴリリストをプロンプトおよび Pydantic 構造化出力モデルのフィールド説明へ動的に注入します。現時点での懸念点やその他の希望カテゴリ分類があればご提示ください。

---

## システム構成

```
pdf-checker/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI エントリーポイント
│   │   ├── routers/
│   │   │   ├── file_a.py            # ファイルA処理 API
│   │   │   ├── file_b.py            # ファイルB処理・照合 API
│   │   │   └── match.py             # 照合処理 API
│   │   ├── services/
│   │   │   ├── extractor.py         # pdfplumber / markitdown による抽出ロジック
│   │   │   ├── matcher.py           # LangChain 経由の照合ロジック
│   │   │   └── annotator.py         # reportlab によるPDF注釈書き込み
│   │   ├── db/
│   │   │   ├── models.py            # SQLAlchemyモデル
│   │   │   └── database.py          # DB接続
│   │   └── static/                  # フロントエンド静的ファイル
│   │       ├── index.html           # メイン画面（SPA）
│   │       ├── style.css            # スタイルシート（Vanilla CSS、プレミアムデザイン）
│   │       └── app.js               # アプリケーションロジック
│   ├── pyproject.toml               # uv 管理 of Python packages
│   └── uv.lock                      # dependency lock
└── docker-compose.yml
```

---

## データベース設計

### テーブル: `source_documents`（ファイルBのメタデータ）

| カラム | 型 | 説明 |
|---|---|---|
| id | UUID | PK |
| filename | TEXT | ファイル名 |
| title | TEXT | 文書タイトル（例: JASS2024） |
| version | TEXT | 版・年度 |
| uploaded_at | DATETIME | 登録日時 |

### テーブル: `source_items`（ファイルBから抽出した数値・テキスト）

| カラム | 型 | 説明 |
|---|---|---|
| id | UUID | PK |
| document_id | UUID | FK → source_documents |
| page | INT | 抽出ページ番号 |
| label | TEXT | 項目名（例: 固定荷重） |
| value | FLOAT | 数値 |
| unit | TEXT | 単位（例: kN/m²） |
| context_text | TEXT | 前後の文脈テキスト |
| bbox | JSON | {x0, y0, x1, y1} (nullable: 描画用。PoC段階では省略) |
| category | TEXT | カテゴリ（例: 固定荷重、積載荷重等。絞り込み用） |

### テーブル: `check_sessions`（照合セッション）

| カラム | 型 | 説明 |
|---|---|---|
| id | UUID | PK |
| file_a_path | TEXT | ファイルAのパス |
| prompt_template_id | UUID | 使用したプロンプト |
| status | TEXT | pending / reviewed / exported |
| created_at | DATETIME | 作成日時 |

### テーブル: `check_items`（ファイルAから抽出したチェック項目）

| カラム | 型 | 説明 |
|---|---|---|
| id | UUID | PK |
| session_id | UUID | FK → check_sessions |
| label | TEXT | 項目名 |
| value | FLOAT | 数値 |
| unit | TEXT | 単位 |
| bbox | JSON | ファイルA上の位置 (nullable: 描画用。PoC段階では省略) |
| page | INT | ページ番号 |
| context | TEXT | 前後の文脈テキスト |
| source_hint | TEXT | 計算書に記載されている出典情報・参照先 |
| category | TEXT | カテゴリ（絞り込み用） |

### テーブル: `match_results`（照合結果）

| カラム | 型 | 説明 |
|---|---|---|
| id | UUID | PK |
| check_item_id | UUID | FK → check_items |
| source_item_id | UUID | FK → source_items（nullable） |
| confidence | FLOAT | 一致信頼度 0.0〜1.0 |
| status | TEXT | approved / rejected / pending |
| ai_reasoning | TEXT | AIの判定根拠テキスト |
| reviewed_by | TEXT | レビュアー名（任意） |

### テーブル: `prompt_templates`（プロンプトテンプレート）

| カラム | 型 | 説明 |
|---|---|---|
| id | UUID | PK |
| name | TEXT | テンプレート名（例: 構造計算_標準） |
| content | TEXT | プロンプト本文（変数: {{document_text}}） |
| industry | TEXT | 業種タグ（任意） |
| created_at | DATETIME | 作成日時 |

---

## API設計

### ファイルB系（抽出・DB・照合）

```
POST   /api/v1/source-documents          # ファイルBをアップロード・抽出・DB保存
  リクエスト (Formデータ):
    file: UploadFile
    title: str (任意)
    version: str (任意)
    categories: str (任意、カンマ区切り。デフォルト値あり)
  レスポンス:
    SourceDocumentResponse

GET    /api/v1/source-documents          # 登録済み文書一覧
DELETE /api/v1/source-documents/{id}    # 文書削除
```

### ファイルA系（抽出・セッション管理）

```
POST   /api/v1/sessions                  # ファイルAをアップロードしてセッション作成
  リクエスト (Formデータ):
    file: UploadFile
    prompt_template_id: uuid (任意)
    categories: str (任意、カンマ区切り。デフォルト値あり)
  レスポンス:
    CheckSessionResponse

GET    /api/v1/sessions/{id}/items       # 抽出されたチェック項目取得
GET    /api/v1/sessions/{id}/results     # 照合結果取得
PATCH  /api/v1/results/{id}             # 承認/除外 ステータス更新
  リクエスト: { "status": "approved" | "rejected" }

POST   /api/v1/sessions/{id}/export     # 承認済み項目をPDFに書き込んでダウンロード
```

---

## 処理フロー詳細

### ファイルB登録フロー

```
1. PDFおよびカテゴリリスト（categories）受信
2. pypdf でページ分割し、markitdown で各ページを Markdown テキストに変換
3. LangChain 経由で LLM に構造化出力を依頼
   → カテゴリ候補リストをプロンプトおよび schema に埋め込み、{ label, value, unit, context_text, page, category } のリストを返させる
4. DBに保存
```

### ファイルA処理フロー

```
1. PDFおよびカテゴリリスト（categories）受信 → セッション作成
2. pypdf でページ分割し、markitdown で各ページを Markdown テキストに変換
3. ユーザー選択のプロンプトテンプレートで LangChain 経由の LLM に依頼
   → チェック項目リスト { label, value, unit, page, context, category } を構造化出力
4. check_itemsテーブルに保存
5. 照合実行
```

### 照合フロー

```
1. check_itemのcategoryと一致するsource_items（同一カテゴリのデータのみ）を検索
2. 同一カテゴリのsource_itemsから類似度スコアの上位5件をコンテキストとして LangChain 経由の LLM に照合依頼
   → matched, confidence, reasoning, matched_source_page を返させる
3. 単位変換ロジックで数値を正規化してfinal_matchを確定
4. match_resultsに保存
```

---

## 技術スタック

| レイヤー | 採用技術 | 理由 |
|---|---|---|
| バックエンド | FastAPI (Python) + uv | 非同期・型安全、依存管理を高速化 |
| PDF抽出 | markitdown + pypdf | 構造化されたMarkdownテキスト・表抽出 (精度向上) |
| PDF書き込み | reportlab | 将来のPDFへのチェックマーク・注釈追加用 |
| AI照合 | LangChain + 各種LLM API (Gemini / Azure OpenAI) | プロバイダ差し替え、構造化出力 |
| フロントエンド | HTML5 + Vanilla CSS + JS (Alpine.js) | FastAPIから直接静的配信。ビルド手順がなく、開発が最もシンプル |
| コンテナ | Docker Compose | ローカル開発・本番共通 |

---

## 実装フェーズ

### Phase 1-1 — PoC-1 (Pure Match)
- [ ] File A/B: pypdf + markitdown で PDF ページごとに Markdown 抽出 -> 保存
- [ ] File A/B: LangChain + LLM 構造化出力で各項目のリスト (数値、単位、文脈、ページ番号、カテゴリ) を抽出 -> JSON 保存 (bbox座標は空)
- [ ] File A と File B の抽出結果を LLM (LangChain) を用いて照合・突き合わせ（カテゴリによる事前フィルタ適用） -> JSON 保存
- [ ] 照合結果を CSV に整理してエクスポートし、純粋な照合の精度を確認する

### Phase 1-2 — PoC-2 (Bbox & Annotation)
- [ ] `pdfplumber` を用いて、ファイル A の各チェック項目の出現箇所に対応する bbox（座標情報）を抽出する
- [ ] PoC-1 の照合結果と bbox 情報を紐付け、`reportlab` を用いてファイル A 上にチェックマーク（✓）と出典注釈を描画・アノテーションする
- [ ] 注釈書き込み済みの PDF を出力し、目視でアノテーションの位置と内容を確認する

### Phase 2 — バックエンド
- [ ] `uv` で FastAPI プロジェクト初期化
- [ ] DB設計・マイグレーション（alembicによる `category` カラムの追加）
- [ ] ファイルB登録API（categories を受け取り、カテゴリ指定付き抽出→DB保存）
- [ ] 照合API（/api/v1/match - カテゴリフィルタリングの実装）
- [ ] ファイルAセッション管理API
- [ ] PDF注釈出力API (bboxマッチング・描画)
- [ ] プロンプトテンプレートCRUD

### Phase 3 — フロントエンド (FastAPI静的マウント)
- [ ] `backend/app/static/` ディレクトリに、ファイルA/Bアップロード時の「カテゴリ」入力エリアを追加
- [ ] 抽出項目および照合結果画面にカテゴリ表示用のバッジを追加

---

## 注意事項・実装上のポイント

### カテゴリ指定によるトークンの節約
- 従来の全探索的マッチングから、カテゴリ単位のサブセット絞り込みへ移行することで、LLMへ候補として渡す不要データを大幅に削減し、API呼び出し時のトークン数およびコストを大幅に抑制します。
- カテゴリの分類はPDFテキスト抽出のLLM呼び出し段階で同時に行うため、追加のAPIコールは発生しません。
