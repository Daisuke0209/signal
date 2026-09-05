import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const audioMocks = vi.hoisted(() => ({ start: vi.fn() }));
vi.mock("@/lib/audio-capture", () => ({
  startAudioCapture: audioMocks.start,
  captureFailure: () => "cancelled",
  stopStream: (stream: MediaStream | null) =>
    stream?.getTracks().forEach((track) => track.stop()),
}));
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

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  audioMocks.start.mockReset();
});

describe("authentication page", () => {
  it("stops both sources and updates the UI when a source track ends", async () => {
    const listeners = new Map<string, () => void>();
    const tabTrack = {
      stop: vi.fn(),
      addEventListener: vi.fn((name: string, callback: () => void) =>
        listeners.set(name, callback),
      ),
    } as unknown as MediaStreamTrack;
    const micTrack = {
      stop: vi.fn(),
      addEventListener: vi.fn((name: string, callback: () => void) =>
        listeners.set(`mic-${name}`, callback),
      ),
    } as unknown as MediaStreamTrack;
    audioMocks.start.mockResolvedValue({
      displayStream: {
        getTracks: () => [tabTrack],
        getAudioTracks: () => [tabTrack],
      },
      microphoneStream: {
        getTracks: () => [micTrack],
        getAudioTracks: () => [micTrack],
      },
    });
    const user = {
      ...currentUser,
      organizations: [
        { id: "org-1", name: "Demo", slug: "demo", role: "admin" },
      ],
    };
    const detail = {
      id: "conversation-1",
      organization_id: "org-1",
      created_by_user_id: currentUser.id,
      status: "active",
      created_at: "2026-09-05T12:00:00Z",
      participants: [],
      messages: [],
    };
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse(user))
        .mockResolvedValueOnce(
          jsonResponse([
            {
              id: detail.id,
              organization_id: detail.organization_id,
              status: detail.status,
              created_at: detail.created_at,
            },
          ]),
        )
        .mockResolvedValueOnce(jsonResponse(detail)),
    );
    render(<Home />);
    await screen.findByText("進行中の商談");
    fireEvent.click(
      screen.getByRole("button", { name: "Meet音声とマイクを取得" }),
    );
    await screen.findByText("共有音声・マイクを取得中");
    listeners.get("ended")?.();
    expect(await screen.findByText("共有音声が終了しました。")).toBeDefined();
    expect(screen.getByText("停止中")).toBeDefined();
    expect(tabTrack.stop).toHaveBeenCalled();
    expect(micTrack.stop).toHaveBeenCalled();
  });

  it("stops streams that resolve after the workspace unmounts", async () => {
    let resolveCapture: ((value: unknown) => void) | undefined;
    audioMocks.start.mockReturnValue(
      new Promise((resolve) => {
        resolveCapture = resolve;
      }),
    );
    const tabTrack = {
      stop: vi.fn(),
      addEventListener: vi.fn(),
    } as unknown as MediaStreamTrack;
    const micTrack = {
      stop: vi.fn(),
      addEventListener: vi.fn(),
    } as unknown as MediaStreamTrack;
    const user = {
      ...currentUser,
      organizations: [
        { id: "org-1", name: "Demo", slug: "demo", role: "admin" },
      ],
    };
    const detail = {
      id: "conversation-1",
      organization_id: "org-1",
      created_by_user_id: currentUser.id,
      status: "active",
      created_at: "2026-09-05T12:00:00Z",
      participants: [],
      messages: [],
    };
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse(user))
        .mockResolvedValueOnce(
          jsonResponse([
            {
              id: detail.id,
              organization_id: detail.organization_id,
              status: detail.status,
              created_at: detail.created_at,
            },
          ]),
        )
        .mockResolvedValueOnce(jsonResponse(detail)),
    );
    const view = render(<Home />);
    await screen.findByText("進行中の商談");
    fireEvent.click(
      screen.getByRole("button", { name: "Meet音声とマイクを取得" }),
    );
    view.unmount();
    resolveCapture?.({
      displayStream: {
        getTracks: () => [tabTrack],
        getAudioTracks: () => [tabTrack],
      },
      microphoneStream: {
        getTracks: () => [micTrack],
        getAudioTracks: () => [micTrack],
      },
    });
    await Promise.resolve();
    expect(tabTrack.stop).toHaveBeenCalled();
    expect(micTrack.stop).toHaveBeenCalled();
  });
  it("renders an existing conversation in message order", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(userResponse())
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify([
            {
              id: "conversation-1",
              organization_id: "org-1",
              status: "active",
              created_at: "2026-09-05T12:00:00Z",
            },
          ]),
          { status: 200 },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: "conversation-1",
            organization_id: "org-1",
            created_by_user_id: "user-1",
            status: "active",
            created_at: "2026-09-05T12:00:00Z",
            participants: [],
            messages: [
              {
                id: "message-1",
                participant_id: "participant-1",
                speaker_label: "通話相手",
                side: "customer",
                sequence_number: 1,
                content: "最初の発言",
              },
              {
                id: "message-2",
                participant_id: "participant-2",
                speaker_label: "自分",
                side: "sales_rep",
                sequence_number: 2,
                content: "次の発言",
              },
            ],
          }),
          { status: 200 },
        ),
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

  it("creates a conversation with the server-provided organization", async () => {
    const userWithOrganization = {
      ...currentUser,
      organizations: [
        {
          id: "org-1",
          name: "Signal Demo",
          slug: "signal-demo",
          role: "admin",
        },
      ],
    };
    const created = {
      id: "conversation-2",
      organization_id: "org-1",
      status: "active",
      created_at: "2026-09-05T12:00:00Z",
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(userWithOrganization))
      .mockResolvedValueOnce(conversationsResponse())
      .mockResolvedValueOnce(jsonResponse(created))
      .mockResolvedValueOnce(
        jsonResponse({
          ...created,
          created_by_user_id: currentUser.id,
          participants: [],
          messages: [],
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    render(<Home />);

    await screen.findByText("Demo User");
    fireEvent.click(screen.getByRole("button", { name: "新規作成" }));

    await screen.findByText("会話を受け取る準備ができました");
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "http://localhost:8000/conversations",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ organization_id: "org-1" }),
      }),
    );
  });

  it("refreshes the transcript after adding a customer message", async () => {
    const detail = {
      id: "conversation-1",
      organization_id: "org-1",
      created_by_user_id: currentUser.id,
      status: "active",
      created_at: "2026-09-05T12:00:00Z",
      participants: [],
      messages: [],
    };
    const refreshed = {
      ...detail,
      messages: [
        {
          id: "message-3",
          participant_id: "participant-1",
          speaker_label: "通話相手",
          side: "customer",
          sequence_number: 1,
          content: "顧客の発言",
        },
      ],
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(userResponse())
      .mockResolvedValueOnce(
        jsonResponse([
          {
            id: detail.id,
            organization_id: detail.organization_id,
            status: detail.status,
            created_at: detail.created_at,
          },
        ]),
      )
      .mockResolvedValueOnce(jsonResponse(detail))
      .mockResolvedValueOnce(jsonResponse(refreshed.messages[0]))
      .mockResolvedValueOnce(jsonResponse(refreshed));
    vi.stubGlobal("fetch", fetchMock);
    render(<Home />);

    await screen.findByText("会話を受け取る準備ができました");
    expect(screen.queryByLabelText("発言")).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "音声が使えないときは" }),
    );
    fireEvent.change(screen.getByLabelText("話者"), {
      target: { value: "customer" },
    });
    fireEvent.change(screen.getByLabelText("発言"), {
      target: { value: "顧客の発言" },
    });
    fireEvent.click(screen.getByRole("button", { name: "追加" }));

    expect(await screen.findByText("顧客の発言")).toBeDefined();
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "http://localhost:8000/conversations/conversation-1/messages",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("keeps the workspace visible when selecting a conversation fails", async () => {
    const list = [
      {
        id: "conversation-1",
        organization_id: "org-1",
        status: "active",
        created_at: "2026-09-05T12:00:00Z",
      },
      {
        id: "conversation-2",
        organization_id: "org-1",
        status: "active",
        created_at: "2026-09-05T12:01:00Z",
      },
    ];
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(userResponse())
      .mockResolvedValueOnce(jsonResponse(list))
      .mockResolvedValueOnce(
        jsonResponse({
          ...list[0],
          created_by_user_id: currentUser.id,
          participants: [],
          messages: [],
        }),
      )
      .mockResolvedValueOnce(emptyResponse(500));
    vi.stubGlobal("fetch", fetchMock);
    render(<Home />);

    await screen.findByText("進行中の商談");
    fireEvent.click(screen.getAllByRole("button", { name: /商談/ })[1]);

    expect(
      await screen.findByText("会話を読み込めませんでした。"),
    ).toBeDefined();
    expect(screen.getByText("営業支援")).toBeDefined();
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
      await screen.findByText(
        "メールアドレスまたはパスワードが正しくありません。",
      ),
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
