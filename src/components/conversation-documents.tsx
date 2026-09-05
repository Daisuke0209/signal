"use client";

import { useEffect, useState } from "react";
import {
  getConversationDocuments,
  listReadyDocuments,
  saveConversationDocuments,
} from "@/lib/conversation-documents-api";
import styles from "./conversation-documents.module.css";

type ReadyDocument = { id: string; filename: string };

type ConversationDocumentsProps = {
  conversationId: string;
  organizationId: string;
  ended: boolean;
};

export function ConversationDocuments({
  conversationId,
  organizationId,
  ended,
}: ConversationDocumentsProps) {
  const [open, setOpen] = useState(false);
  const [ids, setIds] = useState<string[]>([]);
  const [documents, setDocuments] = useState<ReadyDocument[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);

  function toggle() {
    if (open) {
      setOpen(false);
      return;
    }
    setIds([]);
    setDocuments([]);
    setError("");
    setLoaded(false);
    setOpen(true);
  }

  useEffect(() => {
    if (!open) return;
    let live = true;
    void Promise.all([
      listReadyDocuments(organizationId),
      getConversationDocuments(conversationId),
    ])
      .then(([all, selected]) => {
        if (!live) return;
        setDocuments(all);
        setIds(selected.map((document) => document.id));
        setError("");
        setLoaded(true);
      })
      .catch(() => {
        if (!live) return;
        setError("参照資料を読み込めませんでした。");
      });
    return () => {
      live = false;
    };
  }, [conversationId, open, organizationId]);

  function toggleDocument(documentId: string) {
    setIds((current) =>
      current.includes(documentId)
        ? current.filter((id) => id !== documentId)
        : [...current, documentId],
    );
  }

  async function save() {
    if (!loaded || busy || ended) return;
    setBusy(true);
    setError("");
    try {
      await saveConversationDocuments(conversationId, ids);
      setOpen(false);
    } catch {
      setError("保存できませんでした。もう一度お試しください。");
    } finally {
      setBusy(false);
    }
  }

  const selectionLabel = loaded
    ? ids.length
      ? `参照資料 (${ids.length})`
      : "参照資料なし"
    : "参照資料";

  return (
    <section className={styles.root}>
      <button className={styles.trigger} disabled={ended} onClick={toggle} type="button">
        {selectionLabel}
      </button>
      {open && (
        <div className={styles.panel}>
          <p className={styles.description}>
            {loaded
              ? documents.length
                ? "提案で参照する資料を選択します。"
                : "利用可能な資料はありません。参照資料なしで提案します。"
              : "参照資料を読み込んでいます…"}
          </p>
          {error && (
            <p className={styles.error} role="alert">
              {error}
            </p>
          )}
          <div className={styles.options}>
            {documents.map((document) => (
              <label className={styles.option} key={document.id}>
                <input
                  checked={ids.includes(document.id)}
                  disabled={busy || ended || !loaded}
                  onChange={() => toggleDocument(document.id)}
                  type="checkbox"
                />
                <span>{document.filename}</span>
              </label>
            ))}
          </div>
          <button
            className={styles.save}
            disabled={busy || ended || !loaded}
            onClick={() => void save()}
            type="button"
          >
            {busy ? "保存中…" : "保存"}
          </button>
        </div>
      )}
    </section>
  );
}
