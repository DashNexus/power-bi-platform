'use client'

/**
 * Collapsible configuration card for the Microsoft Entra ID provider.
 *
 * Renders an expand/collapse toggle so admins can configure one provider at a
 * time without every form being visible simultaneously. The client secret field
 * is always masked with a placeholder when a saved value exists, matching the
 * API's redacted response — the user must type a new value to replace it.
 */
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import * as Switch from '@radix-ui/react-switch'
import * as Label from '@radix-ui/react-label'
import { ChevronDown, ChevronUp, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'

export interface AuthProviderConfig {
  id?: number
  enabled: boolean
  client_id: string
  client_secret: string
  tenant_id?: string
}

export interface AuthProviderCardProps {
  provider: 'microsoft'
  displayName: string
  config: AuthProviderConfig | null
  onSave: (data: Record<string, string>) => Promise<void>
  onDelete: () => Promise<void>
  onToggle: (enabled: boolean) => Promise<void>
}

const baseSchema = z.object({
  client_id: z.string().min(1, 'Client ID is required'),
  client_secret: z.string().optional(),
})

const microsoftSchema = baseSchema.extend({
  tenant_id: z.string().min(1, 'Tenant ID is required for Microsoft Entra ID'),
})

type FormValues = z.infer<typeof microsoftSchema>

/** Map provider key to its icon emoji (placeholder until SVG assets are added). */
const PROVIDER_ICONS: Record<AuthProviderCardProps['provider'], string> = {
  microsoft: '🔷',
}

/**
 * Collapsible card that lets an admin configure one OAuth / OIDC provider.
 *
 * The enabled/disabled state is controlled via an immediate PATCH rather than
 * requiring a full form save, so admins can quickly toggle a provider without
 * re-entering credentials.
 */
export function AuthProviderCard({
  provider,
  displayName,
  config,
  onSave,
  onDelete,
  onToggle,
}: AuthProviderCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [toggling, setToggling] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(microsoftSchema),
    defaultValues: {
      client_id: config?.client_id ?? '',
      client_secret: '',
      tenant_id: config?.tenant_id ?? '',
    },
  })

  async function handleToggle(checked: boolean) {
    setToggling(true)
    try {
      await onToggle(checked)
      toast.success(`${displayName} ${checked ? 'enabled' : 'disabled'}.`)
    } catch {
      toast.error(`Failed to ${checked ? 'enable' : 'disable'} ${displayName}.`)
    } finally {
      setToggling(false)
    }
  }

  async function handleDelete() {
    if (!config?.id) return
    setDeleting(true)
    try {
      await onDelete()
      toast.success(`${displayName} configuration removed.`)
    } catch {
      toast.error(`Failed to remove ${displayName} configuration.`)
    } finally {
      setDeleting(false)
    }
  }

  async function onSubmit(values: FormValues) {
    const payload: Record<string, string> = {
      client_id: values.client_id,
    }
    // Only send client_secret when the user has typed a new value.
    if (values.client_secret) {
      payload['client_secret'] = values.client_secret
    }
    if (values.tenant_id) {
      payload['tenant_id'] = values.tenant_id
    }
    try {
      await onSave(payload)
      toast.success(`${displayName} configuration saved.`)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      toast.error(`Failed to save ${displayName}: ${msg}`)
    }
  }

  const isEnabled = config?.enabled ?? false

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
      {/* Card header — always visible */}
      <div className="flex items-center justify-between px-5 py-4">
        <div className="flex items-center gap-3">
          <span className="text-xl" aria-hidden="true">
            {PROVIDER_ICONS[provider]}
          </span>
          <div>
            <p className="text-sm font-medium text-foreground">{displayName}</p>
            <p className="text-xs text-muted-foreground">
              {config ? (isEnabled ? 'Enabled' : 'Disabled') : 'Not configured'}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {/* Enabled / disabled toggle */}
          <div className="flex items-center gap-2">
            <Label.Root
              htmlFor={`toggle-${provider}`}
              className="text-xs text-muted-foreground select-none cursor-pointer"
            >
              {isEnabled ? 'On' : 'Off'}
            </Label.Root>
            <Switch.Root
              id={`toggle-${provider}`}
              checked={isEnabled}
              disabled={toggling || !config}
              onCheckedChange={handleToggle}
              className={cn(
                'relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent',
                'transition-colors duration-200 ease-in-out focus:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                isEnabled ? 'bg-primary' : 'bg-secondary',
                (toggling || !config) && 'opacity-50 cursor-not-allowed',
              )}
            >
              <Switch.Thumb
                className={cn(
                  'pointer-events-none inline-block h-4 w-4 transform rounded-full bg-card shadow ring-0',
                  'transition duration-200 ease-in-out',
                  isEnabled ? 'translate-x-4' : 'translate-x-0',
                )}
              />
            </Switch.Root>
          </div>

          {/* Expand / collapse */}
          <button
            type="button"
            onClick={() => setExpanded(v => !v)}
            aria-expanded={expanded}
            aria-controls={`card-body-${provider}`}
            className="rounded-lg p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
          >
            {expanded ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
          </button>
        </div>
      </div>

      {/* Collapsible form body */}
      {expanded && (
        <div
          id={`card-body-${provider}`}
          className="border-t border-border px-5 py-5"
        >
          <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
            {/* Client ID */}
            <div className="space-y-1">
              <label
                htmlFor={`${provider}-client-id`}
                className="block text-sm font-medium text-foreground"
              >
                Client ID
              </label>
              <input
                id={`${provider}-client-id`}
                type="text"
                autoComplete="off"
                {...register('client_id')}
                className={cn(
                  'block w-full rounded-lg border px-3 py-2 text-sm shadow-sm',
                  'focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent',
                  errors.client_id
                    ? 'border-destructive/40 bg-destructive-subtle'
                    : 'border-border-strong bg-card',
                )}
              />
              {errors.client_id && (
                <p className="text-xs text-destructive-strong">{errors.client_id.message}</p>
              )}
            </div>

            {/* Client Secret */}
            <div className="space-y-1">
              <label
                htmlFor={`${provider}-client-secret`}
                className="block text-sm font-medium text-foreground"
              >
                Client Secret
              </label>
              <input
                id={`${provider}-client-secret`}
                type="password"
                autoComplete="new-password"
                placeholder={config?.client_secret ? '••••••••' : ''}
                {...register('client_secret')}
                className={cn(
                  'block w-full rounded-lg border px-3 py-2 text-sm shadow-sm',
                  'focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent',
                  errors.client_secret
                    ? 'border-destructive/40 bg-destructive-subtle'
                    : 'border-border-strong bg-card',
                )}
              />
              {config?.client_secret && (
                <p className="text-xs text-muted-foreground">
                  Leave blank to keep the existing secret.
                </p>
              )}
              {errors.client_secret && (
                <p className="text-xs text-destructive-strong">{errors.client_secret.message}</p>
              )}
            </div>

            {/* Tenant ID — scopes sign-in to one Entra directory */}
            <div className="space-y-1">
              <label
                htmlFor={`${provider}-tenant-id`}
                className="block text-sm font-medium text-foreground"
              >
                Tenant ID
              </label>
              <input
                id={`${provider}-tenant-id`}
                type="text"
                autoComplete="off"
                {...register('tenant_id')}
                className={cn(
                  'block w-full rounded-lg border px-3 py-2 text-sm shadow-sm',
                  'focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent',
                  errors.tenant_id
                    ? 'border-destructive/40 bg-destructive-subtle'
                    : 'border-border-strong bg-card',
                )}
              />
              {errors.tenant_id && (
                <p className="text-xs text-destructive-strong">{errors.tenant_id.message}</p>
              )}
            </div>

            {/* Action buttons */}
            <div className="flex items-center justify-between pt-2">
              <button
                type="submit"
                disabled={isSubmitting}
                className={cn(
                  'inline-flex items-center rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground',
                  'hover:bg-primary-hover transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  isSubmitting && 'opacity-60 cursor-not-allowed',
                )}
              >
                {isSubmitting ? 'Saving…' : 'Save Configuration'}
              </button>

              {config?.id && (
                <button
                  type="button"
                  onClick={handleDelete}
                  disabled={deleting}
                  className={cn(
                    'inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium text-destructive-strong',
                    'hover:bg-destructive-subtle transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500',
                    deleting && 'opacity-60 cursor-not-allowed',
                  )}
                >
                  <Trash2 className="h-4 w-4" />
                  {deleting ? 'Removing…' : 'Remove Configuration'}
                </button>
              )}
            </div>
          </form>
        </div>
      )}
    </div>
  )
}
