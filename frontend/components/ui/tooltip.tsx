"use client"

import { Tooltip as TooltipPrimitive } from "@base-ui/react/tooltip"

import { cn } from "@/lib/utils"

interface TooltipProps {
  content: React.ReactNode
  children: React.ReactNode
  side?: "top" | "bottom" | "left" | "right"
  sideOffset?: number
}

// Self-contained tooltip: includes its own Provider so each instance works
// standalone wherever a keyword/symbol is rendered inside answer text.
function Tooltip({ content, children, side = "top", sideOffset = 6 }: TooltipProps) {
  return (
    <TooltipPrimitive.Provider delay={120}>
      <TooltipPrimitive.Root>
        <TooltipPrimitive.Trigger render={<span className="cursor-help" />}>
          {children}
        </TooltipPrimitive.Trigger>
        <TooltipPrimitive.Portal>
          <TooltipPrimitive.Positioner side={side} sideOffset={sideOffset} className="isolate z-50">
            <TooltipPrimitive.Popup
              className={cn(
                "z-50 max-w-xs rounded-md bg-popover px-2.5 py-1.5 text-xs font-normal not-italic normal-case leading-snug text-popover-foreground shadow-md ring-1 ring-foreground/10 outline-hidden",
                "origin-(--transform-origin) duration-100 data-open:animate-in data-open:fade-in-0 data-open:zoom-in-95 data-closed:animate-out data-closed:fade-out-0 data-closed:zoom-out-95"
              )}
            >
              {content}
            </TooltipPrimitive.Popup>
          </TooltipPrimitive.Positioner>
        </TooltipPrimitive.Portal>
      </TooltipPrimitive.Root>
    </TooltipPrimitive.Provider>
  )
}

export { Tooltip }
