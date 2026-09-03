import "dotenv/config";

import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { after, test } from "node:test";

import { eq } from "drizzle-orm";

import { db, pool } from "../db/client";
import { sessions, users } from "../db/schema";
import {
  createSession,
  deleteSession,
  getValidSession,
} from "./session-store";
import { hashSessionToken } from "./session-token";

const DAY_MS = 24 * 60 * 60 * 1000;

after(async () => {
  await pool.end();
});

test("creates, validates, and deletes a session", async () => {
  let userId: string | undefined;
  let token: string | undefined;

  try {
    const [user] = await db
      .insert(users)
      .values({
        name: "Session Test User",
        email: `session-test-${randomUUID()}@signal.local`,
        passwordHash: "not-used-in-this-test",
      })
      .returning({
        id: users.id,
      });

    assert.ok(user);
    userId = user.id;

    const createdSession = await createSession(userId);
    token = createdSession.token;

    const [storedSession] = await db
      .select({
        id: sessions.id,
        tokenHash: sessions.tokenHash,
        expiresAt: sessions.expiresAt,
      })
      .from(sessions)
      .where(eq(sessions.userId, userId))
      .limit(1);

    assert.ok(storedSession);
    assert.notEqual(storedSession.tokenHash, token);
    assert.equal(storedSession.tokenHash, hashSessionToken(token));

    const remainingDuration =
      createdSession.expiresAt.getTime() - Date.now();
    assert.ok(remainingDuration > 29 * DAY_MS);
    assert.ok(remainingDuration <= 30 * DAY_MS);

    const validSession = await getValidSession(token);
    assert.ok(validSession);
    assert.equal(validSession.id, storedSession.id);
    assert.equal(validSession.userId, userId);

    await deleteSession(token);
    assert.equal(await getValidSession(token), null);
  } finally {
    if (token) {
      await deleteSession(token);
    }

    if (userId) {
      await db.delete(users).where(eq(users.id, userId));
    }
  }
});
