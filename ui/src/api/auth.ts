import { apiRequest } from "./client";

export type Role = "viewer" | "operator" | "admin";

export interface UIAccessToken {
  access_token: string;
  token_type: string;
}

export interface UserRead {
  id: string;
  username: string;
  email: string;
  role: Role;
  created_at: string;
}

// POST /auth/ui-login — form-encoded, sets the httpOnly refresh_token
// cookie as a side effect (Set-Cookie handled by the browser, invisible
// here). skipAuth: true because there is no access token yet to attach,
// and a 401 here means "bad credentials", not "expired session" — must
// not trigger the refresh-retry dance.
export async function uiLogin(username: string, password: string): Promise<UIAccessToken> {
  const form = new URLSearchParams();
  form.set("username", username);
  form.set("password", password);
  return apiRequest<UIAccessToken>("/auth/ui-login", { method: "POST", form, skipAuth: true });
}

// POST /auth/ui-refresh — no body; relies on the refresh_token cookie.
// skipAuth: true for the same reason as above — this IS the refresh
// mechanism, it must not recursively trigger itself on a 401.
export async function uiRefresh(): Promise<UIAccessToken> {
  return apiRequest<UIAccessToken>("/auth/ui-refresh", { method: "POST", skipAuth: true });
}

// POST /auth/ui-logout — no body; revokes + clears the refresh cookie.
export async function uiLogout(): Promise<void> {
  return apiRequest<void>("/auth/ui-logout", { method: "POST", skipAuth: true });
}

export async function getMe(): Promise<UserRead> {
  return apiRequest<UserRead>("/auth/me", { method: "GET" });
}
