# Signal

Signalは、顧客との会話をリアルタイムで理解し、営業担当者へ次の質問や返答案を提案する営業支援アプリです。

## アーキテクチャ

- フロントエンド: Next.js / TypeScript
- バックエンドAPI: FastAPI / Python
- データベース: PostgreSQL
- ORM・マイグレーション: SQLAlchemy / Alembic
- Python環境・依存管理: uv

Next.jsはUIを担当し、データベース、認証、今後追加するAgentやRAGの処理はFastAPI側へ配置します。

## 必要な環境

- Node.js
- npm
- Python 3.12（uvによる自動インストールも可能）
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop

## セットアップ

フロントエンドの依存パッケージをインストールします。

```bash
npm install
```

Python環境とバックエンドの依存パッケージを作成します。

```bash
uv sync --project backend --all-groups
```

環境変数ファイルを作成します。

```bash
cp .env.example .env
```

作成した`.env`の`SEED_DEMO_PASSWORD`を、任意の開発用パスワードへ変更してください。

```dotenv
DATABASE_URL=postgresql+psycopg://signal:signal@localhost:5432/signal
SEED_DEMO_PASSWORD=replace-with-your-demo-password
BACKEND_CORS_ORIGINS=http://localhost:3000
NEXT_PUBLIC_API_URL=http://localhost:8000
```

`BACKEND_CORS_ORIGINS`には、FastAPIへのブラウザアクセスを許可するオリジンをカンマ区切りで指定できます。

## PostgreSQL

PostgreSQLをバックグラウンドで起動します。

```bash
docker compose up -d
docker compose ps
```

## データベースの準備

Alembicのマイグレーションを適用します。

```bash
npm run db:migrate
```

最初のAlembicマイグレーションは、以前のDrizzleマイグレーションで作成した同一構造のローカルDBをそのまま引き継げます。既存のテーブルやデータを削除する必要はありません。

PythonバックエンドからPostgreSQLへ接続できることを確認します。

```bash
npm run db:check
```

ログイン機能の開発に使うデモデータを投入します。

```bash
npm run db:seed
```

seedは再実行可能です。同じ組織、ユーザー、所属データを重複して作成しません。

### デモデータ

- 組織: `Signal Demo`
- 組織slug: `signal-demo`
- ユーザー: `demo@signal.local`
- ロール: `admin`
- パスワード: `.env`の`SEED_DEMO_PASSWORD`で設定した値

## 開発サーバー

2つのターミナルでフロントエンドとバックエンドを起動します。

```bash
npm run dev
```

```bash
npm run dev:api
```

- フロントエンド: [http://localhost:3000](http://localhost:3000)
- APIドキュメント: [http://localhost:8000/docs](http://localhost:8000/docs)
- DBヘルスチェック: [http://localhost:8000/health](http://localhost:8000/health)

## テストとコード品質

```bash
npm run lint
npm test
npm run lint:api
npm run format:api:check
npm run typecheck:api
npm run test:api
```

バックエンドの統合テストは実際のPostgreSQLを使用します。PostgreSQLを起動し、マイグレーションを適用してから実行してください。

## マイグレーションの追加

SQLAlchemyモデルを変更した後、新しいAlembicマイグレーションを生成します。

```bash
uv run --directory backend alembic -c alembic.ini revision --autogenerate -m "describe change"
```

生成されたSQLを確認してから`npm run db:migrate`で適用します。

## 主なコマンド

| コマンド | 用途 |
| --- | --- |
| `npm run dev` | Next.jsフロントエンドを起動する |
| `npm run dev:api` | FastAPIバックエンドを起動する |
| `npm run build` | Next.jsを本番用にビルドする |
| `npm run lint` | フロントエンドのESLintを実行する |
| `npm test` | フロントエンドのVitestテストを実行する |
| `npm run lint:api` | PythonバックエンドのRuffを実行する |
| `npm run format:api:check` | Pythonコードのフォーマットを確認する |
| `npm run typecheck:api` | Pythonバックエンドのmypyを実行する |
| `npm run test:api` | Pythonバックエンドの全テストを実行する |
| `npm run test:integration` | PostgreSQLを使う統合テストを実行する |
| `npm run db:migrate` | Alembicマイグレーションを適用する |
| `npm run db:check-schema` | モデルと適用済みスキーマの差分を確認する |
| `npm run db:check` | PythonからPostgreSQLへの接続を確認する |
| `npm run db:seed` | デモデータを投入する |
