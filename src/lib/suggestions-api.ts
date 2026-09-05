import { recordReceived } from "./browser-observations";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type SuggestionKind = "question" | "response" | "confirmation";
export type SuggestionStatus = "queued" | "running" | "succeeded" | "failed";
export type SuggestionPhase = "generating" | "searching" | null;

export type SuggestionSource = {
  document_id: string;
  document_name: string;
  page_number: number;
  excerpt: string;
};

export type Suggestion = {
  id: string;
  kind: SuggestionKind;
  content: string;
  position: number;
  sources: SuggestionSource[];
};

export type SuggestionRun = {
  id: string;
  generation: number;
  revision: number;
  input_sequence_number: number;
  status: SuggestionStatus;
  phase: SuggestionPhase;
  error_code: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  suggestions: Suggestion[];
};

export type SuggestionState = {
  delivery?: "snapshot" | "live";
  conversation_id: string;
  latest_run: SuggestionRun | null;
};

async function request(path: string): Promise<Response> {
  return fetch(`${API_URL}${path}`, { credentials: "include" });
}

export async function getLatestSuggestions(
  conversationId: string,
): Promise<SuggestionState> {
  const response = await request(`/conversations/${conversationId}/suggestions`);
  if (!response.ok) throw new Error("Suggestion request failed");
  return (await response.json()) as SuggestionState;
}

function eventUrl(conversationId: string): string {
  return new URL(
    `/conversations/${conversationId}/suggestions/events`,
    API_URL,
  ).toString();
}

export function connectSuggestionEvents(
  conversationId: string,
  onState: (state: SuggestionState) => void,
  onConnectionError: () => void,
  onAccessRevoked: () => void,
): () => void {
  const events = new EventSource(eventUrl(conversationId), {
    withCredentials: true,
  });

  events.addEventListener("suggestion_state", (event) => {
    try {
      const state = JSON.parse((event as MessageEvent<string>).data) as SuggestionState;
      if (state.delivery === "live" && state.latest_run) recordReceived(state.latest_run);
      onState(state);
    } catch {
      onConnectionError();
    }
  });
  events.addEventListener("error", onConnectionError);
  events.addEventListener("access_revoked", () => {
    events.close();
    onAccessRevoked();
  });

  return () => events.close();
}
