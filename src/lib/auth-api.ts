const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type CurrentUser = {
  id: string;
  name: string;
  email: string;
  organizations: Organization[];
};

export type Organization = { id: string; name: string; slug: string; role: string };
export type Conversation = { id: string; organization_id: string; status: "active" | "ended"; created_at: string };
export type ConversationDetail = Conversation & { created_by_user_id: string; participants: { id: string; side: "customer" | "sales_rep"; speaker_label: string; display_name: string | null }[]; messages: { id: string; participant_id: string; speaker_label: string; side: "customer" | "sales_rep"; sequence_number: number; content: string }[] };

function request(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
  });
}

export async function getCurrentUser(): Promise<CurrentUser | null> {
  const response = await request("/auth/me");

  if (response.status === 401) {
    return null;
  }

  if (!response.ok) {
    throw new Error("Failed to restore the authentication session");
  }

  return (await response.json()) as CurrentUser;
}

export async function login(email: string, password: string): Promise<boolean> {
  const response = await request("/auth/login", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ email, password }),
  });

  if (response.status === 401) {
    return false;
  }

  if (!response.ok) {
    throw new Error("Failed to log in");
  }

  return true;
}

export async function logout(): Promise<void> {
  const response = await request("/auth/logout", { method: "POST" });

  if (!response.ok) {
    throw new Error("Failed to log out");
  }
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await request(path, init);
  if (!response.ok) throw new Error("Conversation request failed");
  return (await response.json()) as T;
}

export const listConversations = () => json<Conversation[]>("/conversations");
export const getConversation = (id: string) => json<ConversationDetail>(`/conversations/${id}`);
export const createConversation = (organizationId: string) => json<Conversation>("/conversations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ organization_id: organizationId }) });
export const addMessage = (id: string, message: { speaker_label: string; side: "customer" | "sales_rep"; content: string }) => json<ConversationDetail["messages"][number]>(`/conversations/${id}/messages`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(message) });
