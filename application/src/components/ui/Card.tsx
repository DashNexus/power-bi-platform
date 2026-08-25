/**
 * Surface container primitive.
 *
 * Replaces the ad-hoc `rounded-xl border border-gray-200 bg-white shadow-sm`
 * strings that had drifted into more than a dozen spellings. Use `interactive`
 * for cards that are themselves links or buttons.
 */
import { forwardRef } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const cardVariants = cva('rounded-xl border bg-card text-card-foreground', {
  variants: {
    variant: {
      default: 'border-border shadow-sm',
      flat: 'border-border',
      muted: 'border-border bg-muted shadow-none',
    },
    interactive: {
      true: 'transition-colors hover:border-primary/50 hover:bg-accent/50',
      false: '',
    },
  },
  defaultVariants: { variant: 'default', interactive: false },
})

export interface CardProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof cardVariants> {}

export const Card = forwardRef<HTMLDivElement, CardProps>(function Card(
  { className, variant, interactive, ...props },
  ref,
) {
  return (
    <div ref={ref} className={cn(cardVariants({ variant, interactive }), className)} {...props} />
  )
})

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('flex flex-col gap-1 border-b border-border px-5 py-4', className)} {...props} />
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h2 className={cn('text-sm font-semibold text-foreground', className)} {...props} />
}

export function CardDescription({ className, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn('text-sm text-muted-foreground', className)} {...props} />
}

export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('px-5 py-4', className)} {...props} />
}

export function CardFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('flex items-center gap-2 border-t border-border px-5 py-3', className)}
      {...props}
    />
  )
}
