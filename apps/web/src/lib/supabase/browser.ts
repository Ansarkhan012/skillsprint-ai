"use client";

import { createBrowserClient } from "@supabase/ssr";
import { publicEnv } from "@/lib/env";

export function createClient() {
  const { url, anonKey } = publicEnv();
  return createBrowserClient(url, anonKey);
}
