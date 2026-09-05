import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const liveMocks = vi.hoisted(() => ({ start: vi.fn(), abort: vi.fn(), stop: vi.fn() }));
const suggestionMocks = vi.hoisted(() => ({
  connect: vi.fn(),
  getLatest: vi.fn(),
}));
vi.mock("@/lib/live-transcription", () => ({
  startLiveTranscription: liveMocks.start,
  transcriptionError: () => "文字起こしが中断しました。",
}));
vi.mock("@/lib/suggestions-api", () => ({
  connectSuggestionEvents: suggestionMocks.connect,
  getLatestSuggestions: suggestionMocks.getLatest,
}));
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

beforeEach(() => {
  liveMocks.start.mockResolvedValue({ abort: liveMocks.abort, stop: liveMocks.stop });
  suggestionMocks.connect.mockImplementation(() => vi.fn());
  suggestionMocks.getLatest.mockResolvedValue({
    conversation_id: "",
    latest_run: null,
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  audioMocks.start.mockReset();
  suggestionMocks.connect.mockReset();
  suggestionMocks.getLatest.mockReset();
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
    await screen.findByText("文字起こし中");
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

  it("renders the newest streamed proposal generation with sources and state", async () => {
    const detail = {
      id: "conversation-1",
      organization_id: "org-1",
      created_by_user_id: currentUser.id,
      status: "active",
      created_at: "2026-09-05T12:00:00Z",
      participants: [],
      messages: [],
    };
    const user = {
      ...currentUser,
      organizations: [
        { id: "org-1", name: "Demo", slug: "demo", role: "admin" },
      ],
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
    expect(suggestionMocks.connect).toHaveBeenCalledWith(
      detail.id,
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
    );
    const onState = suggestionMocks.connect.mock.calls[0][1] as (
      state: object,
    ) => void;
    const onConnectionError = suggestionMocks.connect.mock.calls[0][2] as () => void;

    onState({
        conversation_id: detail.id,
        latest_run: {
          id: "run-2",
          generation: 2,
          revision: 1,
          input_sequence_number: 2,
          status: "running",
          phase: "searching",
          error_code: null,
          created_at: detail.created_at,
          started_at: detail.created_at,
          completed_at: null,
          suggestions: [],
        },
      });
    expect(await screen.findByText("資料を調査中")).toBeDefined();

    onState({
        conversation_id: detail.id,
        latest_run: {
          id: "run-2",
          generation: 2,
          revision: 2,
          input_sequence_number: 2,
          status: "succeeded",
          phase: null,
          error_code: null,
          created_at: detail.created_at,
          started_at: detail.created_at,
          completed_at: detail.created_at,
          suggestions: [
            {
              id: "question-1",
              kind: "question",
              content: "導入時期を確認しますか？",
              position: 0,
              sources: [
                {
                  document_id: "document-1",
                  document_name: "料金表",
                  page_number: 2,
                  excerpt: "Standardは20名から利用できます。",
                },
              ],
            },
            {
              id: "response-1",
              kind: "response",
              content: "Standardプランをご案内します。",
              position: 1,
              sources: [],
            },
            {
              id: "confirmation-1",
              kind: "confirmation",
              content: "利用人数を確認します。",
              position: 2,
              sources: [],
            },
          ],
        },
      });
    expect(await screen.findByText("導入時期を確認しますか？")).toBeDefined();
    expect(screen.getByText("料金表 · p.2")).toBeDefined();
    expect(screen.getAllByText("根拠なし")).toHaveLength(2);

    onState({
        conversation_id: detail.id,
        latest_run: {
          id: "run-1",
          generation: 1,
          revision: 1,
          input_sequence_number: 1,
          status: "succeeded",
          phase: null,
          error_code: null,
          created_at: detail.created_at,
          started_at: detail.created_at,
          completed_at: detail.created_at,
          suggestions: [
            {
              id: "stale",
              kind: "question",
              content: "古い提案",
              position: 0,
              sources: [],
            },
          ],
        },
      });
    await waitFor(() => expect(screen.queryByText("古い提案")).toBeNull());

    onConnectionError();
    expect(await screen.findByText("提案の接続が切れています")).toBeDefined();
    onState({
        conversation_id: detail.id,
        latest_run: {
          id: "run-2",
          generation: 2,
          revision: 3,
          input_sequence_number: 2,
          status: "failed",
          phase: null,
          error_code: "timeout",
          created_at: detail.created_at,
          started_at: detail.created_at,
          completed_at: detail.created_at,
          suggestions: [],
        },
      });
    expect(
      await screen.findByText("提案を生成できませんでした"),
    ).toBeDefined();
  });

  it("clears proposals and replaces the event stream when switching conversations", async () => {
    const closeFirst = vi.fn();
    suggestionMocks.connect.mockImplementationOnce(() => closeFirst);
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
    const detail = (conversation: (typeof list)[number]) => ({
      ...conversation,
      created_by_user_id: currentUser.id,
      participants: [],
      messages: [],
    });
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(userResponse())
        .mockResolvedValueOnce(jsonResponse(list))
        .mockResolvedValueOnce(jsonResponse(detail(list[0])))
        .mockResolvedValueOnce(jsonResponse(detail(list[1]))),
    );
    render(<Home />);

    await screen.findByText("進行中の商談");
    const onFirstState = suggestionMocks.connect.mock.calls[0][1] as (
      state: object,
    ) => void;
    const onFirstError = suggestionMocks.connect.mock.calls[0][2] as () => void;
    onFirstState({
        conversation_id: list[0].id,
        latest_run: {
          id: "run-1",
          generation: 1,
          revision: 1,
          input_sequence_number: 1,
          status: "succeeded",
          phase: null,
          error_code: null,
          created_at: list[0].created_at,
          started_at: list[0].created_at,
          completed_at: list[0].created_at,
          suggestions: [
            {
              id: "proposal-1",
              kind: "question",
              content: "最初の提案",
              position: 0,
              sources: [],
            },
          ],
        },
      });
    await screen.findByText("最初の提案");

    fireEvent.click(screen.getAllByRole("button", { name: /商談/ })[1]);
    await waitFor(() => expect(closeFirst).toHaveBeenCalled());
    expect(screen.queryByText("最初の提案")).toBeNull();
    expect(suggestionMocks.connect).toHaveBeenNthCalledWith(
      2,
      "conversation-2",
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
    );
    onFirstError();
    await waitFor(() => {
      expect(screen.queryByText("提案の接続が切れています")).toBeNull();
    });
  });

  it("closes the proposal subscription on logout", async () => {
    const closeEvents = vi.fn();
    suggestionMocks.connect.mockImplementationOnce(() => closeEvents);
    const detail = {
      id: "conversation-1",
      organization_id: "org-1",
      created_by_user_id: currentUser.id,
      status: "active",
      created_at: "2026-09-05T12:00:00Z",
      participants: [],
      messages: [],
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
      .mockResolvedValueOnce(emptyResponse(204));
    vi.stubGlobal("fetch", fetchMock);
    render(<Home />);

    await screen.findByText("進行中の商談");
    fireEvent.click(screen.getByRole("button", { name: "ログアウト" }));

    await screen.findByRole("heading", { name: "Signalにログイン" });
    expect(closeEvents).toHaveBeenCalledOnce();
  });

  it("returns to login without reconnecting after suggestion access is revoked", async () => {
    const closeEvents = vi.fn();
    suggestionMocks.connect.mockImplementationOnce(() => closeEvents);
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
        .mockResolvedValueOnce(jsonResponse(detail)),
    );
    render(<Home />);

    await screen.findByText("進行中の商談");
    const onAccessRevoked = suggestionMocks.connect.mock.calls[0][3] as () => void;
    onAccessRevoked();

    expect(
      await screen.findByRole("heading", { name: "Signalにログイン" }),
    ).toBeDefined();
    expect(
      screen.getByText("認証が失効しました。もう一度ログインしてください。"),
    ).toBeDefined();
    expect(closeEvents).toHaveBeenCalledOnce();
    expect(suggestionMocks.connect).toHaveBeenCalledOnce();
  });

  it("rechecks authorization after a network error and later expires", async () => {
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
        .mockResolvedValueOnce(userResponse())
        .mockResolvedValueOnce(jsonResponse([detail]))
        .mockResolvedValueOnce(jsonResponse(detail))
        .mockRejectedValueOnce(new TypeError("network"))
        .mockResolvedValueOnce(emptyResponse(401)),
    );
    render(<Home />);
    await screen.findByText("進行中の商談");
    const onConnectionError = suggestionMocks.connect.mock.calls[0][2] as () => void;

    onConnectionError();
    await screen.findByText("提案の接続が切れています");
    await Promise.resolve();
    onConnectionError();

    expect(
      await screen.findByRole("heading", { name: "Signalにログイン" }),
    ).toBeDefined();
  });

  it("waits for live audio to flush before ending and keeps retry available on flush failure", async () => {
    let resolveStop: (() => void) | undefined;
    liveMocks.stop.mockImplementationOnce(
      () => new Promise<void>((resolve) => { resolveStop = resolve; }),
    );
    const track = { stop: vi.fn(), addEventListener: vi.fn() } as unknown as MediaStreamTrack;
    audioMocks.start.mockResolvedValue({
      displayStream: { getTracks: () => [track], getAudioTracks: () => [track] },
      microphoneStream: { getTracks: () => [track], getAudioTracks: () => [track] },
    });
    const detail = { id: "conversation-1", organization_id: "org-1", created_by_user_id: currentUser.id, status: "active", created_at: "2026-09-05T12:00:00Z", participants: [], messages: [] };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(userResponse())
      .mockResolvedValueOnce(jsonResponse([detail]))
      .mockResolvedValueOnce(jsonResponse(detail))
      .mockResolvedValueOnce(jsonResponse({ ...detail, status: "ended" }));
    vi.stubGlobal("fetch", fetchMock);
    render(<Home />);
    await screen.findByText("進行中の商談");
    fireEvent.click(screen.getByRole("button", { name: "Meet音声とマイクを取得" }));
    await screen.findByText("文字起こし中");
    fireEvent.click(screen.getByRole("button", { name: "商談を終了" }));
    expect(fetchMock).toHaveBeenCalledTimes(3);
    resolveStop?.();
    await screen.findByText("この商談は終了しました。文字起こしと発言の追加はできません。");
    expect(fetchMock).toHaveBeenCalledTimes(4);
  });

  it("does not end the conversation when live audio flush fails", async () => {
    liveMocks.stop.mockRejectedValueOnce(new Error("flush"));
    const track = { stop: vi.fn(), addEventListener: vi.fn() } as unknown as MediaStreamTrack;
    audioMocks.start.mockResolvedValue({
      displayStream: { getTracks: () => [track], getAudioTracks: () => [track] },
      microphoneStream: { getTracks: () => [track], getAudioTracks: () => [track] },
    });
    const detail = { id: "conversation-1", organization_id: "org-1", created_by_user_id: currentUser.id, status: "active", created_at: "2026-09-05T12:00:00Z", participants: [], messages: [] };
    const fetchMock = vi.fn().mockResolvedValueOnce(userResponse()).mockResolvedValueOnce(jsonResponse([detail])).mockResolvedValueOnce(jsonResponse(detail));
    vi.stubGlobal("fetch", fetchMock);
    render(<Home />);
    await screen.findByText("進行中の商談");
    fireEvent.click(screen.getByRole("button", { name: "Meet音声とマイクを取得" }));
    await screen.findByText("文字起こし中");
    fireEvent.click(screen.getByRole("button", { name: "商談を終了" }));
    expect(await screen.findByText("音声の確定に失敗しました。商談は進行中のまま、もう一度お試しください。")).toBeDefined();
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(screen.getByRole("button", { name: "商談を終了" })).toHaveProperty("disabled", false);
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
describe("approval requests", () => {
  const detail = {
    id: "conversation-approval",
    organization_id: "org-1",
    created_by_user_id: currentUser.id,
    status: "active",
    created_at: "2026-09-05T12:00:00Z",
    participants: [],
    messages: [],
  };
  const user = {
    ...currentUser,
    organizations: [{ id: "org-1", name: "Demo", slug: "demo", role: "admin" }],
  };

  it("shows an approval's impact and approves it", async () => {
    const pending = {
      id: "approval-1",
      conversation_id: detail.id,
      operation: "internal_handoff",
      target: "営業支援",
      input: { summary: "技術要件を確認する" },
      evidence: [
        {
          document_id: "document-1",
          document_name: "製品資料",
          page_number: 3,
          excerpt: "専門チームが導入を支援します。",
        },
      ],
      status: "pending",
      requested_by_user_id: currentUser.id,
      decided_by_user_id: null,
      decided_at: null,
      created_at: detail.created_at,
    };
    const fetchMock = vi
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
      .mockResolvedValueOnce(jsonResponse(detail))
      .mockResolvedValueOnce(jsonResponse([pending]))
      .mockResolvedValueOnce(
        jsonResponse({
          ...pending,
          status: "approved",
          decided_by_user_id: currentUser.id,
          decided_at: detail.created_at,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<Home />);

    await screen.findByText("進行中の商談");
    fireEvent.click(
      screen.getByRole("button", { name: /承認が必要な操作.*確認する/ }),
    );
    expect(await screen.findByText("技術要件を確認する")).toBeDefined();
    expect(screen.getByText("製品資料 · p.3")).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "承認" }));
    expect(await screen.findByText("承認済み")).toBeDefined();
    expect(fetchMock).toHaveBeenLastCalledWith(
      "http://localhost:8000/conversations/approvals/approval-1/approve",
      expect.objectContaining({ method: "POST", credentials: "include" }),
    );
  });

  it("creates an internal handoff approval and keeps an API failure visible", async () => {
    const created = {
      id: "approval-2",
      conversation_id: detail.id,
      operation: "internal_handoff",
      target: "営業支援",
      input: { summary: "導入日程を相談する" },
      evidence: [],
      status: "pending",
      requested_by_user_id: currentUser.id,
      decided_by_user_id: null,
      decided_at: null,
      created_at: detail.created_at,
    };
    const fetchMock = vi
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
      .mockResolvedValueOnce(jsonResponse(detail))
      .mockResolvedValueOnce(jsonResponse([]))
      .mockResolvedValueOnce(jsonResponse(created))
      .mockResolvedValueOnce(new Response(null, { status: 500 }));
    vi.stubGlobal("fetch", fetchMock);

    render(<Home />);

    await screen.findByText("進行中の商談");
    fireEvent.click(
      screen.getByRole("button", { name: /承認が必要な操作.*確認する/ }),
    );
    await screen.findByText("承認待ちの操作はありません。");
    fireEvent.change(screen.getByLabelText("依頼内容"), {
      target: { value: "導入日程を相談する" },
    });
    fireEvent.click(screen.getByRole("button", { name: "承認依頼を作成" }));

    expect(await screen.findByText("導入日程を相談する")).toBeDefined();
    expect(fetchMock).toHaveBeenNthCalledWith(
      5,
      "http://localhost:8000/conversations/conversation-approval/approvals",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          operation: "internal_handoff",
          target: "営業支援",
          input: { summary: "導入日程を相談する" },
          evidence: [],
        }),
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "却下" }));
    expect(
      await screen.findByText(
        "承認結果を保存できませんでした。もう一度お試しください。",
      ),
    ).toBeDefined();
  });
});
