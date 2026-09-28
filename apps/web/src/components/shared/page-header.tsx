export function PageHeader({ eyebrow, title, description, action }: { eyebrow?: string; title: string; description?: string; action?: React.ReactNode }) {
  return <div className="flex flex-wrap items-end justify-between gap-5 border-b border-border pb-6 sm:pb-7">
    <div className="min-w-0 max-w-3xl">
      {eyebrow && <p className="eyebrow mb-3">{eyebrow}</p>}
      <h1 className="text-[2rem] font-semibold leading-[1.08] tracking-[-0.04em] text-foreground sm:text-[2.65rem]">{title}</h1>
      {description && <p className="mt-3 max-w-2xl text-sm leading-7 text-muted-foreground sm:text-[15px]">{description}</p>}
    </div>
    {action && <div className="flex shrink-0 flex-wrap items-center gap-2">{action}</div>}
  </div>;
}
