const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export type MeetingSummary = {
  overview: string; decisions: string[]; unresolved: string[]; next_actions: string[];
};
export type SummaryState = {
  conversation_id: string;
  status: "queued" | "generating" | "succeeded" | "failed";
  attempt: number; result: MeetingSummary | null; error_code: string | null;
  message_count: number; created_at: string; completed_at: string | null;
};
export async function getSummary(id: string): Promise<SummaryState | null> {
  const response = await fetch(`${API_URL}/conversations/${id}/summary`, {credentials: "include"});
  if (!response.ok) throw new Error("要約を読み込めませんでした。");
  return response.json() as Promise<SummaryState | null>;
}
export async function createSummary(id: string): Promise<SummaryState> {
  const response = await fetch(`${API_URL}/conversations/${id}/summary`, {method: "POST", credentials: "include"});
  if (!response.ok) {
    const message = response.status === 413 ? "会話が長いため、一度に要約できません。"
      : response.status === 422 ? "確定した発言がないため、要約を作成できません。"
      : response.status === 503 ? "AIの接続設定を確認してください。"
      : "要約を作成できませんでした。もう一度お試しください。";
    throw new Error(message);
  }
  return response.json() as Promise<SummaryState>;
}
