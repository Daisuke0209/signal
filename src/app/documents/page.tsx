"use client";

import Link from "next/link";
import { ChangeEvent, useEffect, useRef, useState } from "react";
import { CurrentUser, getCurrentUser } from "@/lib/auth-api";
import {
  Document,
  DocumentProcessingStatus,
  extractDocument,
  listDocuments,
  uploadDocument,
  retryDocument,
} from "@/lib/documents-api";
import styles from "./page.module.css";

const statusLabel: Record<DocumentProcessingStatus, string> = {
  pending: "登録済み",
  processing: "解析中",
  ready: "利用可能",
  failed: "解析に失敗",
  text_unavailable: "本文を取得できません",
};

function formatRegisteredAt(value: string): string {
  return new Intl.DateTimeFormat("ja-JP", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function processingErrorLabel(document: Document): string | null {
  if (!document.processing_error) return null;
  if (document.processing_status === "failed") {
    return "PDFの解析に失敗しました。原本を確認して再度お試しください。";
  }
  if (document.processing_status === "text_unavailable") {
    return "PDFから本文を取得できませんでした。";
  }
  return document.processing_error;
}

export default function DocumentsPage() {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [organizationId, setOrganizationId] = useState("");
  const [documents, setDocuments] = useState<Document[]>([]);
  const [checking, setChecking] = useState(true);
  const [loadingDocuments, setLoadingDocuments] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [retrying, setRetrying] = useState<string | null>(null);
  const selectedOrganizationId = useRef("");
  const listRequestGeneration = useRef(0);
  const documentOperationGeneration = useRef(0);
  const mounted = useRef(false);

  function selectOrganization(nextOrganizationId: string) {
    documentOperationGeneration.current += 1;
    selectedOrganizationId.current = nextOrganizationId;
    setOrganizationId(nextOrganizationId);
    setDocuments([]);
    setRetrying(null);
    setError("");
  }

  async function loadDocuments(nextOrganizationId: string) {
    const generation = listRequestGeneration.current + 1;
    listRequestGeneration.current = generation;
    const isCurrentRequest = () =>
      mounted.current &&
      selectedOrganizationId.current === nextOrganizationId &&
      listRequestGeneration.current === generation;
    if (isCurrentRequest()) {
      setError("");
      setLoadingDocuments(true);
    }
    try {
      const loadedDocuments = await listDocuments(nextOrganizationId);
      if (isCurrentRequest()) {
        setDocuments(loadedDocuments);
      }
    } catch {
      if (isCurrentRequest()) {
        setDocuments([]);
        setError("資料一覧を読み込めませんでした。接続を確認してください。");
      }
    } finally {
      if (isCurrentRequest()) setLoadingDocuments(false);
    }
  }

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const currentUser = await getCurrentUser();
        setUser(currentUser);
        const firstOrganizationId = currentUser?.organizations[0]?.id ?? "";
        selectOrganization(firstOrganizationId);
        if (firstOrganizationId) await loadDocuments(firstOrganizationId);
      } catch {
        setError("セッションを確認できませんでした。接続を確認してください。");
      } finally {
        setChecking(false);
      }
    })();
  }, []);

  async function changeOrganization(event: ChangeEvent<HTMLSelectElement>) {
    if (uploading) return;
    const nextOrganizationId = event.target.value;
    selectOrganization(nextOrganizationId);
    await loadDocuments(nextOrganizationId);
  }

  async function registerFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !organizationId || uploading) return;
    if (file.type !== "application/pdf") {
      setError("PDFファイルを選択してください。");
      return;
    }

    const uploadOrganizationId = organizationId;
    setUploading(true);
    setError("");
    try {
      const registered = await uploadDocument(uploadOrganizationId, file);
      if (selectedOrganizationId.current !== uploadOrganizationId) return;
      setDocuments((current) => [registered, ...current]);
      const processed = await extractDocument(registered.id);
      if (selectedOrganizationId.current !== uploadOrganizationId) return;
      setDocuments((current) =>
        current.map((document) =>
          document.id === processed.id ? processed : document,
        ),
      );
    } catch {
      setError("資料を登録できませんでした。PDFと接続を確認して、もう一度お試しください。");
    } finally {
      setUploading(false);
    }
  }

  async function retry(document: Document) {
    if (retrying || document.processing_status === "processing") return;
    const retryOrganizationId = selectedOrganizationId.current;
    const retryGeneration = documentOperationGeneration.current;
    const isCurrentRetry = () =>
      mounted.current &&
      selectedOrganizationId.current === retryOrganizationId &&
      documentOperationGeneration.current === retryGeneration;
    setRetrying(document.id);
    setError("");
    try {
      const next = await retryDocument(document.id);
      if (isCurrentRetry()) {
        setDocuments((items) =>
          items.map((item) => (item.id === next.id ? next : item)),
        );
      }
    } catch {
      if (isCurrentRetry()) {
        setError("資料を再解析できませんでした。もう一度お試しください。");
      }
    } finally {
      if (isCurrentRetry()) {
        setRetrying(null);
      }
    }
  }

  if (checking) {
    return <main className={styles.center}>セッションを確認しています…</main>;
  }

  if (!user) {
    return (
      <main className={styles.center}>
        <p>資料管理を利用するにはログインが必要です。</p>
        <Link href="/">ログイン画面へ戻る</Link>
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <h1>資料管理</h1>
          <p className={styles.intro}>商談中に参照する商品資料を登録します。</p>
        </div>
        <Link className={styles.workspaceLink} href="/">
          商談ワークスペースへ戻る
        </Link>
      </header>

      <section className={styles.content} aria-labelledby="documents-title">
        <div className={styles.toolbar}>
          <div>
            <h2 id="documents-title">登録済み資料</h2>
            <p>PDFはページごとに解析され、提案の根拠として利用されます。</p>
          </div>
          <div className={styles.controls}>
            {user.organizations.length > 1 && (
              <label className={styles.organization}>
                組織
                <select
                  disabled={uploading}
                  value={organizationId}
                  onChange={changeOrganization}
                >
                  {user.organizations.map((organization) => (
                    <option key={organization.id} value={organization.id}>
                      {organization.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className={styles.uploadButton}>
              {uploading ? "登録・解析中…" : "PDFを登録"}
              <input
                accept="application/pdf"
                aria-label="PDFを選択"
                disabled={!organizationId || uploading}
                onChange={registerFile}
                type="file"
              />
            </label>
          </div>
        </div>

        {error && <p className={styles.error} role="alert">{error}</p>}
        {!organizationId ? (
          <p className={styles.empty}>利用できる組織がありません。</p>
        ) : loadingDocuments ? (
          <p className={styles.empty}>資料を読み込んでいます…</p>
        ) : documents.length === 0 ? (
          <p className={styles.empty}>登録済みの資料はありません。</p>
        ) : (
          <ul className={styles.documentList}>
            {documents.map((document) => (
              <li key={document.id}>
                <div>
                  <h3>{document.filename}</h3>
                  <p>
                    {formatRegisteredAt(document.created_at)} · {document.uploaded_by_name}
                  </p>
                  {processingErrorLabel(document) && (
                    <p className={styles.failure}>{processingErrorLabel(document)}</p>
                  )}
                </div>
                <span data-status={document.processing_status}>
                  {statusLabel[document.processing_status]}
                </span>
                {document.processing_status !== "ready" &&
                  document.processing_status !== "processing" && (
                    <button
                      disabled={retrying !== null}
                      onClick={() => void retry(document)}
                    >
                      {retrying === document.id ? "再解析中…" : "再解析"}
                    </button>
                  )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
