# Devin セッションノート

このファイルはDevinとのセッションで決定した方針・調査結果・作業ターゲットを管理するメモ。

---

## 初回セットアップ方針

- `AGENTS.md` はリポジトリルートに存在しており、Devinが自動で読み込むため**追加設定なしで即使用可能**
- `.devin/config.json` は任意。毎回「許可しますか？」を省略したい場合のみ作成する
  ```json
  {
    "permissions": {
      "allow": ["Read(**)", "Exec(git)", "Exec(npm run)", "Exec(pytest)"]
    }
  }
  ```
- APIキー等の秘匿情報は `.devin/config.local.json`（gitignore済み）に書く

---

## プロジェクト概要

Apache Superset — オープンソースのBIツール（データ可視化プラットフォーム）

| レイヤー | 技術 |
|---------|------|
| バックエンド | Python / Flask + Flask-AppBuilder |
| ORM | SQLAlchemy |
| フロントエンド | React / TypeScript |
| UIライブラリ | Ant Design（`@superset-ui/core` 経由） |
| 状態管理 | Redux |
| テスト (PY) | pytest |
| テスト (TS) | Jest + React Testing Library |

### 主要ディレクトリ

```
superset/                # Pythonバックエンド
superset-frontend/src/   # Reactフロントエンド
  ├── components/        # 汎用コンポーネント
  ├── explore/           # チャートビルダー
  ├── dashboard/         # ダッシュボード
  └── SqlLab/            # SQLエディタ
superset-frontend/packages/superset-ui-core/  # UIコンポーネントライブラリ
tests/                   # Pythonテスト
docker-compose.yml       # ローカル環境起動用
```

---

## 調査した問題点（2026-07-04 時点）

### 1. 進行中のマイグレーション（途中で止まっている作業）

**フロントエンド TypeScript 化**
- `superset-frontend/src/` 全体に `: any` 型が 578箇所残っている
- `@ts-ignore` / `@ts-expect-error` が 126箇所ある
- AGENTS.md でも明記されている「やってはいけないパターン」

**テストフレームワーク移行**
- Cypress（E2E）が廃止予定でPlaywrightに移行中だが `cypress-base/` にテストが残っている
  - `editmode.test.ts`, `drilltodetail.test.ts`, `chart.test.js` など
- テストコード内で `describe()` ブロックを `test()` に書き換えるTODOが大量に残っている
  - 対象: **209ファイル**に `eslint-disable-next-line no-restricted-globals -- TODO: Migrate from describe blocks` が存在

**UUID マイグレーション**
- 埋め込みダッシュボードのUUID移行が未完了
- `security/manager.py`, `dashboards/filters.py` に `# TODO (embedded): remove this check once uuids are rolled out` が残っている

### 2. 廃止予定コードの滞留

| ファイル | 内容 |
|---------|------|
| `superset/viz.py` | `@deprecated(deprecated_in="3.0")` が40箇所以上。現在v5.x相当なので大幅遅延 |
| `superset/views/core.py` | `explore` / `explore_json` が `@deprecated(eol_version="5.0.0")` 付きで残存 |
| `superset/middleware/legacy_prefix_redirect.py` | `/superset/*` への308リダイレクトShim。v5.0.0 EOL予定 |
| `superset/reports/notifications/slack.py` | `SlackNotification` クラスを v6.0.0 で削除予定 |
| `superset/tasks/scheduler.py` | retention period の旧オプション形式サポートを v6.0 で削除予定（3箇所） |

### 3. セキュリティ・アクセス制御の未対応

- `superset/views/alerts.py` の冒頭: `# TODO: access control rules for this module`
  - ただし各メソッドには `@has_access` デコレータは付いている（ルートレベルの認証は実装済み）
  - SPA へのルート返却のみのビューなので過剰な制御は不要な可能性あり
- `superset/sqllab/sqllab_execution_context.py`: `# TODO validate db.id is equal to self.database_id`（バリデーション漏れ）

### 4. コード設計上の負債

| ファイル | 問題 |
|---------|------|
| `superset/utils/database.py` | DAO との重複コード |
| `superset/db_engine_specs/base.py` | `name` フィールドが冗長、`@memoize` 未適用など5箇所 |
| `superset/sql_lab.py` | クエリ結果のメタデータとデータが混在（Parquet分離のTODOあり） |
| `superset/semantic_layers/api.py` | sort/pagination を SQL 側に移動する必要あり |
| `superset-frontend/src/views/store.ts` | ダッシュボードとExploreのReducerが混在 |
| `superset-frontend/src/utils/localStorageHelpers.ts` | localStorage キーの命名規則統一が未完 |

---

## 推奨ターゲット：TimeTable テストの `describe` フラット化

### 概要

`src/visualizations/TimeTable/` 配下の11ファイルで、`describe()` ブロックを使っているために
ESLintの `no-restricted-globals` 警告が出ており、全箇所に `// eslint-disable-next-line` が書かれている。
AGENTS.md の指針（`test()` を使え、ネストを避けろ）に沿ってフラット化する。

### 対象ファイル（11ファイル）

```
src/visualizations/TimeTable/
├── utils/
│   ├── valueCalculations/valueCalculations.test.ts   (describe 5箇所)
│   ├── sparklineHelpers/sparklineHelpers.test.ts      (describe 6箇所)
│   ├── sparklineDataUtils/sparklineDataUtils.test.ts  (describe 1箇所)
│   ├── sortUtils/sortUtils.test.ts                    (describe 1箇所)
│   ├── rowProcessing/rowProcessing.test.ts            (describe 1箇所)
│   └── colorUtils/colorUtils.test.ts                  (describe 1箇所)
├── config/
│   ├── transformProps/transformProps.test.ts           (describe 1箇所)
│   └── controlPanel/controlPanel.test.ts              (describe 1箇所)
└── components/
    ├── ValueCell/ValueCell.test.tsx                   (describe 1箇所)
    ├── Sparkline/Sparkline.test.tsx                   (describe 1箇所)
    └── LeftCell/LeftCell.test.tsx                     (describe 1箇所)
```

### 作業内容

`describe('xxx', () => { test('yyy', ...) })` のパターンを
`test('xxx > yyy', ...)` のようにフラット化する。テストロジック自体は変えない。
eslint-disable コメントも合わせて削除する。

### 完了基準

1. 対象11ファイルから `eslint-disable-next-line no-restricted-globals` コメントが消えている
2. `cd superset-frontend && npm run test -- --testPathPattern="TimeTable"` が全テストパスする
3. テストの総数・内容が変わっていない（リファクタのみ）

### 工数見積もり

2〜3時間以内。パターンが単純なので機械的に対応可能。

---

## 自動フラット化システム（デモ用）

### 概要・目的

`describe` ブロックを含むテストファイルがプッシュされたとき、
GitHub Actions が Devin API を呼び出し、フラット化→テスト→PR 作成を自動実行するシステム。
**デモ用途**として設計（プロダクション上の懸念点は後述）。

### ファイル構成

```
.devin/
└── flatten-tests.json              # 対象パス・コマンド設定（git管理）

.github/workflows/
└── flatten-tests.yml               # GitHub Actions ワークフロー（git管理）

docker/flatten-tests/
├── flatten_tests/                  # Python パッケージ
│   ├── __init__.py
│   ├── models.py                   # pydantic モデル（Config, API レスポンス型）
│   ├── detector.py                 # describe ブロック検知ロジック
│   ├── devin_client.py             # Devin API クライアント（セッション起動・ポーリング）
│   ├── slack_client.py             # Slack 通知クライアント
│   └── main.py                     # エントリーポイント
├── tests/                          # pytest 単体テスト（31件）
│   ├── test_detector.py
│   ├── test_devin_client.py
│   └── test_slack_client.py
├── Dockerfile                      # alpine + bash/curl/git/jq（レガシー、将来削除予定）
├── entrypoint.sh                   # Bash 実装（レガシー、Python 版に移行済み）
├── pyproject.toml                  # uv プロジェクト設定
└── uv.lock                         # 依存ロックファイル

GitHub Secrets:
  DEVIN_API_KEY                     # Devin API キー（cog_ prefix）
  DEVIN_ORG_ID                      # Devin Organization ID（org- prefix）
  SLACK_WEBHOOK_URL                 # Slack Incoming Webhook URL
```

### ローカル実行（uv）

```bash
cd docker/flatten-tests

# DRY_RUN で API 呼び出しなしに動作確認
DEVIN_API_KEY="cog_dummy" \
DEVIN_ORG_ID="org-dummy" \
SLACK_WEBHOOK_URL="https://hooks.slack.com/dummy" \
TARGET_FILES="superset-frontend/src/visualizations/TimeTable/utils/sortUtils/sortUtils.test.ts" \
GITHUB_ACTOR="testuser" \
GITHUB_REPOSITORY="tishib2/superset" \
GITHUB_SHA="abc123" \
GITHUB_RUN_ID="99999" \
REPO_ROOT="$(git rev-parse --show-toplevel)" \
SKIP_LAUNCH_NOTIFICATION="1" \
DRY_RUN="1" \
uv run python -m flatten_tests.main

# テストを実行
uv run pytest -v
```

### 設定ファイル仕様

**`.devin/flatten-tests.json`**（git管理）
```json
{
  "targets": [
    "superset-frontend/src/visualizations/TimeTable"
  ],
  "test_command": "cd superset-frontend && npm run test -- --testPathPattern",
  "pr_branch_prefix": "auto/flatten-tests"
}
```

### フロー

```
開発者がコミット＆プッシュ
      ↓
GitHub Actions 発火（push イベント）
      ↓
[Job 1: detect-and-notify] (self-hosted runner)
1. 変更ファイルを取得（git diff）
2. flatten-tests.json の targets と照合
3. 対象ファイル内に describe が含まれるか確認
      ↓ (なければ終了)
4. Slack に即時通知（Run ID・対象ファイル・コミットリンク）

[Job 2: launch-devin] (self-hosted runner, detect-and-notify に依存)
5. uv run python -m flatten_tests.main を実行
6. Devin API v3 でセッション起動（最大3回リトライ）
   → 失敗: ワークフローを失敗終了
7. ポーリング（30秒間隔、最大20分）
   - status が exit/error/suspended になったら終了
   - pull_requests が1件以上になったら成功とみなして終了（running のまま待つ無駄を避ける）
   - タイムアウト時はセッションを明示的に terminate
8. Slack に完了通知（Run ID・結果・Devin セッションリンク）
      ↓
Devin がバックグラウンドで処理
  - リポジトリをクローン
  - 対象ファイルを describe → test にフラット化
  - npm test でパスを確認
  - [skip ci] を含むコミットメッセージで PR を作成
  - PR 作成後にセッションを終了
```

### Devin API 仕様（v3）

```
POST https://api.devin.ai/v3/organizations/{org_id}/sessions
Authorization: Bearer {api_key}

{
  "prompt": "..."
}
```

**注意**: `resumable` など追加パラメータを指定すると Organization 設定との競合で 400 エラーになる場合がある。`prompt` のみを送信するのが安全。

### Devin に渡すプロンプトのテンプレート

```
リポジトリ: {repo_url}

以下のテストファイルで describe() ブロックを Jest の推奨スタイルに従いフラット化してください。

対象ファイル:
{files}

ルール:
- describe('A', () => { test('B', ...) }) → test('A > B', ...) に変換
- ネストが深い場合は > で連結（例: test('A > B > C', ...)）
- テストのロジック・アサーションは一切変更しない
- eslint-disable-next-line no-restricted-globals コメントを削除する
- 変換後に {test_command} を実行し、全テストがパスすることを確認する
- テストが通ったら {pr_branch_prefix}/{timestamp} ブランチで PR を作成する
- PR のコミットメッセージには必ず [skip ci] を含める（CI を一時的にスキップするため）
- PR を作成したらタスクは完了。それ以上の作業は行わずセッションを終了すること
```

### エラーハンドリング方針

| 状況 | 対応 |
|------|------|
| API 呼び出し失敗（ネットワーク等） | 3回リトライ後、ワークフローを失敗終了（GitHub 上で通知） |
| Devin のテスト失敗 | PR は作成されず、ポーリングがタイムアウトして Slack に通知 |
| セッションが running のまま PR 作成済み | pull_requests フィールドを確認し、1件以上で成功とみなす |
| ポーリングタイムアウト（20分） | セッションを terminate し、Slack にタイムアウト通知 |

### Slack 通知の識別子設計

各通知ペア（開始・完了）を紐づけるための識別子として `GITHUB_RUN_ID` を採用している。

**検討した選択肢:**

| 方法 | 採用/不採用 | 理由 |
|------|-----------|------|
| `GITHUB_RUN_ID` | **採用** | 追加実装不要。リンク（GitHub Actions ページ）も貼れるため視認性が高い |
| カスタム UUID | 不採用 | `uuidgen` 等で生成可能だが、リンクが貼れないためユーザー体験が劣る |
| `GITHUB_SHA`（短縮） | 不採用 | 開始通知にすでにコミットリンクとして含まれており冗長 |
| タイムスタンプ | 不採用 | 開始・完了で値がズレる可能性があり、同一ペアの識別が不確実 |

Run ID はクリックすると該当の GitHub Actions 実行ページに直接飛べるため、
カスタム UUID より実用性が高いと判断した。

---

### プロダクション移行時に直す点（既知の制約）

- **変換処理の非決定性**: Devin API（LLM）による変換は毎回同じ結果を保証しない
  → 本番化するなら `jscodeshift` による AST ベースの codemod に置き換える
- **PR 乱立**: push 単位で PR が生まれるため、まとめて処理する仕組みが必要
  → 定期実行（schedule）に切り替えてバッチ処理するか、特定ブランチへの push のみをトリガーにする
