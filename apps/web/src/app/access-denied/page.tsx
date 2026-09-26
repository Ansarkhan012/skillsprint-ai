import Link from "next/link";
import { ShieldAlert } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function AccessDenied() {
  return <main className="flex min-h-screen items-center justify-center px-5"><div className="max-w-md rounded-md border border-border bg-card p-8 text-center shadow-panel"><ShieldAlert className="mx-auto text-destructive" size={32} aria-hidden="true" /><h1 className="mt-4 text-xl font-bold">Access unavailable</h1><p className="mt-2 text-sm leading-6 text-muted-foreground">Your profile is inactive, incomplete, or does not have permission for this area. Contact an administrator.</p><div className="mt-5 flex flex-wrap justify-center gap-2"><Button asChild variant="outline"><Link href="/app/dashboard">Dashboard</Link></Button><Button asChild variant="ghost"><Link href="/login">Sign in</Link></Button></div></div></main>;
}
