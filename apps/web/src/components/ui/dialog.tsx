"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogTitle = DialogPrimitive.Title;

export function DialogContent({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <DialogPrimitive.Portal>
    <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-foreground/50" />
    <DialogPrimitive.Content aria-describedby={undefined} className={`fixed inset-y-0 left-0 z-50 w-[min(19rem,85vw)] overflow-y-auto bg-sidebar text-sidebar-foreground shadow-xl focus:outline-none ${className}`}>
      <DialogPrimitive.Close className="absolute right-3 top-3 rounded-md p-2 text-sidebar-foreground hover:bg-white/10" aria-label="Close menu"><X size={18} /></DialogPrimitive.Close>
      {children}
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>;
}
