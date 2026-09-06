import { afterEach, expect, it, vi } from "vitest";
import { ConfirmationItem, ConfirmationRequestError, getConfirmationItems, updateConfirmationItem } from "./confirmation-items-api";
afterEach(() => vi.unstubAllGlobals());
it("uses authenticated requests and rejects an invalid snapshot", async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({items: []})))
    .mockResolvedValueOnce(new Response(JSON.stringify({unexpected: []})));
  vi.stubGlobal("fetch", fetchMock);
  expect(await getConfirmationItems("c1")).toEqual([]);
  expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/conversations/c1/confirmation-items", {credentials: "include"});
  await expect(getConfirmationItems("c1")).rejects.toThrow("Invalid confirmation snapshot");
});
it("sends the expected version and exposes a conflict without retrying the write", async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(null, {status:409}));
  vi.stubGlobal("fetch", fetchMock);
  await expect(updateConfirmationItem("c1", {id:"i1", version:3} as ConfirmationItem, "open")).rejects.toBeInstanceOf(ConfirmationRequestError);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/conversations/c1/confirmation-items/i1", expect.objectContaining({
    credentials: "include", method:"PATCH", body:JSON.stringify({status:"open",expected_version:3}),
  }));
});
