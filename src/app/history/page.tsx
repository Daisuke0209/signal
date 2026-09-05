"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { getConversation, getCurrentUser, listConversations, type Conversation, type ConversationDetail } from "@/lib/auth-api";
import { createSummary, getSummary, type SummaryState } from "@/lib/summaries-api";
import styles from "./page.module.css";

function date(value: string) {
  return new Date(value).toLocaleString("ja-JP", { month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function HistoryDetail({ id }: { id: string }) {
  const [conversation, setConversation] = useState<ConversationDetail | null>(null);
  const [summary, setSummary] = useState<SummaryState | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const mounted = useRef(false);
  useEffect(() => {
    mounted.current = true;
    let active = true;
    Promise.all([getConversation(id), getSummary(id)]).then(([detail, state]) => {
      if (!active) return;
      setConversation(detail); setSummary(state);
    }).catch(() => {
      if (active) setError("履歴を読み込めませんでした。接続とログイン状態を確認してください。");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; mounted.current = false; };
  }, [id]);
  useEffect(() => {
    if (summary?.status !== "queued" && summary?.status !== "generating") return;
    let active = true;
    const timer = window.setTimeout(() => {
      getSummary(id).then(state => {
        if (active) setSummary(state);
      }).catch(() => {
        if (active) setError("要約の状態を確認できませんでした。もう一度読み込んでください。");
      });
    }, 1500);
    return () => { active = false; window.clearTimeout(timer); };
  }, [id, summary]);
  async function generate() {
    setBusy(true); setError("");
    try {
      const state = await createSummary(id);
      if (mounted.current) setSummary(state);
    } catch (error) {
      if (mounted.current) setError(error instanceof Error ? error.message : "要約を作成できませんでした。");
    } finally { if (mounted.current) setBusy(false); }
  }
  async function reload() {
    setBusy(true); setError("");
    try {
      const [detail, state] = await Promise.all([getConversation(id), getSummary(id)]);
      if (mounted.current) { setConversation(detail); setSummary(state); }
    } catch { if (mounted.current) setError("履歴を読み込めませんでした。"); }
    finally { if (mounted.current) setBusy(false); }
  }
  if (loading) return <p className={styles.placeholder}>履歴を読み込んでいます…</p>;
  const generating = summary?.status === "queued" || summary?.status === "generating";
  return <div className={styles.detail}>
    {error && <div role="alert" className={styles.error}>{error} <button disabled={busy} onClick={() => void reload()}>再読込</button></div>}
    {conversation && <>
      <header className={styles.detailHeader}><div><h2>{date(conversation.created_at)}の商談</h2><p>{conversation.messages.length}件の発言 · {conversation.status === "ended" ? "終了済み" : "進行中"}</p></div></header>
      <section aria-labelledby="summary-title" className={styles.summary}>
        <div className={styles.sectionHeader}><h3 id="summary-title">会議後の要約</h3>
          {conversation.status === "ended" && !summary?.result && <button disabled={busy || generating} onClick={() => void generate()}>{generating ? "要約を作成中…" : summary?.status === "failed" ? "もう一度作成" : "要約を作成"}</button>}
        </div>
        {conversation.status !== "ended" ? <p>商談が終了すると要約を作成できます。</p>
          : summary?.status === "succeeded" && summary.result ? <>
            <p className={styles.overview}>{summary.result.overview}</p>
            {([
              ["決定事項", summary.result.decisions], ["未解決事項", summary.result.unresolved], ["次の対応", summary.result.next_actions],
            ] as const).map(([title, items]) => <div className={styles.summaryGroup} key={title}><h4>{title}</h4>{items.length ? <ul>{items.map((text, index) => <li key={index}>{text}</li>)}</ul> : <p>明示された内容はありません。</p>}</div>)}
            <p className={styles.note}>確定した{summary.message_count}件の発言をもとに作成。内容は文字起こしと合わせて確認してください。</p>
          </> : <p role="status">{summary?.status === "failed" ? "要約の作成が中断しました。確定した発言は保存されています。" : generating ? "決定事項や次の対応を整理しています。" : "確定した発言から、要点と次の対応を整理します。"}</p>}
      </section>
      <section aria-labelledby="transcript-title"><h3 id="transcript-title">文字起こし</h3><ol className={styles.transcript}>{conversation.messages.map(message => <li key={message.id}><span>{message.side === "customer" ? "顧客" : "自分"}</span><p>{message.content}</p></li>)}</ol>{conversation.messages.length === 0 && <p>確定した発言はありません。</p>}</section>
    </>}
  </div>;
}

export default function HistoryPage() {
  const [items, setItems] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        if (!await getCurrentUser()) {
          if (active) setError("ログインしてから履歴を開いてください。");
          return;
        }
        const rows = (await listConversations()).filter(item => item.status === "ended");
        if (active) { setItems(rows); setSelected(rows[0]?.id ?? null); }
      } catch { if (active) setError("履歴を読み込めませんでした。接続を確認してください。"); }
      finally { if (active) setLoading(false); }
    })();
    return () => { active = false; };
  }, []);
  return <main className={styles.page}>
    <header className={styles.header}><Link href="/" className={styles.brand}>Signal</Link><nav><Link href="/">商談に戻る</Link><Link href="/documents">資料管理</Link></nav></header>
    <h1>商談履歴</h1>
    {error && <p role="alert" className={styles.error}>{error} <Link href="/">商談画面へ</Link></p>}
    {loading ? <p>履歴を読み込んでいます…</p> : <div className={styles.layout}>
      <aside aria-label="終了した商談" className={styles.list}>{items.map(item => <button key={item.id} aria-pressed={item.id === selected} onClick={() => setSelected(item.id)}>{date(item.created_at)}<span>終了済み</span></button>)}{!items.length && !error && <p>終了した商談はありません。</p>}</aside>
      {selected ? <HistoryDetail key={selected} id={selected} /> : <p className={styles.placeholder}>商談を終了すると、ここから振り返れます。</p>}
    </div>}
  </main>;
}
