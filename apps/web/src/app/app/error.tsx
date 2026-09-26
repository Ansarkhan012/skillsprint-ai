"use client";
import Link from "next/link";
import { Button } from "@/components/ui/button";
export default function WorkspaceError({ reset }: { error: Error; reset: () => void }) {
  return <section role="alert" className="rounded-md border border-border bg-card p-6"><h1 className="text-xl font-semibold">Workspace temporarily unavailable</h1><p className="mt-3 text-sm text-muted-foreground">The application could not load this page. Retry, or sign in again if your session has expired.</p><div className="mt-5 flex flex-wrap gap-2"><Button onClick={reset}>Retry</Button><Button asChild variant="outline"><Link href="/app/dashboard">Dashboard</Link></Button><Button asChild variant="ghost"><Link href="/login">Sign in</Link></Button></div></section>;
}
