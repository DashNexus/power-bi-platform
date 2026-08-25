/**
 * Form control primitives: Input, Textarea, Select, Label, FieldError, Field.
 *
 * All three controls share one `controlClasses` string so a text input, a
 * textarea, and a native select line up pixel-for-pixel when stacked in a form.
 */
import { forwardRef } from 'react'
import { ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'

/** Control density. `sm` is for inline controls inside table rows and toolbars. */
export type ControlSize = 'sm' | 'md'

/** Shared shell for every text-entry control. `invalid` swaps in the error ring. */
export function controlClasses(invalid?: boolean, size: ControlSize = 'md'): string {
  return cn(
    'block w-full rounded-lg border bg-card text-foreground shadow-sm',
    size === 'sm' ? 'px-2 py-1 text-xs' : 'px-3 py-2 text-sm',
    'transition-colors focus:outline-none focus:ring-2 focus:ring-offset-0',
    'disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground',
    invalid
      ? 'border-destructive bg-destructive-subtle focus:border-destructive focus:ring-destructive'
      : 'border-input focus:border-primary focus:ring-ring',
  )
}

/**
 * Native `size` (a character-width hint) is dropped in favour of the density
 * scale the other primitives use; width comes from layout classes here.
 */
export interface InputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'size'> {
  invalid?: boolean
  size?: ControlSize
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, invalid, size = 'md', ...props },
  ref,
) {
  return (
    <input
      ref={ref}
      aria-invalid={invalid || undefined}
      className={cn(controlClasses(invalid, size), className)}
      {...props}
    />
  )
})

export interface TextareaProps
  extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  invalid?: boolean
  size?: ControlSize
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  { className, invalid, size = 'md', ...props },
  ref,
) {
  return (
    <textarea
      ref={ref}
      aria-invalid={invalid || undefined}
      className={cn(controlClasses(invalid, size), 'min-h-20 resize-y', className)}
      {...props}
    />
  )
})

/**
 * Native `size` (a visible-row count) is dropped in favour of the density scale
 * every other primitive uses. A multi-row select is a list box, not this control.
 */
export interface SelectProps
  extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, 'size'> {
  invalid?: boolean
  size?: ControlSize
  /**
   * Classes for the positioning wrapper rather than the control. Layout classes
   * (`ml-auto`, `flex-1`, `shrink-0`, `mt-1`) belong here — the wrapper, not the
   * `<select>`, is what the parent flex or grid actually lays out.
   */
  wrapperClassName?: string
}

/**
 * Native `<select>` styled to match Input.
 *
 * The UA arrow is suppressed and redrawn, because Chrome renders it in the OS
 * light colour regardless of the surrounding theme. The option popup is drawn by
 * the OS and can't be reached from here at all — `color-scheme` in globals.css
 * is what makes it follow the theme.
 */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { className, invalid, size = 'md', wrapperClassName, children, ...props },
  ref,
) {
  return (
    <div className={cn('relative', wrapperClassName)}>
      <select
        ref={ref}
        aria-invalid={invalid || undefined}
        className={cn(
          controlClasses(invalid, size),
          'cursor-pointer appearance-none',
          size === 'sm' ? 'pr-7' : 'pr-9',
          className,
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronDown
        className={cn(
          'pointer-events-none absolute top-1/2 -translate-y-1/2 text-muted-foreground',
          size === 'sm' ? 'right-2 h-3 w-3' : 'right-3 h-4 w-4',
        )}
        aria-hidden
      />
    </div>
  )
})

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn('block text-sm font-medium text-foreground', className)}
      {...props}
    />
  )
}

export function FieldError({ className, children, ...props }: React.HTMLAttributes<HTMLParagraphElement>) {
  if (!children) return null
  return (
    <p role="alert" className={cn('text-xs text-destructive-strong', className)} {...props}>
      {children}
    </p>
  )
}

interface FieldProps {
  label: string
  htmlFor?: string
  /** Rendered under the control when there is no error. */
  hint?: string
  error?: string
  required?: boolean
  className?: string
  children: React.ReactNode
}

/** Label + control + hint/error, with the spacing every form should use. */
export function Field({ label, htmlFor, hint, error, required, className, children }: FieldProps) {
  return (
    <div className={cn('space-y-1.5', className)}>
      <Label htmlFor={htmlFor}>
        {label}
        {required && (
          <span className="ml-0.5 text-destructive-strong" aria-hidden>
            *
          </span>
        )}
      </Label>
      {children}
      {error ? <FieldError>{error}</FieldError> : hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  )
}
