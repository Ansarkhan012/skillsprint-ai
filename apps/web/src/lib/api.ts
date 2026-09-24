import { cache } from "react";
import { apiBaseUrl } from "@/lib/env";

export type AppRole = "ADMIN" | "TRAINING_MANAGER" | "REVIEWER" | "MANAGER" | "EMPLOYEE";
export type Me = { id: string; display_name: string; roles: AppRole[] };
export type Health = { status: string; service: string };

export class ApiError extends Error {
  constructor(public status: number, public code: string) {
    super(code);
  }
}

export async function apiRequest<T>(path: string, token?: string): Promise<T> {
  const response = await fetch(`${apiBaseUrl()}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    cache: "no-store",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(response.status, body.code ?? "API_ERROR");
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => apiRequest<Health>("/api/v1/health"),
  me: (token: string) => apiRequest<Me>("/api/v1/me", token),
};

// React cache is scoped to one server render. No identity result is shared across users or requests.
export const requestMe = cache((token: string) => api.me(token));
