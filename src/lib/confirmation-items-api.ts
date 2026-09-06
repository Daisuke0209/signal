const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type ConfirmationItem = {
  id: string;
  content: string;
  status: "open" | "confirmed";
  version: number;
  origin_message_id: string | null;
  evidence_message_id: string | null;
  evidence_excerpt: string | null;
  confirmation_source: "auto" | "manual" | null;
  created_at: string;
  updated_at: string;
};

export class ConfirmationRequestError extends Error {
  constructor(public status: number) {
    super("Confirmation request failed");
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
  });
  if (!response.ok) throw new ConfirmationRequestError(response.status);
  return (await response.json()) as T;
}

export async function getConfirmationItems(conversationId: string) {
  const result = await request<{ items: ConfirmationItem[] }>(
    `/conversations/${conversationId}/confirmation-items`,
  );
  if (!Array.isArray(result.items)) throw new Error("Invalid confirmation snapshot");
  return result.items;
}

export function updateConfirmationItem(
  conversationId: string,
  item: ConfirmationItem,
  status: ConfirmationItem["status"],
) {
  return request<ConfirmationItem>(
    `/conversations/${conversationId}/confirmation-items/${item.id}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, expected_version: item.version }),
    },
  );
}
