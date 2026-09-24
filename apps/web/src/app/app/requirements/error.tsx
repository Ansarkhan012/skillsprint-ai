"use client";

import { AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";

export default function RequirementsError({ reset }: { error: Error; reset: () => void }) {
  return <div role="alert" className="rounded-md border border-destructive/25 bg-card p-6 shadow-panel">
    <AlertCircle size={24} className="text-destructive" aria-hidden="true" />
    <h1 className="mt-3 text-xl font-semibold">Requirements are temporarily unavailable</h1>
    <p className="mt-2 text-sm text-muted-foreground">Check the API connection, then try loading this workspace again.</p>
    <Button className="mt-5" variant="outline" onClick={reset}>Try again</Button>
  </div>;
}
