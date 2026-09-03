import { and, eq, gt } from "drizzle-orm";

import { db } from "../db/client";
import { sessions } from "../db/schema";
import { generateSessionToken, hashSessionToken } from "./session-token";

const SESSION_DURATION_MS = 30 * 24 * 60 * 60 * 1000;

export async function createSession(userId: string): Promise<{
  token: string;
  expiresAt: Date;
}> {
  const token = generateSessionToken();
  const tokenHash = hashSessionToken(token);
  const expiresAt = new Date(Date.now() + SESSION_DURATION_MS);

  await db.insert(sessions).values({
    userId,
    tokenHash,
    expiresAt,
  });

  return {
    token,
    expiresAt,
  };
}

export async function getValidSession(token: string): Promise<{
  id: string;
  userId: string;
  expiresAt: Date;
} | null> {
  const tokenHash = hashSessionToken(token);

  const [session] = await db
    .select({
      id: sessions.id,
      userId: sessions.userId,
      expiresAt: sessions.expiresAt,
    })
    .from(sessions)
    .where(
      and(
        eq(sessions.tokenHash, tokenHash),
        gt(sessions.expiresAt, new Date()),
      ),
    )
    .limit(1);

  return session ?? null;
}

export async function deleteSession(token: string): Promise<void> {
  const tokenHash = hashSessionToken(token);

  await db.delete(sessions).where(eq(sessions.tokenHash, tokenHash));
}
