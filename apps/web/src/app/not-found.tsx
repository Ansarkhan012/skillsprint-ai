import Link from "next/link";
import { Button } from "@/components/ui/button";
export default function NotFound() {
  return <main className="mx-auto max-w-xl px-5 py-20"><p className="text-sm font-semibold text-primary">404</p><h1 className="mt-3 text-2xl font-semibold">Page not found</h1><p className="mt-3 text-sm text-muted-foreground">This address does not point to an available workspace page.</p><Button asChild className="mt-6"><Link href="/app/dashboard">Return to dashboard</Link></Button></main>;
}
