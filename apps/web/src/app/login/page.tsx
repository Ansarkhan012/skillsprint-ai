"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { BookOpenCheck, Eye, EyeOff, LockKeyhole, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { createClient } from "@/lib/supabase/browser";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    const frame = requestAnimationFrame(() => setHydrated(true));
    return () => cancelAnimationFrame(frame);
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (!email.trim() || !password) { setError("Enter your email and password."); return; }
    setBusy(true);
    try {
      const { error: authError } = await createClient().auth.signInWithPassword({ email: email.trim(), password });
      if (authError) { setError("The email or password was not accepted."); return; }
      const next = new URLSearchParams(window.location.search).get("next");
      const destination = next?.startsWith("/app/") && !next.startsWith("//") ? next : "/app/dashboard";
      router.replace(destination);
      router.refresh();
    } catch {
      setError("Sign in is unavailable right now. Try again shortly.");
    } finally { setBusy(false); }
  }

  return <main className="grid min-h-screen lg:grid-cols-[minmax(0,1.1fr)_minmax(420px,0.9fr)]">
    <div className="flex min-h-64 flex-col justify-between bg-sidebar px-7 py-8 text-sidebar-foreground sm:px-12 lg:min-h-screen lg:px-16 lg:py-12">
      <div className="flex items-center gap-3"><span className="rounded-md bg-primary p-2"><BookOpenCheck size={22} aria-hidden="true" /></span><span className="text-lg font-bold tracking-tight">SkillSprint AI</span></div>
      <div className="hidden max-w-xl lg:block"><p className="text-xs font-bold uppercase tracking-[0.16em] text-sidebar-muted">Training intelligence workspace</p><h1 className="mt-5 text-4xl font-bold leading-tight tracking-tight">Onboarding work, organized around what matters.</h1><p className="mt-5 max-w-md text-base leading-7 text-sidebar-muted">A focused space for teams to manage learning, evidence, and progress with clarity.</p></div>
      <p className="hidden text-xs text-sidebar-muted lg:block">SkillSprint AI · Authorized workspace</p>
    </div>
    <div className="flex items-center justify-center bg-background px-5 py-12 sm:px-10"><div className="w-full max-w-md rounded-md border border-border bg-card p-7 shadow-panel sm:p-10">
      <div className="flex size-11 items-center justify-center rounded-md bg-secondary text-primary"><LockKeyhole size={22} aria-hidden="true" /></div>
      <h2 className="mt-6 text-2xl font-bold tracking-tight">Welcome back</h2><p className="mt-2 text-sm leading-6 text-muted-foreground">Sign in to your SkillSprint workspace.</p>
      <form onSubmit={submit} method="post" action="/login" className="mt-8 space-y-5" noValidate>
        <div><label htmlFor="email" className="mb-2 block text-sm font-semibold">Email address</label><Input id="email" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@company.com" required aria-invalid={!!error && !email} /></div>
        <div><label htmlFor="password" className="mb-2 block text-sm font-semibold">Password</label><div className="relative"><Input id="password" type={showPassword ? "text" : "password"} autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} className="pr-12" required aria-invalid={!!error && !password} /><button type="button" onClick={() => setShowPassword((value) => !value)} className="absolute inset-y-0 right-0 flex w-11 items-center justify-center rounded-r-md text-muted-foreground hover:text-foreground" aria-label={showPassword ? "Hide password" : "Show password"}>{showPassword ? <EyeOff size={18} /> : <Eye size={18} />}</button></div></div>
        {error && <p role="alert" className="rounded-md border border-destructive/25 bg-destructive/5 p-3 text-sm text-destructive">{error}</p>}
        <Button type="submit" className="w-full" disabled={!hydrated || busy}>{busy ? "Signing in…" : "Sign in"}</Button>
      </form>
      <p className="mt-8 flex items-center gap-2 border-t border-border pt-5 text-xs text-muted-foreground"><ShieldCheck size={15} aria-hidden="true" /> For authorized team members only.</p>
    </div></div>
  </main>;
}
