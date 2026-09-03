import "dotenv/config";

import { hash } from "bcryptjs";

import { db, pool } from "./client";
import { memberships, organizations, users } from "./schema";

const demoPassword = process.env.SEED_DEMO_PASSWORD;

if (!demoPassword) {
  throw new Error("SEED_DEMO_PASSWORD is required");
}

async function main(password: string) {
  const passwordHash = await hash(password, 12);

  await db.transaction(async (tx) => {
    const [organization] = await tx
      .insert(organizations)
      .values({
        name: "Signal Demo",
        slug: "signal-demo",
      })
      .onConflictDoUpdate({
        target: organizations.slug,
        set: {
          name: "Signal Demo",
        },
      })
      .returning({
        id: organizations.id,
      });

    const [user] = await tx
      .insert(users)
      .values({
        name: "Demo User",
        email: "demo@signal.local",
        passwordHash,
      })
      .onConflictDoUpdate({
        target: users.email,
        set: {
          name: "Demo User",
          passwordHash,
        },
      })
      .returning({
        id: users.id,
      });

    if (!organization || !user) {
      throw new Error("Failed to create demo data");
    }

    await tx
      .insert(memberships)
      .values({
        organizationId: organization.id,
        userId: user.id,
        role: "admin",
      })
      .onConflictDoUpdate({
        target: [
          memberships.organizationId,
          memberships.userId,
        ],
        set: {
          role: "admin",
        },
      });
  });

  console.log("Demo data seeded:");
  console.log("- organization: signal-demo");
  console.log("- user: demo@signal.local");
  console.log("- role: admin");
}

main(demoPassword)
  .catch((error: unknown) => {
    console.error("Failed to seed demo data:");
    console.error(error);
    process.exitCode = 1;
  })
  .finally(async () => {
    await pool.end();
  });