import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ConfirmationItem, ConfirmationRequestError } from "@/lib/confirmation-items-api";
const api = vi.hoisted(() => ({ getConfirmationItems: vi.fn(), updateConfirmationItem: vi.fn() }));
vi.mock("@/lib/confirmation-items-api", async (original) => ({
  ...await original<typeof import("@/lib/confirmation-items-api")>(), ...api,
}));
import { ConfirmationChecklist } from "./confirmation-checklist";

const item: ConfirmationItem = {
  id: "item-1", content: "導入時期を確認する", status: "open", version: 1,
  origin_message_id: "message-1", evidence_message_id: null, evidence_excerpt: null,
  confirmation_source: null, created_at: "2026-09-06T00:00:00Z", updated_at: "2026-09-06T00:00:00Z",
};
const props = { conversationId: "c1", ended: false, refreshToken: "run:1" };
beforeEach(() => { api.getConfirmationItems.mockResolvedValue([item]); });
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it("retains cumulative items through new generation and shows automatic completion evidence", async () => {
  const view = render(<ConfirmationChecklist {...props} />);
  await screen.findByRole("checkbox", { name: item.content });
  api.getConfirmationItems.mockResolvedValue([
    { ...item, version: 2, status: "confirmed", confirmation_source: "auto", evidence_message_id: "m2", evidence_excerpt: "来月から導入したいです。" },
    { ...item, id: "item-2", content: "利用人数を確認する" },
  ]);
  view.rerender(<ConfirmationChecklist {...props} refreshToken="run:2" />);
  expect(await screen.findByText("来月から導入したいです。")).toBeDefined();
  expect((screen.getByRole("checkbox", { name: item.content }) as HTMLInputElement).checked).toBe(true);
  expect(screen.getAllByRole("checkbox")).toHaveLength(2);
  expect(screen.getByText("1 / 2 確認済み")).toBeDefined();
});

it("saves a manual correction and ignores a stale snapshot", async () => {
  api.getConfirmationItems.mockResolvedValue([{ ...item, status: "confirmed", version: 2, confirmation_source: "auto" }]);
  api.updateConfirmationItem.mockResolvedValue({ ...item, version: 3, confirmation_source: "manual" });
  const view = render(<ConfirmationChecklist {...props} />);
  fireEvent.click(await screen.findByRole("checkbox", { name: item.content }));
  await screen.findByText("手動で未確認に変更");
  expect(api.updateConfirmationItem).toHaveBeenCalledWith("c1", expect.objectContaining({ version: 2 }), "open");
  view.rerender(<ConfirmationChecklist {...props} refreshToken="run:2" />);
  await waitFor(() => expect(api.getConfirmationItems).toHaveBeenCalledTimes(2));
  expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(false);
});

it("reloads on conflict without silently overwriting the other change", async () => {
  api.updateConfirmationItem.mockRejectedValue(new ConfirmationRequestError(409));
  render(<ConfirmationChecklist {...props} />);
  fireEvent.click(await screen.findByRole("checkbox"));
  await screen.findByText(/状態が更新されたか商談が終了しました/);
  expect(api.getConfirmationItems).toHaveBeenCalledTimes(2);
  expect(api.updateConfirmationItem).toHaveBeenCalledTimes(1);
});

it("keeps the original status when saving fails and allows another attempt", async () => {
  api.updateConfirmationItem.mockRejectedValueOnce(new Error()).mockResolvedValueOnce({ ...item, status: "confirmed", version: 2, confirmation_source: "manual" });
  render(<ConfirmationChecklist {...props} />);
  fireEvent.click(await screen.findByRole("checkbox"));
  await screen.findByRole("alert");
  expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(false);
  fireEvent.click(screen.getByRole("checkbox"));
  await screen.findByText("手動で確認済み");
});

it("does not let an old conversation response enter a newly selected conversation", async () => {
  let resolveOld!: (value: ConfirmationItem[]) => void;
  api.getConfirmationItems.mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
    .mockResolvedValueOnce([{ ...item, id: "new", content: "新しい商談の確認" }]);
  const view = render(<ConfirmationChecklist {...props} />);
  await waitFor(() => expect(api.getConfirmationItems).toHaveBeenCalledWith("c1"));
  view.rerender(<ConfirmationChecklist {...props} conversationId="c2" />);
  await screen.findByText("新しい商談の確認");
  await act(async () => resolveOld([item]));
  expect(screen.queryByText(item.content)).toBeNull();
});

it("removes previously visible items when access is revoked", async () => {
  const view = render(<ConfirmationChecklist {...props} />);
  await screen.findByRole("checkbox");
  api.getConfirmationItems.mockRejectedValue(new ConfirmationRequestError(403));
  view.rerender(<ConfirmationChecklist {...props} refreshToken="run:2" />);
  await screen.findByRole("alert");
  expect(screen.queryByRole("checkbox")).toBeNull();
});

it("renders ended conversations read-only", async () => {
  render(<ConfirmationChecklist {...props} ended />);
  expect((await screen.findByRole("checkbox") as HTMLInputElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole("checkbox"));
  expect(api.updateConfirmationItem).not.toHaveBeenCalled();
});

it("does not replace a manual result with an in-flight read", async () => {
  let resolveRead!: (value: ConfirmationItem[]) => void;
  api.updateConfirmationItem.mockResolvedValue({ ...item, version: 2, status: "confirmed", confirmation_source: "manual" });
  const view = render(<ConfirmationChecklist {...props} />);
  await screen.findByRole("checkbox");
  api.getConfirmationItems.mockImplementationOnce(() => new Promise((resolve) => { resolveRead = resolve; }));
  view.rerender(<ConfirmationChecklist {...props} refreshToken="run:2" />);
  await waitFor(() => expect(api.getConfirmationItems).toHaveBeenCalledTimes(2));
  fireEvent.click(screen.getByRole("checkbox"));
  await screen.findByText("手動で確認済み");
  await act(async () => resolveRead([item]));
  expect((screen.getByRole("checkbox") as HTMLInputElement).checked).toBe(true);
});
