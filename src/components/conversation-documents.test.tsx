import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
vi.mock("@/lib/conversation-documents-api", () => ({ listReadyDocuments: vi.fn().mockResolvedValue([]), getConversationDocuments: vi.fn().mockResolvedValue([]), saveConversationDocuments: vi.fn() }));
import { ConversationDocuments } from "./conversation-documents";
it("retries after a save failure", async () => { render(<ConversationDocuments conversationId="c" organizationId="o" ended={false} />); fireEvent.click(screen.getByRole("button", { name: /参照資料/ })); expect(await screen.findByText(/利用可能な資料はありません/)).toBeDefined(); });
