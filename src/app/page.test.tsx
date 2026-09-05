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
