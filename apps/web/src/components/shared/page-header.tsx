export function PageHeader({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description?: string; action?: React.ReactNode }) {
  return <div className="flex flex-wrap items-end justify-between gap-4">
    <div className="min-w-0 max-w-3xl">
      {eyebrow && <p className="eyebrow mb-1">{eyebrow}</p>}
      <h1 className="page-title text-foreground">{title}</h1>
      {description && <p className="mt-1 max-w-2xl text-sm leading-6 text-muted-foreground">{description}</p>}
    </div>
    {action && <div className="flex shrink-0 flex-wrap items-center gap-2">{action}</div>}
  </div>;
}
