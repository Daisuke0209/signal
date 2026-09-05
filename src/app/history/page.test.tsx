import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import HistoryPage from "./page";
import { getConversation, getCurrentUser, listConversations, type Conversation, type ConversationDetail } from "@/lib/auth-api";
import { createSummary, getSummary, type SummaryState } from "@/lib/summaries-api";

vi.mock("@/lib/auth-api", () => ({ getConversation: vi.fn(), getCurrentUser: vi.fn(), listConversations: vi.fn() }));
vi.mock("@/lib/summaries-api", () => ({ createSummary: vi.fn(), getSummary: vi.fn() }));
const one: Conversation = { id: "one", organization_id: "org", status: "ended", created_at: "2026-09-05T10:00:00Z" };
const two: Conversation = { ...one, id: "two", created_at: "2026-09-05T11:00:00Z" };
function detail(item: Conversation): ConversationDetail {
  return { ...item, created_by_user_id: "u", participants: [], messages: [{ id: item.id, participant_id: "p", side: "customer", speaker_label: "顧客", sequence_number: 1, content: `${item.id}の確定発言` }] };
}
const summary: SummaryState = { conversation_id: "one", status: "succeeded", attempt: 1, result: {overview: "価格と導入時期を相談。", decisions: [], unresolved: ["見積りの確認"], next_actions: ["担当者が見積りを用意する"]}, error_code: null, message_count: 1, created_at: one.created_at, completed_at: one.created_at };
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(getCurrentUser).mockResolvedValue({ id: "u", name: "利用者", email: "fictional@example.com", organizations: [] });
  vi.mocked(listConversations).mockResolvedValue([one]);
  vi.mocked(getConversation).mockResolvedValue(detail(one));
  vi.mocked(getSummary).mockResolvedValue(null);
});
afterEach(cleanup);

describe("meeting history", () => {
  it("restores the saved summary beside final transcripts and excludes active meetings", async () => {
    vi.mocked(listConversations).mockResolvedValue([one, {...two, status: "active"}]);
    vi.mocked(getSummary).mockResolvedValue(summary);
    render(<HistoryPage />);
    await screen.findByText("価格と導入時期を相談。");
    expect(screen.getByText("oneの確定発言")).toBeTruthy();
    expect(screen.getByText("見積りの確認")).toBeTruthy();
    expect(screen.queryByRole("button", {name: "要約を作成"})).toBeNull();
    expect(screen.getAllByRole("button", {pressed: true})).toHaveLength(1);
    expect(createSummary).not.toHaveBeenCalled();
  });
  it("keeps the creation action retryable after a failed POST", async () => {
    vi.mocked(createSummary).mockRejectedValueOnce(new Error("要約を作成できませんでした。"));
    vi.mocked(createSummary).mockResolvedValueOnce(summary);
    render(<HistoryPage />);
    fireEvent.click(await screen.findByRole("button", {name: "要約を作成"}));
    await screen.findByRole("alert");
    const button = screen.getByRole("button", {name: "要約を作成"}) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));
    fireEvent.click(button);
    await screen.findByText("価格と導入時期を相談。");
    expect(createSummary).toHaveBeenCalledTimes(2);
  });
  it.each(["resolve", "reject"])("ignores a previous meeting's delayed %s after switching", async mode => {
    vi.mocked(listConversations).mockResolvedValue([one, two]);
    let resolve!: (value: ConversationDetail) => void;
    let reject!: (reason: Error) => void;
    const delayed = new Promise<ConversationDetail>((yes, no) => {resolve = yes; reject = no;});
    vi.mocked(getConversation).mockImplementation(id => id === "one" ? delayed : Promise.resolve(detail(two)));
    render(<HistoryPage />);
    const choices = await screen.findAllByRole("button", {pressed: false});
    fireEvent.click(choices[0]);
    await screen.findByText("twoの確定発言");
    await act(async () => { if (mode === "resolve") resolve(detail(one)); else reject(new Error("old failure")); });
    expect(screen.queryByText("oneの確定発言")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
