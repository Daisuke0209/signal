"use client";
import { useEffect, useState } from "react";
import { getConversationDocuments, listReadyDocuments, saveConversationDocuments } from "@/lib/conversation-documents-api";

export function ConversationDocuments({ conversationId, organizationId, ended }: { conversationId: string; organizationId: string; ended: boolean }) {
  const [open, setOpen] = useState(false); const [ids, setIds] = useState<string[]>([]); const [documents, setDocuments] = useState<{id:string;filename:string}[]>([]); const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  useEffect(() => { if (!open) return; let live = true; setLoaded(false); void Promise.all([listReadyDocuments(organizationId), getConversationDocuments(conversationId)]).then(([all, selected]) => { if (live) { setDocuments(all); setIds(selected.map((d) => d.id)); setError(""); setLoaded(true); } }).catch(() => { if (live) setError("参照資料を読み込めませんでした。"); }); return () => { live = false; }; }, [conversationId, open, organizationId]);
  async function save() { if (!loaded || busy) return; setBusy(true); setError(""); try { await saveConversationDocuments(conversationId, ids); setOpen(false); } catch { setError("保存できませんでした。もう一度お試しください。"); } finally { setBusy(false); } }
  return <section><button disabled={ended} onClick={() => setOpen(!open)}>参照資料{ids.length ? ` (${ids.length})` : "なし"}</button>{open && <div>{error && <p role="alert">{error}</p>}<><p>{documents.length ? "提案で参照する資料を選択します。" : "利用可能な資料はありません。参照資料なしで提案します。"}</p>{documents.map((d) => <label key={d.id}><input type="checkbox" checked={ids.includes(d.id)} onChange={() => setIds((old) => old.includes(d.id) ? old.filter((id) => id !== d.id) : [...old, d.id])} />{d.filename}</label>)}<button disabled={busy || ended || !loaded} onClick={() => void save()}>保存</button></></div>}</section>;
}
