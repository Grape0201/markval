# PoC-3: ブロック ID 参照方式による抽出と座標特定

## 目的

現在の「LLM で数値を抽出 → PDF 内から同じ数値を正規表現で検索して Bbox を特定する」というパイプラインを改善し、**抽出対象を数値以外（名称・式）にも拡張**可能なアーキテクチャを検証する。

### 課題

- 現行方式は数値の正規表現マッチに依存しているため、「第二種」「SN400B」のようなテキスト値の位置特定ができない
- LLM に Bbox 座標を直接出力させると、存在しない座標のハルシネーションが発生する

### 解決策: ブロック ID 参照方式

OCR のテキストブロック（段落・テーブル行）に ID を振り、LLM には **ID だけを選択させる**。座標の生成は一切 LLM に任せない。

## アーキテクチャ

```
Yomitoku JSON ──→ [Step 1] ──→ ID付きブロックリスト ──→ [Step 2] ──→ 抽出結果
                  ブロック構築    + ID-Bbox 対応表        LLM 抽出     (source_block_ids)
                                                                         │
                                                                         ▼
                                                                    [Step 3]
                                                                    Bbox 解決
                                                                    Phase 1: ブロック Bbox
                                                                    Phase 2: Word 精密検索
                                                                         │
                                                                         ▼
                                                                    [Step 4]
                                                                    レポート出力
```

## ブロックの種別と ID 設計

### ブロック種別

| 種別 | ID フォーマット | OCR ソース | 粒度 |
|---|---|---|---|
| 段落 (paragraph) | `B001`, `B002`, ... | `paragraphs[].contents` | 段落単位 |
| テーブル行 | `T001-R1`, `T001-R2`, ... | `tables[].cells[]` を行でグルーピング | 行単位 |

- 段落は通し番号 `B001`〜 で付与。
- テーブルは**行単位**でグルーピング。セル単位では ID が爆発するため、同一行のセルをマージし `T001-R1` のように行 ID を付与する。
- 行 Bbox はセル Bbox のマージ（min x0, min y0, max x1, max y1）で算出。

### ID スコープ

LLM への入力はページ単位で行われるため、ID はページ内でユニークであれば十分。ページ番号プレフィックスは不要。

### LLM 入力フォーマット

```
[B001/paragraph] 第4章 固定荷重
[B002/paragraph] 4.1 概要
[B003/paragraph] 固定荷重は建物の自重であり、構造体·仕上げ材·設備等の重量を合算して求める。

【テーブル T001】
[T001-R1] | 部位 | 荷重(N/m²) | 備考 |
[T001-R2] | 折板葺き（断熱材あり） | 1,200 | 屋根 |
[T001-R3] | ALC板 t=100 | 600 | 外壁 |
```

## 抽出対象の拡張: value_type による多態化

```python
class ExtractedItem(BaseModel):
    label: str
    value_type: Literal["numeric", "name", "formula"]
    numeric_value: float | None = None   # 荷重値、係数 等
    text_value: str | None = None        # 地盤種別「第二種」、材料名「SN400B」等
    formula_value: str | None = None     # 数式（将来対応）
    unit: str | None = None
    context: str
    source_block_ids: list[str]          # ← ブロック ID 参照
    category: str
```

## 二段階 Bbox 戦略（粗→細）

ブロック Bbox は広すぎる場合があるため、Phase 2 で OCR の Word データを使って精密位置を特定する。

| Phase | 方法 | 対象 |
|---|---|---|
| Phase 1 (LLM) | `source_block_ids` → ID-Bbox 対応表からブロック Bbox を取得 | 全 value_type |
| Phase 2 (ルールベース) | ブロック内の Word から値を検索 | `numeric`: 数値マッチ / `name`(短文): テキスト一致 |

- `numeric`: ブロック内の Word を数値パースし、浮動小数点比較で一致する単語の Bbox を採用
- `name`（≤20文字）: 完全一致 → 部分一致 の優先順で Word を検索
- `name`（>20文字）/ `formula`: ブロック Bbox をそのまま採用（フォールバック）

## 実装

### ファイル構成

| ファイル | 役割 |
|---|---|
| `load_yomitoku_json.py` | Yomitoku OCR JSON の Pydantic モデル |
| `models.py` | 共有モデル（`ExtractedItem`, `BlockInfo`, `PageBlocks` 等） |
| `step1_build_blocks.py` | Yomitoku JSON → ID 付きブロックリスト + ID-Bbox 対応表 |
| `step2_extract_with_ids.py` | LLM 構造化抽出（`--dry-run` / `--load-responses` 対応） |
| `step3_resolve_bbox.py` | ブロック ID → Bbox 解決 + Phase 2 精密検索 |
| `step4_report.py` | CSV レポート + 検証サマリー出力 |
| `run_all.sh` | パイプライン実行スクリプト |

### 実行方法

```bash
# Step 1: ブロック構築（LLM 不要）
bash run_all.sh --step1

# Step 2: プロンプト生成のみ
bash run_all.sh --step2-dry

# Step 2: LLM レスポンスを手動保存後に読み込み
#   poc_data/poc3_response_{a,b}_p{1,2,3}.json に PageExtraction JSON を配置
bash run_all.sh --step2-load

# Step 2: LLM 直接呼び出し（GOOGLE_API_KEY 必要）
bash run_all.sh --step2-llm

# Step 3 + 4: Bbox 解決 + レポート
bash run_all.sh --step3-4
```

## 検証結果

サンプルデータ（構造計算書 3 ページ + 荷重指針 3 ページ）での検証結果。

### File A（構造計算書）

| メトリクス | 結果 |
|---|---|
| 抽出アイテム数 | 47 |
| ブロック ID 有効率 | **100%** (47/47) |
| Phase 2 精密 Bbox 成功率 | 68.1% (32/47) |

### File B（荷重指針）

| メトリクス | 結果 |
|---|---|
| 抽出アイテム数 | 62 |
| ブロック ID 有効率 | **100%** (62/62) |
| Phase 2 精密 Bbox 成功率 | 69.4% (43/62) |

### 抽出の内訳（File A）

数値・名称の両方を正しく抽出できている。

```
  p1 | name     | ID:✓ | 構造種別                → 鉄骨造
  p1 | numeric  | ID:✓ | 屋根 固定荷重             → 1200.0 N/m²
  p2 | numeric  | ID:✓ | 事務室 積載荷重 床用        → 2900.0 N/m²
  p2 | numeric  | ID:✓ | 標準せん断力係数 Co        → 0.2
  p2 | name     | ID:✓ | 地盤の種別               → 第二種
  p3 | name     | ID:✓ | 地表面粗度区分            → III
  p3 | name     | ID:✓ | 使用鋼材                → SN400B
  p3 | numeric  | ID:✓ | SN400B 降伏点           → 235.0 N/mm²
```

### 判明した課題と対策

#### LLM が ID にタイプ注釈を含める

LLM が `B002` ではなく `B002/paragraph` を返す場合がある（入力フォーマットの `[B002/paragraph]` を ID と誤認）。
→ `step3_resolve_bbox.py` に `_normalize_block_id()` を実装し、`/paragraph` 等のサフィックスを除去して対応済み。

#### Phase 2 精密 Bbox の未対応ケース

Phase 2 が成功しない約 30% のアイテムは以下のいずれか：
- `name` 型で値がブロック内の単語と一致しない（OCR のトークン化の差異）
- 数値が単位と結合した形で Word に格納されている（例: `1,780 N/m2` が 1 語）
- ブロック Bbox と Word Bbox の座標系にずれがある

これらのケースではブロック Bbox がフォールバックとして採用されるため、位置情報が完全に失われることはない。

## この方式のメリット

- **トークン数の大幅削減**: 座標情報をプロンプトから排除し、ブロック単位にまとめることで入力トークンを圧縮
- **抽出対象の拡張**: 数値だけでなく名称・種別もブロック ID で位置特定できる
- **ハルシネーションの防止**: LLM は座標を生成せず ID を選ぶだけ。ID 正規化により実質 100% の有効率を達成
- **テーブル構造の活用**: テーブル行単位の ID により、テーブルが多い構造計算書でもトークン効率と位置特定精度を両立
- **段階的な精度向上**: Phase 2 の Word 検索により、数値・短い名称はブロック内の単語レベルまで精密化

## 今後の展望

- `formula` 型への対応（LaTeX 形式での式抽出と位置特定）
- 本番パイプライン（`YomitokuProvider`）への統合
- Phase 2 精密検索の改善（OCR Word のトークン化差異への対応）
