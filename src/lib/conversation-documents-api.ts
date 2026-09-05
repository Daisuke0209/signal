import { Document, listDocuments } from "@/lib/documents-api";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { ...init, credentials: "include" });
  if (!response.ok) throw new Error("Conversation document request failed");
  return (await response.json()) as T;
}

export const listReadyDocuments = async (organizationId: string): Promise<Document[]> =>
  (await listDocuments(organizationId)).filter((document) => document.processing_status === "ready");
export const getConversationDocuments = (conversationId: string) => json<{ id: string }[]>(`/conversations/${conversationId}/documents`);
export const saveConversationDocuments = (conversationId: string, documentIds: string[]) =>
  json(`/conversations/${conversationId}/documents`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ document_ids: documentIds }) });
