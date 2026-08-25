'use client'

/**
 * Dialog primitive built on Radix, replacing the hand-rolled overlay+card that
 * several pages duplicated (and which trapped no focus and ignored Escape).
 */
import * as Dialog from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { cn } from '@/lib/utils'

const WIDTHS = {
  sm: 'max-w-sm',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
  xl: 'max-w-4xl',
} as const

interface ModalProps {
  open: boolean
  onClose: () => void
  title: string
  description?: string
  size?: keyof typeof WIDTHS
  /** Rendered in a bordered footer, right-aligned. */
  footer?: React.ReactNode
  children: React.ReactNode
}

export function Modal({
  open,
  onClose,
  title,
  description,
  size = 'md',
  footer,
  children,
}: ModalProps) {
  return (
    <Dialog.Root open={open} onOpenChange={next => !next && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-brand-navy/60 backdrop-blur-sm" />
        <Dialog.Content
          className={cn(
            'fixed left-1/2 top-1/2 z-50 flex max-h-[85vh] w-[calc(100vw-2rem)] -translate-x-1/2',
            '-translate-y-1/2 flex-col rounded-xl border border-border bg-card shadow-xl',
            WIDTHS[size],
          )}
        >
          <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-3.5">
            <div className="min-w-0">
              <Dialog.Title className="truncate text-base font-semibold text-foreground">
                {title}
              </Dialog.Title>
              {description && (
                <Dialog.Description className="mt-0.5 text-sm text-muted-foreground">
                  {description}
                </Dialog.Description>
              )}
            </div>
            <Dialog.Close
              aria-label="Close"
              className="rounded-lg p-1 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              <X className="h-4 w-4" />
            </Dialog.Close>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>

          {footer && (
            <div className="flex items-center justify-end gap-2 border-t border-border px-5 py-3">
              {footer}
            </div>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

interface DetailListProps {
  children: React.ReactNode
}

/** Label/value list used inside detail modals. */
export function DetailList({ children }: DetailListProps) {
  return <dl className="divide-y divide-border">{children}</dl>
}

interface DetailRowProps {
  label: string
  children: React.ReactNode
}

export function DetailRow({ label, children }: DetailRowProps) {
  return (
    <div className="grid grid-cols-3 gap-3 py-2.5">
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="col-span-2 break-words text-sm text-foreground">{children}</dd>
    </div>
  )
}
