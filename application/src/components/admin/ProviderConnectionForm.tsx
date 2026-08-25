'use client'

/**
 * Provider-driven connection dialog, shared by the admin connection pages.
 *
 * Every "connect to an external system" page in admin (pipeline orchestrators,
 * BI platforms, billing providers) renders the same dialog: a name, a grouped
 * provider picker, the selected provider's metadata-declared fields, and an
 * active toggle. Only the option grouping and an optional callout differ, so
 * those are the props — the layout, secret handling, and save flow live here.
 *
 * Secrets are write-only: an existing secret is never sent to the browser, so a
 * blank secret field on edit means "leave the stored value alone".
 */
import { useState } from 'react'
import { Button, Field, Input, Modal, Select } from '@/components/ui'

/** One metadata-declared input on a provider's connection form. */
export interface ProviderFieldMeta {
  key: string
  label: string
  type: string
  required: boolean
  secret: boolean
  placeholder: string
  help: string
}

/** The subset of provider metadata this form needs. */
export interface ProviderMetaBase {
  key: string
  label: string
  implemented: boolean
  fields: ProviderFieldMeta[]
}

export interface ProviderOption {
  key: string
  label: string
  disabled?: boolean
}

/** One `<optgroup>` in the provider picker. */
export interface ProviderGroup {
  label: string
  options: ProviderOption[]
}

/** What the page persists. `secret` is undefined when it should stay unchanged. */
export interface ConnectionPayload {
  name: string
  provider: string
  config: Record<string, string>
  secret?: string
  is_active: boolean
}

/** The existing connection being edited, if any. */
export interface EditingConnection {
  name: string
  provider: string
  config: Record<string, string>
  is_active: boolean
  has_secret: boolean
}

interface ProviderConnectionFormProps<P extends ProviderMetaBase> {
  title: string
  namePlaceholder: string
  providers: P[]
  /** Grouped options for the provider `<Select>`. */
  providerGroups: ProviderGroup[]
  /** Provider selected on open when creating. Falls back to the first enabled option. */
  defaultProviderKey?: string
  editing: EditingConnection | null
  /** Callout rendered above the provider's fields, e.g. "no credentials needed". */
  notice?: (provider: P) => React.ReactNode
  onSubmit: (payload: ConnectionPayload) => Promise<void>
  onClose: () => void
}

function firstEnabled(groups: ProviderGroup[]): string {
  for (const group of groups) {
    const option = group.options.find(o => !o.disabled)
    if (option) return option.key
  }
  return ''
}

export function ProviderConnectionForm<P extends ProviderMetaBase>({
  title,
  namePlaceholder,
  providers,
  providerGroups,
  defaultProviderKey,
  editing,
  notice,
  onSubmit,
  onClose,
}: ProviderConnectionFormProps<P>) {
  const [name, setName] = useState(editing?.name ?? '')
  const [providerKey, setProviderKey] = useState(
    editing?.provider ?? defaultProviderKey ?? firstEnabled(providerGroups),
  )
  const [values, setValues] = useState<Record<string, string>>(() => ({ ...(editing?.config ?? {}) }))
  const [isActive, setIsActive] = useState(editing?.is_active ?? true)
  const [saving, setSaving] = useState(false)

  const provider = providers.find(p => p.key === providerKey)

  async function handleSave() {
    if (!name.trim() || !provider) return
    const config: Record<string, string> = {}
    let secret: string | undefined
    for (const field of provider.fields) {
      const value = values[field.key] ?? ''
      if (field.secret) {
        // Blank means "keep the stored secret" — never overwrite with empty.
        if (value) secret = value
      } else {
        config[field.key] = value
      }
    }
    setSaving(true)
    try {
      await onSubmit({ name: name.trim(), provider: providerKey, config, secret, is_active: isActive })
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={title}
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button
            onClick={() => void handleSave()}
            disabled={!name.trim() || !provider}
            isLoading={saving}
          >
            {editing ? 'Save' : 'Create'}
          </Button>
        </>
      }
    >
      <div className="space-y-3">
        <Field label="Connection name" htmlFor="connection-name" required>
          <Input
            id="connection-name"
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder={namePlaceholder}
          />
        </Field>

        <Field
          label="Provider"
          htmlFor="connection-provider"
          hint={editing ? 'Provider cannot be changed after creation.' : undefined}
        >
          <Select
            id="connection-provider"
            value={providerKey}
            onChange={e => {
              setProviderKey(e.target.value)
              setValues({})
            }}
            disabled={Boolean(editing)}
          >
            {providerGroups
              .filter(group => group.options.length > 0)
              .map(group => (
                <optgroup key={group.label} label={group.label}>
                  {group.options.map(option => (
                    <option key={option.key} value={option.key} disabled={option.disabled}>
                      {option.label}
                    </option>
                  ))}
                </optgroup>
              ))}
          </Select>
        </Field>

        {provider && notice?.(provider)}

        {provider?.fields.map(field => (
          <Field
            key={field.key}
            label={field.label}
            htmlFor={`connection-${field.key}`}
            required={field.required}
            hint={field.help || undefined}
          >
            <Input
              id={`connection-${field.key}`}
              type={field.secret ? 'password' : field.type === 'number' ? 'number' : 'text'}
              value={values[field.key] ?? ''}
              onChange={e => setValues(prev => ({ ...prev, [field.key]: e.target.value }))}
              placeholder={
                field.secret && editing?.has_secret ? '•••••••• (unchanged)' : field.placeholder
              }
              autoComplete={field.secret ? 'new-password' : 'off'}
            />
          </Field>
        ))}

        <label className="flex cursor-pointer items-center gap-2 pt-1">
          <input
            type="checkbox"
            checked={isActive}
            onChange={e => setIsActive(e.target.checked)}
            className="h-4 w-4 rounded border-input text-primary focus:ring-ring"
          />
          <span className="text-sm text-foreground">Active</span>
        </label>
      </div>
    </Modal>
  )
}
