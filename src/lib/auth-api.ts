const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type CurrentUser = {
  id: string;
  name: string;
  email: string;
};

function request(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${API_URL}${path}`, {
    ...init,
    credentials: "include",
  });
}

export async function getCurrentUser(): Promise<CurrentUser | null> {
  const response = await request("/auth/me");

  if (response.status === 401) {
    return null;
  }

  if (!response.ok) {
    throw new Error("Failed to restore the authentication session");
  }

  return (await response.json()) as CurrentUser;
}

export async function login(email: string, password: string): Promise<boolean> {
  const response = await request("/auth/login", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ email, password }),
  });

  if (response.status === 401) {
    return false;
  }

  if (!response.ok) {
    throw new Error("Failed to log in");
  }

  return true;
}

export async function logout(): Promise<void> {
  const response = await request("/auth/logout", { method: "POST" });

  if (!response.ok) {
    throw new Error("Failed to log out");
  }
}
