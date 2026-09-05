"use client";

import { FormEvent, useEffect, useState } from "react";
import {
  CurrentUser,
  getCurrentUser,
  login,
  logout,
} from "@/lib/auth-api";
import styles from "./page.module.css";

const DEMO_EMAIL = "demo@signal.local";

export default function Home() {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [email, setEmail] = useState(DEMO_EMAIL);
  const [password, setPassword] = useState("");
  const [isCheckingSession, setIsCheckingSession] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let isActive = true;

    async function restoreSession() {
      try {
        const currentUser = await getCurrentUser();
        if (isActive) {
          setUser(currentUser);
        }
      } catch {
        if (isActive) {
          setError("認証サーバーに接続できません。しばらくしてから再度お試しください。");
        }
      } finally {
        if (isActive) {
          setIsCheckingSession(false);
        }
      }
    }

    void restoreSession();

    return () => {
      isActive = false;
    };
  }, []);

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setIsSubmitting(true);

    try {
      const authenticated = await login(email, password);

      if (!authenticated) {
        setError("メールアドレスまたはパスワードが正しくありません。");
        return;
      }

      const currentUser = await getCurrentUser();
      if (currentUser === null) {
        throw new Error("The session was not available after login");
      }

      setUser(currentUser);
      setPassword("");
    } catch {
      setError("認証サーバーに接続できません。しばらくしてから再度お試しください。");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleLogout() {
    setError("");
    setIsSubmitting(true);

    try {
      await logout();
      setUser(null);
      setPassword("");
    } catch {
      setError("ログアウトできませんでした。もう一度お試しください。");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.brand}>
          <span className={styles.brandMark} aria-hidden="true">
            <span />
          </span>
          <span>Signal</span>
        </div>
      </header>

      <main className={styles.main}>
        <section className={styles.authCard} aria-live="polite">
          {isCheckingSession ? (
            <div className={styles.loadingState} role="status">
              <span className={styles.loadingIndicator} aria-hidden="true" />
              <h2>セッションを確認しています</h2>
            </div>
          ) : user ? (
            <div className={styles.accountState}>
              <div className={styles.cardHeader}>
                <h2>おかえりなさい</h2>
                <span className={styles.statusBadge}>
                  <span aria-hidden="true" /> 接続中
                </span>
              </div>

              <div className={styles.userProfile}>
                <div className={styles.avatar} aria-hidden="true">
                  {user.name.slice(0, 1).toUpperCase()}
                </div>
                <div>
                  <strong>{user.name}</strong>
                  <span>{user.email}</span>
                </div>
              </div>

              <div className={styles.sessionDetail}>
                <span>認証セッション</span>
                <strong>有効</strong>
              </div>

              {error ? (
                <p className={styles.error} role="alert">
                  {error}
                </p>
              ) : null}

              <button
                className={styles.secondaryButton}
                type="button"
                onClick={handleLogout}
                disabled={isSubmitting}
              >
                {isSubmitting ? "ログアウトしています…" : "ログアウト"}
              </button>
            </div>
          ) : (
            <form className={styles.loginForm} onSubmit={handleLogin}>
              <h2>Signalにログイン</h2>

              <div className={styles.field}>
                <label htmlFor="email">メールアドレス</label>
                <input
                  id="email"
                  name="email"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  autoComplete="email"
                  required
                />
              </div>

              <div className={styles.field}>
                <label htmlFor="password">パスワード</label>
                <input
                  id="password"
                  name="password"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="current-password"
                  required
                />
              </div>

              {error ? (
                <p className={styles.error} role="alert">
                  {error}
                </p>
              ) : null}

              <button
                className={styles.primaryButton}
                type="submit"
                disabled={isSubmitting}
              >
                {isSubmitting ? "ログインしています…" : "ログイン"}
              </button>

              <p className={styles.demoHint}>
                デモ環境: <code>{DEMO_EMAIL}</code>
              </p>
            </form>
          )}
        </section>
      </main>
    </div>
  );
}
