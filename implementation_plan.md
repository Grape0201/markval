# PDF照合チェックツール 実装プラン

技術計算書（ファイルA）の入力値と、その出典文書（ファイルB）の数値が一致しているかをAIで照合し、承認済み項目をPDF上にチェックマークとして書き込むツール。

## User Review Required

> [!IMPORTANT]
> - 今回の改訂では、`pdfplumber`の代わりに`markitdown` + `pypdf`を用いたMarkdownテキストベースの構造化抽出と照合に舵を切ります。
> - PoCは2つのフェーズに分割して進めます：
>   - **PoC-1 (Pure Match)**: bboxやPDFのアノテーション（markup）は行わず、純粋にテキストベースでデータの構造化抽出と照合が行えるかを検証します。
>   - **PoC-2 (Bbox & Annotation)**: `pdfplumber`を用いてPDFからbbox（座標情報）を抽出し、PoC-1の照合結果と紐付けることで、PDF上にアノテーション（チェックマーク✓と出典注釈）を描画・出力する部分を検証します。

## Open Questions

> [!NOTE]
> 現時点で特筆すべきオープンな質問はありませんが、PoC結果を見て必要に応じて照合の信頼度判定ルールや抽出粒度のチューニングを検討します。

---

## システム構成

```
pdf-checker/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI エントリーポイント
│   │   ├── routers/
│   │   │   ├── file_a.py            # ファイルA処理 API
│   │   │   └── file_b.py            # ファイルB処理・照合 API
│   │   ├── services/
│   │   │   ├── extractor.py         # pdfplumber による抽出ロジック
│   │   │   ├── matcher.py           # LangChain 経由の照合ロジック
│   │   │   └── annotator.py         # reportlab によるPDF注釈書き込み
│   │   ├── db/
│   │   │   ├── models.py            # SQLAlchemyモデル
│   │   │   └── database.py          # DB接続
│   │   └── static/                  # フロントエンド静的ファイル
│   │       ├── index.html           # メイン画面（SPA）
│   │       ├── style.css            # スタイルシート（Vanilla CSS、プレミアムデザイン）
│   │       └── app.js               # アプリケーションロジック（Alpine.js / Petite-Vue 等を使用）
│   ├── pyproject.toml               # uv 管理の Python パッケージ定義
│   └── uv.lock                      # 依存関係ロック
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
GET    /api/v1/source-documents          # 登録済み文書一覧
DELETE /api/v1/source-documents/{id}    # 文書削除

POST   /api/v1/match                     # 照合実行
  リクエスト:
    {
      "session_id": "uuid",
      "items": [
        { "label": "固定荷重", "value": 9.81, "unit": "kN/m²", "bbox": {...}, "page": 3 }
      ]
    }
  レスポンス:
    {
      "results": [
        {
          "check_item_id": "uuid",
          "matched": true,
          "confidence": 0.97,
          "source": { "doc_title": "JASS2024", "page": 14, "context_text": "..." },
          "ai_reasoning": "単位換算後に数値が一致"
        }
      ]
    }
```

### ファイルA系（抽出・セッション管理）

```
POST   /api/v1/sessions                  # ファイルAをアップロードしてセッション作成
GET    /api/v1/sessions/{id}/items       # 抽出されたチェック項目取得
GET    /api/v1/sessions/{id}/results     # 照合結果取得
PATCH  /api/v1/results/{id}             # 承認/除外 ステータス更新
  リクエスト: { "status": "approved" | "rejected" }

POST   /api/v1/sessions/{id}/export     # 承認済み項目をPDFに書き込んでダウンロード
```

### プロンプトテンプレート管理

```
GET    /api/v1/prompt-templates         # テンプレート一覧
POST   /api/v1/prompt-templates         # 新規作成
PUT    /api/v1/prompt-templates/{id}    # 編集
DELETE /api/v1/prompt-templates/{id}    # 削除
```

---

## 処理フロー詳細

### ファイルB登録フロー

```
1. PDF受信
2. pypdf でページ分割し、markitdown で各ページを Markdown テキストに変換
3. LangChain 経由で LLM に構造化出力を依頼
   → { label, value, unit, context_text, page } のリストを返させる (bboxは一旦除外)
4. DBに保存
```

### ファイルA処理フロー

```
1. PDF受信 → セッション作成
2. pypdf でページ分割し、markitdown で各ページを Markdown テキストに変換
3. ユーザー選択のプロンプトテンプレートで LangChain 経由の LLM に依頼
   → チェック項目リスト { label, value, unit, page, context } を構造化出力
4. check_itemsテーブルに保存
5. 照合実行
```

### 照合フロー

```
1. source_itemsから検索
2. 上位5件をコンテキストとして LangChain 経由の LLM に照合依頼
   → matched, confidence, reasoning, matched_source_page を返させる
3. 単位変換ロジックで数値を正規化してfinal_matchを確定
4. match_resultsに保存
```

### PDF注釈出力フロー (オプション / 将来的な拡張)

```
1. status=approvedのmatch_resultsを取得
2. (将来フェーズ) pdfplumber 等でファイルAの該当項目の出現箇所のbbox座標を特定
3. reportlab でチェックマーク（✓）を描画
4. 注釈済みPDFをダウンロード提供
```

---

## 技術スタック

| レイヤー | 採用技術 | 理由 |
|---|---|---|
| バックエンド | FastAPI (Python) + uv | 非同期・型安全、依存管理を高速化 |
| PDF抽出 | markitdown + pypdf | 構造化されたMarkdownテキスト・表抽出 (精度向上) |
| PDF書き込み | reportlab | 将来のPDFへのチェックマーク・注釈追加用 |
| AI照合 | LangChain + 各種LLM API (Gemini / Azure OpenAI) | プロバイダ差し替え、構造化出力 |
| フロントエンド | HTML5 + Vanilla CSS + JS (Alpine.js / Petite-Vue) | FastAPIから直接静的配信。ビルド手順がなく、開発が最もシンプル |
| コンテナ | Docker Compose | ローカル開発・本番共通 |

---

## 実装フェーズ

### Phase 1-1 — PoC-1 (Pure Match)
- [ ] File A/B: pypdf + markitdown で PDF ページごとに Markdown 抽出 -> 保存
- [ ] File A/B: LangChain + LLM 構造化出力で各項目のリスト (数値、単位、文脈、ページ番号) を抽出 -> JSON 保存 (bbox座標は空)
- [ ] File A と File B の抽出結果を LLM (LangChain) を用いて照合・突き合わせ -> JSON 保存
- [ ] 照合結果を CSV に整理してエクスポートし、純粋な照合の精度を確認する

### Phase 1-2 — PoC-2 (Bbox & Annotation)
- [ ] `pdfplumber` を用いて、ファイル A の各チェック項目の出現箇所に対応する bbox（座標情報）を抽出する
- [ ] PoC-1 の照合結果と bbox 情報を紐付け、`reportlab` を用いてファイル A 上にチェックマーク（✓）と出典注釈を描画・アノテーションする
- [ ] 注釈書き込み済みの PDF を出力し、目視でアノテーションの位置と内容を確認する

### Phase 2 — バックエンド
- [ ] `uv` で FastAPI プロジェクト初期化
- [ ] `uv add` で backend 依存関係を追加 (markitdown等)
- [ ] DB設計・マイグレーション（alembic）
- [ ] ファイルB登録API（markitdown による抽出→DB保存）
- [ ] 照合API（/api/v1/match）
- [ ] ファイルAセッション管理API
- [ ] PDF注釈出力API (bboxマッチング・描画)
- [ ] プロンプトテンプレートCRUD

### Phase 3 — フロントエンド (FastAPI静的マウント)
- [ ] `backend/app/static/` ディレクトリを作成し、FastAPIで静的ファイル配信を有効化 (`app.mount()`)
- [ ] `index.html`, `style.css`, `app.js` の基礎枠作成（Alpine.js / Petite-Vue を CDN 経由で導入）
- [ ] ファイルAアップロード画面の作成
- [ ] プロンプトテンプレート編集UIの作成
- [ ] 照合結果レビュー画面（承認/除外）の作成
  - チェック項目と出典箇所を並べて表示
  - 信頼度スコアの可視化
- [ ] ファイルBのDB管理画面の作成
- [ ] 注釈済みPDFダウンロード機能のUI紐付け

### Phase 4 — 精度改善
- [ ] 単位変換ロジック（kN/kgf/N、m/mm等）
- [ ] スキャンPDF対応（PaddleOCR連携 / markitdown OCR対応）
- [ ] 「この照合ペアを自動承認」学習機能
- [ ] 照合結果のCSVレポート出力

---

## 注意事項・実装上のポイント

### PDF抽出
- `pdfplumber` によるピクセル単位・行単位の抽出に依存せず、`pypdf` でページ単位に分割した上で `markitdown` を用いて Markdown テキスト化する
- Markdown化することで、PDF内の表構造や段落構成、ヘッダー・フッター等のノイズをLLMが正しく解釈しやすくなり、抽出精度が劇的に向上する
- テキストが極端に少ない場合はスキャンPDFと判定し、OCRフラグを立てる (markitdown に OCR 設定を渡す)

### 数値照合
- 数値は文字列のまま比較せず、floatに正規化してから比較する
- 単位変換テーブルを持ち、LLMの判定前に正規化する
- 指数表記（1.0×10³）と小数表記（1000）を同一視する処理を入れる

### LangChain / LLM プロンプト設計
- LLM 呼び出しは LangChain の抽象化レイヤー経由で行い、provider を差し替え可能にする
- 構造化出力は LangChain の structured output を使い、JSONスキーマを厳密に定義する
- 照合プロンプトには「一致・不一致の根拠テキストを必ず含めること」を明示する
- コンテキスト長節約のため、必要に応じて照合をバッチ処理する

### ローカル開発コマンド
- バックエンドは `uv run` を使って起動・実行する
- 依存追加と更新は `uv add` / `uv lock` を使う
- フロントエンドはFastAPIの起動に同梱されるため、追加の起動コマンドやビルド手順は不要

### セキュリティ
- アップロードファイルはサニタイズし、パストラバーサル対策をとる
- APIキーは環境変数で管理（`.env`ファイル、Dockerシークレット）
- 技術計算書は機密情報を含む場合があるため、ファイルの保存期間ポリシーをREADMEに明記する
