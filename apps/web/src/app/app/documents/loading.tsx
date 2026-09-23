export default function DocumentsLoading() {
  return <div role="status" className="space-y-5" aria-label="Loading documents">
    <div className="h-8 w-48 animate-pulse rounded-md bg-muted" />
    <div className="h-20 animate-pulse rounded-md bg-muted" />
    <div className="h-64 animate-pulse rounded-md bg-muted" />
    <span className="sr-only">Loading documents…</span>
  </div>;
}
