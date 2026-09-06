"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ConfirmationItem,
  ConfirmationRequestError,
  getConfirmationItems,
  updateConfirmationItem,
} from "@/lib/confirmation-items-api";
import styles from "./confirmation-checklist.module.css";

type Props = {
  conversationId: string;
  ended: boolean;
  refreshToken: string;
};

// Items are cumulative; a delayed snapshot must not undo a newer manual change.
function mergeItems(current: ConfirmationItem[], incoming: ConfirmationItem[]) {
  const merged = new Map(current.map((item) => [item.id, item]));
  for (const item of incoming) {
    const previous = merged.get(item.id);
    if (!previous || item.version >= previous.version) merged.set(item.id, item);
  }
  return [...merged.values()];
}

export function ConfirmationChecklist(props: Props) {
  // Remount on conversation switch to isolate pending requests and UI state.
  return <Checklist key={props.conversationId} {...props} />;
}

function Checklist({ conversationId, ended, refreshToken }: Props) {
  const [items, setItems] = useState<ConfirmationItem[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const live = useRef(false);
  const mutating = useRef(false);
  const requestVersion = useRef(0);

  const reportError = useCallback((failure: unknown, message: string) => {
    if (
      failure instanceof ConfirmationRequestError &&
      (failure.status === 401 || failure.status === 403)
    ) {
      setItems([]);
      setForbidden(true);
      setError("確認事項へのアクセスが失効しました。再ログインしてください。");
    } else {
      setError(message);
    }
  }, []);

  const refresh = useCallback(async () => {
    if (mutating.current) return;
    const version = ++requestVersion.current;
    try {
      const incoming = await getConfirmationItems(conversationId);
      if (!live.current || version !== requestVersion.current) return;
      setItems((current) => mergeItems(current, incoming));
      setLoaded(true);
      setForbidden(false);
      setError("");
    } catch (failure) {
      if (live.current && version === requestVersion.current)
        reportError(failure, "確認事項を読み込めませんでした。再試行してください。");
    }
  }, [conversationId, reportError]);

  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
      requestVersion.current += 1;
    };
  }, []);

  useEffect(() => {
    let active = true;
    queueMicrotask(() => { if (active) void refresh(); });
    return () => { active = false; };
  }, [refresh, refreshToken]);

  useEffect(() => {
    if (ended || forbidden) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, 5000);
    return () => window.clearInterval(timer);
  }, [ended, forbidden, refresh]);

  async function toggle(item: ConfirmationItem) {
    if (ended || forbidden || mutating.current) return;
    mutating.current = true;
    requestVersion.current += 1;
    setPendingId(item.id);
    setError("");
    setNotice("");
    try {
      const saved = await updateConfirmationItem(
        conversationId,
        item,
        item.status === "confirmed" ? "open" : "confirmed",
      );
      if (!live.current) return;
      setItems((current) => mergeItems(current, [saved]));
      setNotice(saved.status === "confirmed" ? "確認済みにしました。" : "未確認に戻しました。自動判定よりこの変更を優先します。");
    } catch (failure) {
      if (!live.current) return;
      if (failure instanceof ConfirmationRequestError && failure.status === 409) {
        mutating.current = false;
        await refresh();
        if (live.current) setNotice("状態が更新されたか商談が終了しました。最新の状態を確認してください。");
      } else {
        reportError(failure, "変更を保存できませんでした。もう一度チェックを操作してください。");
      }
    } finally {
      mutating.current = false;
      if (live.current) setPendingId(null);
    }
  }

  const confirmed = items.filter((item) => item.status === "confirmed").length;
  const ordered = [...items].sort((a, b) =>
    Number(a.status === "confirmed") - Number(b.status === "confirmed") ||
    a.created_at.localeCompare(b.created_at) || a.id.localeCompare(b.id),
  );

  return (
    <section className={styles.root} aria-labelledby="confirmation-title">
      <div className={styles.heading}>
        <h3 id="confirmation-title">確認事項</h3>
        {loaded && <span>{confirmed} / {items.length} 確認済み</span>}
      </div>
      <p className={styles.description}>会話で確認できた項目に自動でチェックします。手動でも修正できます。</p>
      {error && <div className={styles.error} role="alert">
        <p>{error}</p>
        {!forbidden && <button type="button" onClick={() => void refresh()}>再試行</button>}
      </div>}
      {notice && <p className={styles.notice} role="status">{notice}</p>}
      {!loaded && !error && <p className={styles.empty}>確認事項を読み込んでいます…</p>}
      {loaded && !items.length && !error && <p className={styles.empty}>会話から確認したいことを見つけると、ここに追加します。</p>}
      <ul className={styles.list}>
        {ordered.map((item) => (
          <li className={styles.item} key={item.id} data-confirmed={item.status === "confirmed"}>
            <label className={styles.check}>
              <input
                type="checkbox"
                checked={item.status === "confirmed"}
                disabled={ended || forbidden || pendingId !== null}
                onChange={() => void toggle(item)}
              />
              <span>{item.content}</span>
            </label>
            {item.confirmation_source && <p className={styles.source}>
              {pendingId === item.id ? "保存中…" : item.confirmation_source === "auto" ? "会話から確認済み" : item.status === "confirmed" ? "手動で確認済み" : "手動で未確認に変更"}
            </p>}
            {item.status === "confirmed" && item.evidence_excerpt && <blockquote className={styles.evidence}>
              {item.evidence_excerpt}
            </blockquote>}
          </li>
        ))}
      </ul>
      {ended && <p className={styles.empty}>終了した商談の確認事項です。</p>}
    </section>
  );
}
