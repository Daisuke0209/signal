import { drizzle } from "drizzle-orm/node-postgres";
import { Pool } from "pg";

import * as schema from "./schema";

const databaseUrl = process.env.DATABASE_URL;

if (!databaseUrl) {
  throw new Error("DATABASE_URL is required");
}

const globalForPostgres = globalThis as typeof globalThis & {
  signalPostgresPool?: Pool;
};

export const pool =
  globalForPostgres.signalPostgresPool ??
  new Pool({
    connectionString: databaseUrl,
  });

if (process.env.NODE_ENV !== "production") {
  globalForPostgres.signalPostgresPool = pool;
}

export const db = drizzle({
  client: pool,
  schema,
});