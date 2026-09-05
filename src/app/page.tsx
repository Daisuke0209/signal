"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import Link from "next/link";
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
import {
  LiveTranscription,
  TranscriptEvent,
  startLiveTranscription,
  transcriptionError,
} from "@/lib/live-transcription";
import {
  connectSuggestionEvents,
  getLatestSuggestions,
  Suggestion,
  SuggestionKind,
  SuggestionRun,
  SuggestionState,
} from "@/lib/suggestions-api";
import styles from "./page.module.css";

const DEMO_EMAIL = "demo@signal.local";

function suggestionsFor(run: SuggestionRun | null, kind: SuggestionKind): Suggestion[] {
  return run?.suggestions.filter((suggestion) => suggestion.kind === kind) ?? [];
}

function suggestionStatus(run: SuggestionRun | null, connectionError: boolean): string {
  if (connectionError) return "提案の接続が切れています";
  if (run?.status === "queued") return "提案を準備中";
  if (run?.status === "running") {
    return run.phase === "searching" ? "資料を調査中" : "提案を生成中";
  }
  if (run?.status === "failed") return "提案を生成できませんでした";
  return "提案を待機中";
}

function isOlderSuggestionRun(
  candidate: SuggestionRun | null,
  current: SuggestionRun | null,
): boolean {
  if (candidate === null) return current !== null;
  if (current === null) return false;
  return (
    candidate.generation < current.generation ||
    (candidate.generation === current.generation &&
      candidate.revision < current.revision)
  );
}

function SuggestionItems({ suggestions }: { suggestions: Suggestion[] }) {
  if (!suggestions.length) {
    return <p className={styles.suggestionHint}>まだ提案はありません。</p>;
  }

  return (
    <div className={styles.suggestionItems}>
      {suggestions.map((suggestion) => (
        <article className={styles.suggestionItem} key={suggestion.id}>
          <p>{suggestion.content}</p>
          {suggestion.sources.length ? (
            <div className={styles.sources}>
              {suggestion.sources.map((source) => (
                <details
                  className={styles.source}
                  key={`${source.document_id}:${source.page_number}:${source.excerpt}`}
                >
                  <summary>{source.document_name} · p.{source.page_number}</summary>
                  <p>{source.excerpt}</p>
                </details>
              ))}
            </div>
          ) : (
            <p className={styles.noSources}>根拠なし</p>
          )}
        </article>
      ))}
    </div>
  );
}

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
  const captureGeneration = useRef(0);
  const live = useRef<LiveTranscription | null>(null);
  const liveAbort = useRef<AbortController | null>(null);
  const [partials, setPartials] = useState<Record<string, TranscriptEvent>>({});
  const [isStopping, setIsStopping] = useState(false);
  const [showManualInput, setShowManualInput] = useState(false);
  const [captureState, setCaptureState] = useState("停止中");
  const [isCapturing, setIsCapturing] = useState(false);
  const [suggestionRun, setSuggestionRun] = useState<SuggestionRun | null>(
    null,
  );
  const [suggestionConnectionError, setSuggestionConnectionError] =
    useState(false);
  function stopCapture() {
    captureGeneration.current += 1;
    liveAbort.current?.abort();
    live.current?.abort();
    live.current = null;
    setPartials({});
    setIsStopping(false);
    stopStream(capture.current?.displayStream ?? null);
    stopStream(capture.current?.microphoneStream ?? null);
    capture.current = null;
    setIsCapturing(false);
    setCaptureState("停止中");
  }
  async function beginCapture() {
    if (busy || isCapturing || !conversation || conversation.status !== "active") return;
    const generation = captureGeneration.current + 1;
    captureGeneration.current = generation;
    setError("");
    setBusy(true);
    const aborter = new AbortController();
    liveAbort.current = aborter;
    try {
      const nextCapture = await startAudioCapture();
      if (captureGeneration.current !== generation) {
        stopStream(nextCapture.displayStream);
        stopStream(nextCapture.microphoneStream);
        return;
      }
      capture.current = nextCapture;
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
      setCaptureState("文字起こしに接続中…");
      const connection = await startLiveTranscription(nextCapture, conversation.id, aborter.signal,
        (update) => {
          if (captureGeneration.current !== generation) return;
          const key = `${update.source}:${update.item_id}`;
          setPartials((old) => {
            const next = { ...old };
            if (update.type === "final") delete next[key];
            else next[key] = update;
            return next;
          });
          if (update.type === "final" && update.message) {
            const message = update.message;
            setSuggestionRun(null);
            setSuggestionConnectionError(false);
            setConversation((old) => old?.id === conversation.id ? {
              ...old, messages: [...old.messages.filter((m) => m.id !== message.id), message]
                .sort((a, b) => a.sequence_number - b.sequence_number),
            } : old);
          }
        },
        (message) => {
          if (captureGeneration.current !== generation) return;
          stopCapture();
          setError(message);
        });
      if (captureGeneration.current !== generation) { connection.abort(); return; }
      live.current = connection;
      setCaptureState("文字起こし中");
    } catch (captureError) {
      if (captureGeneration.current !== generation) return;
      const connecting = capture.current !== null;
      const reason = captureFailure(captureError);
      setError(
        connecting ? transcriptionError(captureError instanceof Error ? captureError.message : "") : reason === "missing-tab-audio"
          ? "共有したタブに音声がありません。タブ音声を共有してください。"
          : reason === "missing-microphone-audio"
            ? "マイクから音声を取得できませんでした。マイクを確認してください。"
            : reason === "permission-denied"
              ? "共有またはマイクの権限が許可されませんでした。"
              : "音声共有がキャンセルされました。",
      );
      stopCapture();
    } finally {
      setBusy(false);
    }
  }
  async function finishCapture() {
    if (!live.current || isStopping) return;
    const generation = captureGeneration.current;
    setIsStopping(true);
    setCaptureState("最後の発言を保存中…");
    try {
      await live.current.stop();
    } catch {
      if (captureGeneration.current === generation) setError(transcriptionError("stop_failed"));
    } finally {
      if (captureGeneration.current === generation) stopCapture();
    }
  }
  useEffect(() => () => stopCapture(), []);
  const conversationId = conversation?.id;
  useEffect(() => {
    if (!user || !conversationId) return;

    let active = true;
    const applyState = (state: SuggestionState) => {
      if (!active || state.conversation_id !== conversationId) return;
      setSuggestionConnectionError(false);
      setSuggestionRun((current) =>
        isOlderSuggestionRun(state.latest_run, current)
          ? current
          : state.latest_run,
      );
    };
    const handleConnectionError = () => {
      if (active) setSuggestionConnectionError(true);
    };
    const handleAccessRevoked = () => {
      if (!active) return;
      stopCapture();
      setSuggestionRun(null);
      setSuggestionConnectionError(false);
      setConversation(null);
      setItems([]);
      setUser(null);
      setError("認証が失効しました。もう一度ログインしてください。");
    };
    void getLatestSuggestions(conversationId)
      .then(applyState)
      .catch(handleConnectionError);

    const closeEvents = connectSuggestionEvents(
      conversationId,
      applyState,
      handleConnectionError,
      handleAccessRevoked,
    );
    return () => {
      active = false;
      closeEvents();
    };
  }, [conversationId, user]);
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
    stopCapture();
    setShowManualInput(false);
    setSuggestionRun(null);
    setSuggestionConnectionError(false);
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
      stopCapture();
      setShowManualInput(false);
      setSuggestionRun(null);
      setSuggestionConnectionError(false);
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
      setSuggestionRun(null);
      setSuggestionConnectionError(false);
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
      <aside className={styles.sidebar} aria-label="商談一覧">
        <div className={styles.brand}>
          <span className={styles.brandMark} aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
          Signal
        </div>
        <Link className={styles.documentsLink} href="/documents">
          資料を管理
        </Link>
        <button
          className={styles.newConversation}
          onClick={() => void start()}
          disabled={busy}
        >
          <span aria-hidden="true">＋</span> 新規作成
        </button>
        <div className={styles.listHeading}>
          <h2>商談</h2>
          <span>{items.length}</span>
        </div>
        <nav className={styles.conversationList} aria-label="商談履歴">
          {items.length ? (
            items.map((item) => (
              <button
                className={conversation?.id === item.id ? styles.active : ""}
                aria-current={conversation?.id === item.id ? "page" : undefined}
                key={item.id}
                onClick={() => void select(item.id)}
                disabled={busy}
              >
                <span className={styles.conversationTitle}>
                  商談{" "}
                  <span
                    className={styles.conversationDot}
                    data-active={item.status === "active"}
                  />
                </span>
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
            <p className={styles.listEmpty}>まだ商談がありません</p>
          )}
        </nav>
        <div className={styles.profile}>
          <span className={styles.avatar} aria-hidden="true">
            {user.name.slice(0, 1)}
          </span>
          <div>
            <strong>{user.name}</strong>
            <button onClick={() => void signOut()} disabled={busy}>
              ログアウト
            </button>
          </div>
        </div>
      </aside>
      <div className={styles.stage}>
        <header className={styles.sessionHeader}>
          <div>
            <h1>
              {conversation
                ? conversation.status === "active"
                  ? "進行中の商談"
                  : "終了した商談"
                : "会話に、集中できる場所。"}
            </h1>
          </div>
          <div className={styles.audioControls}>
            <span
              className={styles.captureStatus}
              data-active={isCapturing}
              role="status"
            >
              <span aria-hidden="true" />
              {captureState}
            </span>
            {isCapturing ? (
              <button className={styles.stopButton} disabled={busy || isStopping} onClick={() => void finishCapture()}>
                音声取得を停止
              </button>
            ) : (
              <button
                className={styles.primaryButton}
                onClick={() => void beginCapture()}
                disabled={conversation?.status !== "active" || busy}
              >
                <svg
                  width="16"
                  height="16"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.7"
                  aria-hidden="true"
                >
                  <rect x="9" y="3" width="6" height="11" rx="3" />
                  <path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8" />
                </svg>
                Meet音声とマイクを取得
              </button>
            )}
          </div>
        </header>
        {error && (
          <p className={styles.error} role="alert">
            {error}
          </p>
        )}
        <div className={styles.columns}>
          <section
            className={styles.transcript}
            aria-labelledby="transcript-title"
          >
            <div className={styles.panelHead}>
              <div>
                <h2 id="transcript-title">文字起こし</h2>
              </div>
              <span className={styles.panelMeta}>
                {conversation?.messages.length ?? 0} 発言
              </span>
            </div>
            <div className={styles.messageList}>
              {conversation?.messages.map((message) => (
                <article
                  className={styles.message}
                  data-speaker={message.side}
                  key={message.id}
                >
                  <div className={styles.speaker}>
                    <span aria-hidden="true" />
                    {message.speaker_label}
                  </div>
                  <p>{message.content}</p>
                </article>
              ))}
               {Object.entries(partials).map(([key, update]) => (
                <article className={styles.message} data-speaker={update.side} data-partial="true" key={key}>
                  <div className={styles.speaker}>
                    <span aria-hidden="true" />
                    {update.source === "microphone" ? "自分（マイク）" : "通話相手（共有音声）"}
                    <small>聞き取り中</small>
                  </div>
                  <p>{update.text || "…"}</p>
                </article>
              ))}
               {!conversation?.messages.length && !Object.keys(partials).length && (
                <div className={styles.transcriptEmpty}>
                  <span className={styles.soundMark} aria-hidden="true">
                    <i />
                    <i />
                    <i />
                    <i />
                    <i />
                  </span>
                  <h3>
                    {conversation
                      ? "会話を受け取る準備ができました"
                      : "新しい商談をはじめましょう"}
                  </h3>
                  <p>
                    {conversation
                      ? "上部からMeetのタブ音声とマイクを共有してください。"
                      : "「新規作成」から商談を作成すると、音声を接続できます。"}
                  </p>
                </div>
              )}
            </div>
            {conversation?.status === "active" && (
              <div className={styles.manualTools}>
                <button
                  className={styles.quietButton}
                  aria-expanded={showManualInput}
                  aria-controls="manual-input"
                  onClick={() => setShowManualInput(!showManualInput)}
                >
                  {showManualInput ? "手入力を閉じる" : "音声が使えないときは"}
                  <span aria-hidden="true">{showManualInput ? "−" : "＋"}</span>
                </button>
                {showManualInput && (
                  <form
                    id="manual-input"
                    className={styles.manualForm}
                    onSubmit={submit}
                  >
                    <p>音声の代わりに、発言を手入力で追加できます。</p>
                    <div>
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
                      <button disabled={busy || !content.trim()}>追加</button>
                    </div>
                  </form>
                )}
              </div>
            )}
          </section>
          <aside className={styles.assist} aria-labelledby="assist-title">
            <div className={styles.panelHead}>
              <div>
                <h2 id="assist-title">営業支援</h2>
              </div>
              <span
                aria-live="polite"
                className={styles.assistLabel}
                data-state={suggestionRun?.status ?? "idle"}
              >
                {suggestionStatus(suggestionRun, suggestionConnectionError)}
              </span>
            </div>
            <section className={styles.nextQuestion}>
              <div className={styles.suggestionHeading}>
                <span aria-hidden="true">↗</span>
                <h3>次に聞くこと</h3>
              </div>
              <SuggestionItems
                suggestions={suggestionsFor(suggestionRun, "question")}
              />
            </section>
            <section className={styles.suggestionSection}>
              <div className={styles.suggestionHeading}>
                <span aria-hidden="true">↳</span>
                <h3>返答例</h3>
              </div>
              <SuggestionItems
                suggestions={suggestionsFor(suggestionRun, "response")}
              />
            </section>
            <section className={styles.suggestionSection}>
              <div className={styles.suggestionHeading}>
                <span aria-hidden="true">✓</span>
                <h3>確認事項</h3>
              </div>
              <SuggestionItems
                suggestions={suggestionsFor(suggestionRun, "confirmation")}
              />
            </section>
          </aside>
        </div>
      </div>
    </main>
  );
}
