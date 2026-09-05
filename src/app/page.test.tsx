import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import Home from "./page";

const currentUser = {
  id: "34c26d3e-5562-4dd4-8d95-6347f346db58",
  name: "Demo User",
  email: "demo@signal.local",
  organizations: [],
};

function emptyResponse(status: number): Response {
  return new Response(null, { status });
}

function userResponse(): Response {
  return new Response(JSON.stringify(currentUser), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function conversationsResponse(): Response {
  return new Response(JSON.stringify([]), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("authentication page", () => {
  it("renders an existing conversation in message order", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(userResponse())
      .mockResolvedValueOnce(
        new Response(JSON.stringify([{ id: "conversation-1", organization_id: "org-1", status: "active", created_at: "2026-09-05T12:00:00Z" }]), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ id: "conversation-1", organization_id: "org-1", created_by_user_id: "user-1", status: "active", created_at: "2026-09-05T12:00:00Z", participants: [], messages: [{ id: "message-1", participant_id: "participant-1", speaker_label: "通話相手", side: "customer", sequence_number: 1, content: "最初の発言" }, { id: "message-2", participant_id: "participant-2", speaker_label: "自分", side: "sales_rep", sequence_number: 2, content: "次の発言" }] }), { status: 200 }),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<Home />);

    expect(await screen.findByText("最初の発言")).toBeDefined();
    expect(screen.getByText("次の発言")).toBeDefined();
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "http://localhost:8000/conversations/conversation-1",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("restores an existing session", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(userResponse())
      .mockResolvedValueOnce(conversationsResponse());
    vi.stubGlobal("fetch", fetchMock);

    render(<Home />);

    expect(await screen.findByText("Demo User")).toBeDefined();
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/auth/me",
      expect.objectContaining({ credentials: "include" }),
    );
  });

  it("logs in and displays the current user", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(emptyResponse(401))
      .mockResolvedValueOnce(emptyResponse(204))
      .mockResolvedValueOnce(userResponse())
      .mockResolvedValueOnce(conversationsResponse());
    vi.stubGlobal("fetch", fetchMock);

    render(<Home />);

    await screen.findByRole("heading", { name: "Signalにログイン" });
    fireEvent.change(screen.getByLabelText("パスワード"), {
      target: { value: "demo-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "ログイン" }));

    expect(await screen.findByText("Demo User")).toBeDefined();
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://localhost:8000/auth/login",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        body: JSON.stringify({
          email: "demo@signal.local",
          password: "demo-password",
        }),
      }),
    );
  });

  it("shows an error when credentials are invalid", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(emptyResponse(401))
      .mockResolvedValueOnce(emptyResponse(401));
    vi.stubGlobal("fetch", fetchMock);

    render(<Home />);

    await screen.findByRole("heading", { name: "Signalにログイン" });
    fireEvent.change(screen.getByLabelText("パスワード"), {
      target: { value: "wrong-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "ログイン" }));

    expect(
      await screen.findByText("メールアドレスまたはパスワードが正しくありません。"),
    ).toBeDefined();
  });

  it("logs out and returns to the login form", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(userResponse())
      .mockResolvedValueOnce(conversationsResponse())
      .mockResolvedValueOnce(emptyResponse(204));
    vi.stubGlobal("fetch", fetchMock);

    render(<Home />);

    await screen.findByText("Demo User");
    fireEvent.click(screen.getByRole("button", { name: "ログアウト" }));

    expect(
      await screen.findByRole("heading", { name: "Signalにログイン" }),
    ).toBeDefined();
    await waitFor(() => {
      expect(fetchMock).toHaveBeenNthCalledWith(
        3,
        "http://localhost:8000/auth/logout",
        expect.objectContaining({
          method: "POST",
          credentials: "include",
        }),
      );
    });
  });
});
