const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type DocumentProcessingStatus =
  | "pending"
  | "processing"
  | "ready"
  | "failed"
  | "text_unavailable";

export type Document = {
  id: string;
  organization_id: string;
  filename: string;
  content_type: string;
  byte_size: number;
  processing_status: DocumentProcessingStatus;
  processing_error: string | null;
  created_at: string;
  uploaded_by_name: string;
};

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
  });
  if (!response.ok) throw new Error("Document request failed");
  return (await response.json()) as T;
}

export const listDocuments = (organizationId: string) =>
  json<Document[]>(`/documents?organization_id=${encodeURIComponent(organizationId)}`);

export const uploadDocument = (organizationId: string, file: File) => {
  const form = new FormData();
  form.set("organization_id", organizationId);
  form.set("file", file);
  return json<Document>("/documents", { method: "POST", body: form });
};

export const extractDocument = (documentId: string) =>
  json<Document>(`/documents/${documentId}/extract`, { method: "POST" });

export const retryDocument = (documentId: string) =>
  json<Document>(`/documents/${documentId}/retry`, { method: "POST" });
