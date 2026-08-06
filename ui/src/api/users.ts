import { api } from "./client";
import type { Role, UserRead } from "./auth";

export type { UserRead };

export interface UserUpdate {
  email?: string;
  role?: Role;
}

export function listUsers(params: { limit?: number; offset?: number } = {}): Promise<UserRead[]> {
  return api.get<UserRead[]>("/users", params);
}

export function updateUser(userId: string, payload: UserUpdate): Promise<UserRead> {
  return api.patch<UserRead>(`/users/${encodeURIComponent(userId)}`, payload);
}

export function deactivateUser(userId: string): Promise<UserRead> {
  return api.post<UserRead>(`/users/${encodeURIComponent(userId)}/deactivate`);
}

export function reactivateUser(userId: string): Promise<UserRead> {
  return api.post<UserRead>(`/users/${encodeURIComponent(userId)}/reactivate`);
}
