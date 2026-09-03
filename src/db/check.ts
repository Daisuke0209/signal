import "dotenv/config";

import { sql } from "drizzle-orm";

import { db, pool } from "./client";

async function main() {
  const result = await db.execute(sql`
    SELECT
      current_database() AS database_name,
      current_user AS user_name
  `);

  console.log("Database connection succeeded:");
  console.log(result.rows[0]);
}

main()
  .catch((error: unknown) => {
    console.error("Database connection failed:");
    console.error(error);
    process.exitCode = 1;
  })
  .finally(async () => {
    await pool.end();
  });