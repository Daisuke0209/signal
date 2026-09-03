# Signal

Signalは、顧客との会話をリアルタイムで理解し、営業担当者へ次の質問や返答案を提案する営業支援アプリです。

## 必要な環境

- Node.js
- npm
- Docker Desktop

## セットアップ

依存パッケージをインストールします。

```bash
npm install
```

環境変数ファイルを作成します。

```bash
cp .env.example .env
```

作成した`.env`の`SEED_DEMO_PASSWORD`を、任意の開発用パスワードへ変更してください。

```dotenv
DATABASE_URL=postgres://signal:signal@localhost:5432/signal
SEED_DEMO_PASSWORD=replace-with-your-demo-password
```

## PostgreSQL

PostgreSQLをバックグラウンドで起動します。

```bash
docker compose up -d
```

起動状態を確認します。

```bash
docker compose ps
```

## データベースの準備

Git管理されているマイグレーションをPostgreSQLへ適用します。

```bash
npm run db:migrate
```

DrizzleからPostgreSQLへ接続できることを確認します。

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

```bash
npm run dev
```

[http://localhost:3000](http://localhost:3000)をブラウザで開きます。

## 主なコマンド

| コマンド | 用途 |
| --- | --- |
| `npm run dev` | 開発サーバーを起動する |
| `npm run build` | 本番用にビルドする |
| `npm run lint` | ESLintを実行する |
| `npm run db:check` | PostgreSQLへの接続を確認する |
| `npm run db:generate` | `schema.ts`からマイグレーションSQLを生成する |
| `npm run db:migrate` | 生成済みマイグレーションをDBへ適用する |
| `npm run db:seed` | デモデータを投入する |
| `npm run db:studio` | Drizzle Studioを起動する |