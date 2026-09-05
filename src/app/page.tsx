"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import {
  addMessage,
  Conversation,
  ConversationDetail,
  createConversation,
  CurrentUser,
  getConversation,
  getCurrentUser,
  listConversations,
  login,
  logout,
} from "@/lib/auth-api";
import {
  captureFailure,
  startAudioCapture,
  stopStream,
} from "@/lib/audio-capture";
import styles from "./page.module.css";

const DEMO_EMAIL = "demo@signal.local";

export default function Home() {
  const [user, setUser] = useState<CurrentUser | null>(null),
    [email, setEmail] = useState(DEMO_EMAIL),
    [password, setPassword] = useState(""),
    [checking, setChecking] = useState(true),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [items, setItems] = useState<Conversation[]>([]),
    [conversation, setConversation] = useState<ConversationDetail | null>(null),
    [side, setSide] = useState<"customer" | "sales_rep">("sales_rep"),
    [content, setContent] = useState("");
  const capture = useRef<Awaited<ReturnType<typeof startAudioCapture>> | null>(
    null,
  );
  const [captureState, setCaptureState] = useState("停止中");
  const [isCapturing, setIsCapturing] = useState(false);
  function stopCapture() {
    stopStream(capture.current?.displayStream ?? null);
    stopStream(capture.current?.microphoneStream ?? null);
    capture.current = null;
    setIsCapturing(false);
    setCaptureState("停止中");
  }
  async function beginCapture() {
    setError("");
    setBusy(true);
    try {
      capture.current = await startAudioCapture();
      setIsCapturing(true);
      capture.current.displayStream
        .getAudioTracks()[0]
        ?.addEventListener("ended", () => {
          stopCapture();
          setError("共有音声が終了しました。");
        });
      capture.current.microphoneStream
        .getAudioTracks()[0]
        ?.addEventListener("ended", () => {
          stopCapture();
          setError("マイク音声が終了しました。");
        });
      setCaptureState("共有音声・マイクを取得中");
    } catch (captureError) {
      const reason = captureFailure(captureError);
      setError(
        reason === "missing-tab-audio"
          ? "共有したタブに音声がありません。タブ音声を共有してください。"
          : reason === "permission-denied"
            ? "共有またはマイクの権限が許可されませんでした。"
            : "音声共有がキャンセルされました。",
      );
      stopCapture();
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => () => stopCapture(), []);
  async function load() {
    const conversations = await listConversations();
    setItems(conversations);
    if (conversations[0])
      setConversation(await getConversation(conversations[0].id));
  }
  useEffect(() => {
    void (async () => {
      try {
        const me = await getCurrentUser();
        setUser(me);
        if (me) await load();
      } catch {
        setError("情報を読み込めませんでした。接続を確認してください。");
      } finally {
        setChecking(false);
      }
    })();
  }, []);
  async function signIn(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (!(await login(email, password))) {
        setError("メールアドレスまたはパスワードが正しくありません。");
        return;
      }
      const me = await getCurrentUser();
      setUser(me);
      if (me) await load();
    } catch {
      setError("認証サーバーに接続できません。");
    } finally {
      setBusy(false);
    }
  }
  async function select(id: string) {
    setBusy(true);
    try {
      setConversation(await getConversation(id));
    } catch {
      setError("会話を読み込めませんでした。");
    } finally {
      setBusy(false);
    }
  }
  async function start() {
    if (!user?.organizations[0]) {
      setError("利用できる組織がありません。");
      return;
    }
    setBusy(true);
    try {
      const created = await createConversation(user.organizations[0].id);
      setItems((old) => [created, ...old]);
      setConversation(await getConversation(created.id));
    } catch {
      setError("会話を開始できませんでした。");
    } finally {
      setBusy(false);
    }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!conversation || !content.trim()) return;
    setBusy(true);
    try {
      await addMessage(conversation.id, {
        speaker_label: side === "sales_rep" ? "自分" : "通話相手",
        side,
        content,
      });
      setContent("");
      setConversation(await getConversation(conversation.id));
    } catch {
      setError("発言を追加できませんでした。");
    } finally {
      setBusy(false);
    }
  }
  async function signOut() {
    setBusy(true);
    setError("");
    try {
      await logout();
      stopCapture();
      setUser(null);
      setConversation(null);
      setItems([]);
    } catch {
      setError("ログアウトできませんでした。もう一度お試しください。");
    } finally {
      setBusy(false);
    }
  }
  if (checking)
    return <main className={styles.center}>セッションを確認しています…</main>;
  if (!user)
    return (
      <main className={styles.login}>
        <form onSubmit={signIn}>
          <h1>Signalにログイン</h1>
          <label>
            メールアドレス
            <input
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              type="email"
            />
          </label>
          <label>
            パスワード
            <input
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              type="password"
            />
          </label>
          {error && <p role="alert">{error}</p>}
          <button disabled={busy}>ログイン</button>
        </form>
      </main>
    );
  return (
    <main className={styles.workspace}>
      <header>
        <strong>Signal</strong>
        <span>{user.name}</span>
        <button onClick={() => void signOut()} disabled={busy}>
          ログアウト
        </button>
      </header>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <div className={styles.columns}>
        <aside>
          <div className={styles.panelHead}>
            <h1>商談</h1>
            <button onClick={() => void start()} disabled={busy}>
              新規作成
            </button>
          </div>
          {items.length ? (
            items.map((item) => (
              <button
                className={conversation?.id === item.id ? styles.active : ""}
                key={item.id}
                onClick={() => void select(item.id)}
              >
                商談{" "}
                <small>
                  {new Date(item.created_at).toLocaleString("ja-JP", {
                    month: "numeric",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}{" "}
                  · {item.status === "active" ? "進行中" : "終了"}
                </small>
              </button>
            ))
          ) : (
            <p>まだ商談がありません。</p>
          )}
        </aside>
        <section className={styles.transcript}>
          <div className={styles.panelHead}>
            <div>
              <p>書き起こし</p>
              <h2>{conversation ? "進行中の商談" : "商談を選択"}</h2>
            </div>
          </div>
          {conversation?.messages.map((message) => (
            <article
              className={
                message.side === "sales_rep" ? styles.rep : styles.customer
              }
              key={message.id}
            >
              <small>{message.speaker_label}</small>
              <p>{message.content}</p>
            </article>
          ))}
          {conversation && !conversation.messages.length && (
            <p className={styles.empty}>最初の発言を追加してください。</p>
          )}
          {conversation?.status === "active" && (
            <form onSubmit={submit}>
              <select
                aria-label="話者"
                value={side}
                onChange={(e) =>
                  setSide(e.target.value as "customer" | "sales_rep")
                }
              >
                <option value="sales_rep">自分</option>
                <option value="customer">通話相手</option>
              </select>
              <input
                aria-label="発言"
                value={content}
                onChange={(e) => setContent(e.target.value)}
                placeholder="発言を入力"
              />
              <button disabled={busy}>追加</button>
            </form>
          )}
        </section>
        <aside className={styles.assist}>
          <h2>営業支援</h2>
          <section>
            <h3>音声入力</h3>
            <p>{captureState}</p>
            {isCapturing ? (
              <button onClick={stopCapture}>音声取得を停止</button>
            ) : (
              <button
                onClick={() => void beginCapture()}
                disabled={!conversation || busy}
              >
                Meet音声とマイクを取得
              </button>
            )}
          </section>
          {[
            ["次に聞くこと", "会話が始まると提案します"],
            ["返答例", "会話の文脈から作成します"],
            ["確認事項", "重要な確認点を表示します"],
          ].map(([title, text]) => (
            <section key={title}>
              <h3>{title}</h3>
              <p>{text}</p>
            </section>
          ))}
        </aside>
      </div>
    </main>
  );
}
