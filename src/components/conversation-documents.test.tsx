import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({ listReadyDocuments: vi.fn(), getConversationDocuments: vi.fn(), saveConversationDocuments: vi.fn() }));
vi.mock("@/lib/conversation-documents-api", () => api);
import { ConversationDocuments } from "./conversation-documents";
it("retries a failed save", async () => { api.listReadyDocuments.mockResolvedValue([{id:"d",filename:"資料"}]); api.getConversationDocuments.mockResolvedValue([]); api.saveConversationDocuments.mockRejectedValueOnce(new Error()).mockResolvedValueOnce([]); render(<ConversationDocuments conversationId="c" organizationId="o" ended={false} />); fireEvent.click(screen.getByRole("button",{name:/参照資料/})); fireEvent.click(await screen.findByRole("checkbox")); fireEvent.click(screen.getByRole("button",{name:"保存"})); expect(await screen.findByRole("alert")).toBeDefined(); fireEvent.click(screen.getByRole("button",{name:"保存"})); await waitFor(()=>expect(api.saveConversationDocuments).toHaveBeenCalledTimes(2)); });
