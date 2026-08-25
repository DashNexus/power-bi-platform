'use client'

/**
 * Collapsible configuration card for a data pipeline connector.
 *
 * Supports two connector types with distinct field sets:
 *   prefect — API URL, optional username, optional password (Basic Auth)
 *   azure_data_factory — tenant ID, subscription ID, resource group, factory name,
 *                        service principal client ID, service principal client secret
 *
 * Credentials are persisted to auth_provider_configs via the admin API.
 * Client secrets are Fernet-encrypted server-side; the API never returns the
 * plaintext value, only a has_client_secret boolean.
 */
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import * as Switch from '@radix-ui/react-switch'
import * as Label from '@radix-ui/react-label'
import { ChevronDown, ChevronUp, Trash2, Wifi } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'

export type PipelineConnectorType = 'prefect' | 'azure_data_factory'

export interface PipelineConnectorConfig {
  id?: number
  enabled: boolean
  client_id: string
  has_client_secret: boolean
  config: Record<string, string> | null
}

export interface PipelineConnectorCardProps {
  connector: PipelineConnectorType
  displayName: string
  config: PipelineConnectorConfig | null
  onSave: (data: Record<string, unknown>) => Promise<void>
  onDelete: () => Promise<void>
  onToggle: (enabled: boolean) => Promise<void>
  onTestConnection?: () => Promise<{ ok: boolean; error?: string; pipeline_count?: number }>
}

const CONNECTOR_ICONS: Record<PipelineConnectorType, string> = {
  prefect: '⚡',
  azure_data_factory: '🔵',
}

// ─── Prefect form ─────────────────────────────────────────────────────────────

const prefectSchema = z.object({
  url: z.string().url('Must be a valid URL — e.g. http://localhost:4200/api'),
  username: z.string().optional(),
  password: z.string().optional(),
})

type PrefectValues = z.infer<typeof prefectSchema>

interface PrefectFormProps {
  config: PipelineConnectorConfig | null
  onSave: (data: Record<string, unknown>) => Promise<void>
  onDelete: () => Promise<void>
  isDeleting: boolean
}

function PrefectForm({ config, onSave, onDelete, isDeleting }: PrefectFormProps) {
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<PrefectValues>({
    resolver: zodResolver(prefectSchema),
    defaultValues: {
      url: config?.config?.['url'] ?? '',
      username: config?.client_id ?? '',
      password: '',
    },
  })

  async function onSubmit(values: PrefectValues) {
    const payload: Record<string, unknown> = {
      config: { url: values.url },
    }
    if (values.username) payload['client_id'] = values.username
    if (values.password) payload['client_secret'] = values.password
    await onSave(payload)
  }

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
      <div className="space-y-1">
        <label htmlFor="prefect-url" className="block text-sm font-medium text-foreground">
          Prefect API URL
        </label>
        <input
          id="prefect-url"
          type="url"
          autoComplete="off"
          placeholder="http://localhost:4200/api"
          {...register('url')}
          className={cn(
            'block w-full rounded-lg border px-3 py-2 text-sm shadow-sm',
            'focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent',
            errors.url ? 'border-destructive/40 bg-destructive-subtle' : 'border-border-strong bg-card',
          )}
        />
        {errors.url && <p className="text-xs text-destructive-strong">{errors.url.message}</p>}
      </div>

      <div className="space-y-1">
        <label htmlFor="prefect-username" className="block text-sm font-medium text-foreground">
          Username <span className="font-normal text-muted-foreground">(optional)</span>
        </label>
        <input
          id="prefect-username"
          type="text"
          autoComplete="off"
          {...register('username')}
          className="block w-full rounded-lg border border-border-strong bg-card px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
        />
      </div>

      <div className="space-y-1">
        <label htmlFor="prefect-password" className="block text-sm font-medium text-foreground">
          Password <span className="font-normal text-muted-foreground">(optional)</span>
        </label>
        <input
          id="prefect-password"
          type="password"
          autoComplete="new-password"
          placeholder={config?.has_client_secret ? '••••••••' : ''}
          {...register('password')}
          className="block w-full rounded-lg border border-border-strong bg-card px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
        />
        {config?.has_client_secret && (
          <p className="text-xs text-muted-foreground">Leave blank to keep the existing password.</p>
        )}
      </div>

      <FormActions
        isSubmitting={isSubmitting}
        hasConfig={!!config?.id}
        isDeleting={isDeleting}
        onDelete={onDelete}
      />
    </form>
  )
}

// ─── ADF form ─────────────────────────────────────────────────────────────────

const adfSchema = z.object({
  tenant_id: z.string().min(1, 'Tenant ID is required'),
  subscription_id: z.string().min(1, 'Subscription ID is required'),
  resource_group: z.string().min(1, 'Resource group is required'),
  factory_name: z.string().min(1, 'Factory name is required'),
  client_id: z.string().min(1, 'Client ID is required'),
  client_secret: z.string().optional(),
})

type AdfValues = z.infer<typeof adfSchema>

interface AdfFormProps {
  config: PipelineConnectorConfig | null
  onSave: (data: Record<string, unknown>) => Promise<void>
  onDelete: () => Promise<void>
  isDeleting: boolean
  onTestConnection?: () => Promise<{ ok: boolean; error?: string; pipeline_count?: number }>
}

function AdfForm({ config, onSave, onDelete, isDeleting, onTestConnection }: AdfFormProps) {
  const [testing, setTesting] = useState(false)
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<AdfValues>({
    resolver: zodResolver(adfSchema),
    defaultValues: {
      tenant_id: config?.config?.['tenant_id'] ?? '',
      subscription_id: config?.config?.['subscription_id'] ?? '',
      resource_group: config?.config?.['resource_group'] ?? '',
      factory_name: config?.config?.['factory_name'] ?? '',
      client_id: config?.client_id ?? '',
      client_secret: '',
    },
  })

  async function onSubmit(values: AdfValues) {
    const payload: Record<string, unknown> = {
      client_id: values.client_id,
      config: {
        tenant_id: values.tenant_id,
        subscription_id: values.subscription_id,
        resource_group: values.resource_group,
        factory_name: values.factory_name,
      },
    }
    if (values.client_secret) payload['client_secret'] = values.client_secret
    await onSave(payload)
  }

  async function handleTest() {
    if (!onTestConnection) return
    setTesting(true)
    try {
      const result = await onTestConnection()
      if (result.ok) {
        toast.success(
          `Connected — ${result.pipeline_count ?? 0} pipeline${result.pipeline_count === 1 ? '' : 's'} found.`,
        )
      } else {
        toast.error(result.error ?? 'Connection test failed.', { duration: 10000 })
      }
    } catch {
      toast.error('Connection test failed.')
    } finally {
      setTesting(false)
    }
  }

  const textField = (
    id: string,
    label: string,
    field: keyof AdfValues,
    placeholder: string,
  ) => (
    <div key={field} className="space-y-1">
      <label htmlFor={id} className="block text-sm font-medium text-foreground">
        {label}
      </label>
      <input
        id={id}
        type="text"
        autoComplete="off"
        placeholder={placeholder}
        {...register(field)}
        className={cn(
          'block w-full rounded-lg border px-3 py-2 text-sm shadow-sm',
          'focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent',
          errors[field] ? 'border-destructive/40 bg-destructive-subtle' : 'border-border-strong bg-card',
        )}
      />
      {errors[field] && <p className="text-xs text-destructive-strong">{errors[field]?.message}</p>}
    </div>
  )

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
      {textField('adf-tenant-id', 'Tenant ID', 'tenant_id', 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx')}
      {textField('adf-subscription-id', 'Subscription ID', 'subscription_id', 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx')}
      {textField('adf-resource-group', 'Resource group', 'resource_group', 'my-resource-group')}
      {textField('adf-factory-name', 'Factory name', 'factory_name', 'my-data-factory')}
      {textField('adf-client-id', 'Service principal client ID', 'client_id', 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx')}

      <div className="space-y-1">
        <label htmlFor="adf-client-secret" className="block text-sm font-medium text-foreground">
          Service principal client secret
        </label>
        <input
          id="adf-client-secret"
          type="password"
          autoComplete="new-password"
          placeholder={config?.has_client_secret ? '••••••••' : ''}
          {...register('client_secret')}
          className="block w-full rounded-lg border border-border-strong bg-card px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent"
        />
        {config?.has_client_secret && (
          <p className="text-xs text-muted-foreground">Leave blank to keep the existing secret.</p>
        )}
      </div>

      {onTestConnection && config?.id && (
        <div>
          <button
            type="button"
            onClick={handleTest}
            disabled={testing}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-lg border border-border-strong bg-card px-4 py-2 text-sm font-medium text-foreground',
              'hover:bg-accent transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              testing && 'opacity-60 cursor-not-allowed',
            )}
          >
            <Wifi className="h-4 w-4" />
            {testing ? 'Testing…' : 'Test Connection'}
          </button>
        </div>
      )}

      <FormActions
        isSubmitting={isSubmitting}
        hasConfig={!!config?.id}
        isDeleting={isDeleting}
        onDelete={onDelete}
      />
    </form>
  )
}

// ─── Shared action buttons ─────────────────────────────────────────────────────

interface FormActionsProps {
  isSubmitting: boolean
  hasConfig: boolean
  isDeleting: boolean
  onDelete: () => Promise<void>
}

function FormActions({ isSubmitting, hasConfig, isDeleting, onDelete }: FormActionsProps) {
  return (
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

      {hasConfig && (
        <button
          type="button"
          onClick={onDelete}
          disabled={isDeleting}
          className={cn(
            'inline-flex items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium text-destructive-strong',
            'hover:bg-destructive-subtle transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500',
            isDeleting && 'opacity-60 cursor-not-allowed',
          )}
        >
          <Trash2 className="h-4 w-4" />
          {isDeleting ? 'Removing…' : 'Remove Configuration'}
        </button>
      )}
    </div>
  )
}

// ─── Card shell ────────────────────────────────────────────────────────────────

/**
 * Collapsible card for configuring a pipeline connector.
 *
 * The header is always visible and shows the connector status (enabled/disabled /
 * not configured) with an immediate toggle. Expanding the card reveals the
 * type-specific credential form.
 */
export function PipelineConnectorCard({
  connector,
  displayName,
  config,
  onSave,
  onDelete,
  onToggle,
  onTestConnection,
}: PipelineConnectorCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [toggling, setToggling] = useState(false)
  const [deleting, setDeleting] = useState(false)

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

  const isEnabled = config?.enabled ?? false

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
      {/* Card header — always visible */}
      <div className="flex items-center justify-between px-5 py-4">
        <div className="flex items-center gap-3">
          <span className="text-xl" aria-hidden="true">
            {CONNECTOR_ICONS[connector]}
          </span>
          <div>
            <p className="text-sm font-medium text-foreground">{displayName}</p>
            <p className="text-xs text-muted-foreground">
              {config ? (isEnabled ? 'Enabled' : 'Disabled') : 'Not configured'}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <Label.Root
              htmlFor={`toggle-${connector}`}
              className="cursor-pointer select-none text-xs text-muted-foreground"
            >
              {isEnabled ? 'On' : 'Off'}
            </Label.Root>
            <Switch.Root
              id={`toggle-${connector}`}
              checked={isEnabled}
              disabled={toggling || !config}
              onCheckedChange={handleToggle}
              className={cn(
                'relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent',
                'transition-colors duration-200 ease-in-out focus:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                isEnabled ? 'bg-primary' : 'bg-secondary',
                (toggling || !config) && 'cursor-not-allowed opacity-50',
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

          <button
            type="button"
            onClick={() => setExpanded(v => !v)}
            aria-expanded={expanded}
            aria-controls={`connector-body-${connector}`}
            className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </button>
        </div>
      </div>

      {/* Collapsible form body */}
      {expanded && (
        <div
          id={`connector-body-${connector}`}
          className="border-t border-border px-5 py-5"
        >
          {connector === 'prefect' ? (
            <PrefectForm
              config={config}
              onSave={onSave}
              onDelete={handleDelete}
              isDeleting={deleting}
            />
          ) : (
            <AdfForm
              config={config}
              onSave={onSave}
              onDelete={handleDelete}
              isDeleting={deleting}
              onTestConnection={onTestConnection}
            />
          )}
        </div>
      )}
    </div>
  )
}
