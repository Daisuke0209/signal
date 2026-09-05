import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import DocumentsPage from "./page";

const user = {
  id: "user-1",
  name: "営業担当",
  email: "sales@example.com",
  organizations: [
    { id: "org-1", name: "営業部", slug: "sales", role: "member" },
  ],
};

const registered = {
  id: "document-1",
  organization_id: "org-1",
  filename: "料金表.pdf",
  content_type: "application/pdf",
  byte_size: 100,
  processing_status: "pending",
  processing_error: null,
  created_at: "2026-09-05T10:00:00Z",
  uploaded_by_name: "営業担当",
};

function response(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("document management page", () => {
  it("retries a failed document and shows its ready state", async () => {
    const failed = { ...registered, processing_status: "failed", processing_error: "PDF extraction failed" };
    vi.stubGlobal("fetch", vi.fn((input: string, init?: RequestInit) => {
      if (input.endsWith("/auth/me")) return Promise.resolve(response(user));
      if (input.includes("?organization_id=org-1")) return Promise.resolve(response([failed]));
      if (input.endsWith("/documents/document-1/retry") && init?.method === "POST") return Promise.resolve(response({ ...registered, processing_status: "ready" }));
      return Promise.reject(new Error("unexpected"));
    }));
    render(<DocumentsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "再解析" }));
    expect(await screen.findByText("利用可能")).toBeDefined();
  });
  it("shows registered documents and their parsing failure reason", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        if (input.endsWith("/auth/me")) return Promise.resolve(response(user));
        return Promise.resolve(
          response([
            {
              ...registered,
              id: "failed-document",
              filename: "画像PDF.pdf",
              processing_status: "failed",
              processing_error: "PDF extraction failed",
            },
          ]),
        );
      }),
    );

    render(<DocumentsPage />);

    expect(await screen.findByText("画像PDF.pdf")).toBeDefined();
    expect(screen.getByText("解析に失敗")).toBeDefined();
    expect(screen.getByText("PDF extraction failed")).toBeDefined();
    expect(
      screen.getByRole("link", { name: "商談ワークスペースへ戻る" }),
    ).toHaveProperty("href", expect.stringContaining("/"));
  });

  it("uploads a selected PDF and refreshes it with its completed parsing state", async () => {
    const fetchMock = vi.fn((input: string, init?: RequestInit) => {
      if (input.endsWith("/auth/me")) return Promise.resolve(response(user));
      if (input.includes("?organization_id=org-1")) return Promise.resolve(response([]));
      if (input.endsWith("/documents") && init?.method === "POST") {
        return Promise.resolve(response(registered));
      }
      if (input.endsWith("/documents/document-1/extract")) {
        return Promise.resolve(
          response({ ...registered, processing_status: "ready" }),
        );
      }
      return Promise.reject(new Error(`Unexpected request: ${input}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<DocumentsPage />);
    await screen.findByText("登録済みの資料はありません。");
    const file = new File(["%PDF-"], "料金表.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText("PDFを選択"), {
      target: { files: [file] },
    });

    expect(await screen.findByText("利用可能")).toBeDefined();
    expect(screen.getByText("料金表.pdf")).toBeDefined();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));
  });

  it("does not switch organizations while a document upload is in flight", async () => {
    let resolveUpload: (value: Response) => void = () => undefined;
    const uploadResponse = new Promise<Response>((resolve) => {
      resolveUpload = resolve;
    });
    const multipleOrganizations = {
      ...user,
      organizations: [
        ...user.organizations,
        { id: "org-2", name: "開発部", slug: "engineering", role: "member" },
      ],
    };
    const fetchMock = vi.fn((input: string, init?: RequestInit) => {
      if (input.endsWith("/auth/me")) {
        return Promise.resolve(response(multipleOrganizations));
      }
      if (input.includes("?organization_id=org-1")) return Promise.resolve(response([]));
      if (input.endsWith("/documents") && init?.method === "POST") {
        return uploadResponse;
      }
      if (input.endsWith("/documents/document-1/extract")) {
        return Promise.resolve(response({ ...registered, processing_status: "ready" }));
      }
      return Promise.reject(new Error(`Unexpected request: ${input}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<DocumentsPage />);
    await screen.findByText("登録済みの資料はありません。");
    fireEvent.change(screen.getByLabelText("PDFを選択"), {
      target: {
        files: [new File(["%PDF-"], "料金表.pdf", { type: "application/pdf" })],
      },
    });

    const organization = screen.getByLabelText("組織");
    expect((organization as HTMLSelectElement).disabled).toBe(true);
    fireEvent.change(organization, { target: { value: "org-2" } });
    expect((organization as HTMLSelectElement).value).toBe("org-1");
    expect(
      fetchMock.mock.calls.some(([url]) =>
        String(url).includes("?organization_id=org-2"),
      ),
    ).toBe(false);

    resolveUpload(response(registered));
    expect(await screen.findByText("利用可能")).toBeDefined();
    expect((organization as HTMLSelectElement).value).toBe("org-1");
  });

  it("keeps the current organization list when an earlier list request resolves late", async () => {
    let resolveSecondOrganization: (value: Response) => void = () => undefined;
    const secondOrganizationResponse = new Promise<Response>((resolve) => {
      resolveSecondOrganization = resolve;
    });
    const multipleOrganizations = {
      ...user,
      organizations: [
        ...user.organizations,
        { id: "org-2", name: "開発部", slug: "engineering", role: "member" },
      ],
    };
    let firstOrganizationRequestCount = 0;
    const firstOrganizationDocument = {
      ...registered,
      id: "sales-document",
      filename: "営業部資料.pdf",
    };
    const secondOrganizationDocument = {
      ...registered,
      id: "engineering-document",
      organization_id: "org-2",
      filename: "開発部資料.pdf",
    };
    const fetchMock = vi.fn((input: string) => {
      if (input.endsWith("/auth/me")) {
        return Promise.resolve(response(multipleOrganizations));
      }
      if (input.includes("?organization_id=org-1")) {
        firstOrganizationRequestCount += 1;
        return Promise.resolve(
          response(
            firstOrganizationRequestCount === 1 ? [] : [firstOrganizationDocument],
          ),
        );
      }
      if (input.includes("?organization_id=org-2")) {
        return secondOrganizationResponse;
      }
      return Promise.reject(new Error(`Unexpected request: ${input}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<DocumentsPage />);
    await screen.findByText("登録済みの資料はありません。");
    const organization = screen.getByLabelText("組織");
    fireEvent.change(organization, { target: { value: "org-2" } });
    fireEvent.change(organization, { target: { value: "org-1" } });

    expect(await screen.findByText("営業部資料.pdf")).toBeDefined();
    resolveSecondOrganization(response([secondOrganizationDocument]));
    await waitFor(() => {
      expect(screen.queryByText("開発部資料.pdf")).toBeNull();
      expect(screen.getByText("営業部資料.pdf")).toBeDefined();
    });
  });

  it("ignores a late list error from an organization that is no longer selected", async () => {
    let rejectSecondOrganization: (reason?: unknown) => void = () => undefined;
    const secondOrganizationResponse = new Promise<Response>((_, reject) => {
      rejectSecondOrganization = reject;
    });
    const multipleOrganizations = {
      ...user,
      organizations: [
        ...user.organizations,
        { id: "org-2", name: "開発部", slug: "engineering", role: "member" },
      ],
    };
    let firstOrganizationRequestCount = 0;
    const fetchMock = vi.fn((input: string) => {
      if (input.endsWith("/auth/me")) {
        return Promise.resolve(response(multipleOrganizations));
      }
      if (input.includes("?organization_id=org-1")) {
        firstOrganizationRequestCount += 1;
        return Promise.resolve(
          response(
            firstOrganizationRequestCount === 1
              ? []
              : [{ ...registered, filename: "営業部資料.pdf" }],
          ),
        );
      }
      if (input.includes("?organization_id=org-2")) {
        return secondOrganizationResponse;
      }
      return Promise.reject(new Error(`Unexpected request: ${input}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<DocumentsPage />);
    await screen.findByText("登録済みの資料はありません。");
    const organization = screen.getByLabelText("組織");
    fireEvent.change(organization, { target: { value: "org-2" } });
    fireEvent.change(organization, { target: { value: "org-1" } });
    expect(await screen.findByText("営業部資料.pdf")).toBeDefined();

    rejectSecondOrganization(new Error("network failed"));
    await Promise.resolve();
    await waitFor(() => {
      expect(screen.queryByRole("alert")).toBeNull();
      expect(screen.getByText("営業部資料.pdf")).toBeDefined();
    });
  });
});
