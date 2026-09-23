import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const styles = cva(
  "inline-flex items-center justify-center gap-2 rounded-md text-sm font-semibold transition-colors disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-3 focus-visible:outline-offset-2 focus-visible:outline-primary",
  { variants: {
    variant: {
      primary: "bg-primary text-primary-foreground hover:bg-primary/90",
      secondary: "bg-secondary text-foreground hover:bg-secondary/75",
      outline: "border border-border bg-card text-foreground hover:bg-muted",
      ghost: "text-foreground hover:bg-muted",
    },
    size: { default: "h-10 px-4", sm: "h-9 px-3", icon: "size-10" },
  }, defaultVariants: { variant: "primary", size: "default" } }
);

export function Button({ className, variant, size, asChild = false, ...props }: React.ComponentProps<"button"> & VariantProps<typeof styles> & { asChild?: boolean }) {
  const Component = asChild ? Slot : "button";
  return <Component className={cn(styles({ variant, size }), className)} {...props} />;
}
