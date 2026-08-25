'use client'

/**
 * New custom HTML page form.
 *
 * Provides a Monaco HTML editor, live preview via a sandboxed iframe, and
 * a slug field that auto-generates from the title but remains editable.
 * Submits to POST /admin/pages on save.
 */
import type { KeyboardEvent } from 'react';
import { useState, useCallback } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import dynamic from 'next/dynamic'
import { useSession } from 'next-auth/react'
import { toast } from 'sonner'
import { ArrowLeft, X } from 'lucide-react'
import { createClientFetch } from '@/lib/api'
import { Select } from '@/components/ui'

// Monaco is a large bundle — load it only on the client
const Editor = dynamic(() => import('@monaco-editor/react'), { ssr: false })

const ROLE_OPTIONS = ['viewer', 'analyst', 'admin', 'superadmin'] as const
type Role = (typeof ROLE_OPTIONS)[number]

function slugify(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')
    .trim()
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
}

export default function NewPagePage() {
  const router = useRouter()
  const { data: session } = useSession()

  const [title, setTitle] = useState('')
  const [slug, setSlug] = useState('')
  const [slugManuallyEdited, setSlugManuallyEdited] = useState(false)
  const [content, setContent] = useState('<h1>Hello world</h1>\n<p>Edit this content.</p>')
  const [requiredRole, setRequiredRole] = useState<Role>('viewer')
  const [isPublished, setIsPublished] = useState(true)
  const [tags, setTags] = useState<string[]>([])
  const [tagInput, setTagInput] = useState('')
  const [showPreview, setShowPreview] = useState(false)
  const [saving, setSaving] = useState(false)

  const apiFetch = createClientFetch(session?.user?.access_token)

  function handleTitleChange(value: string) {
    setTitle(value)
    if (!slugManuallyEdited) {
      setSlug(slugify(value))
    }
  }

  function handleSlugChange(value: string) {
    setSlug(value)
    setSlugManuallyEdited(true)
  }

  const handleEditorChange = useCallback((value: string | undefined) => {
    setContent(value ?? '')
  }, [])

  async function handleSave() {
    if (!title.trim()) {
      toast.error('Title is required.')
      return
    }
    if (!slug.trim()) {
      toast.error('Slug is required.')
      return
    }

    setSaving(true)
    try {
      await apiFetch('/admin/pages', {
        method: 'POST',
        body: JSON.stringify({
          title: title.trim(),
          slug: slug.trim(),
          content,
          required_role: requiredRole,
          is_published: isPublished,
          tags,
        }),
      })
      toast.success('Page created successfully.')
      router.push('/admin/pages')
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to create page.'
      toast.error(message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <Link
            href="/admin/pages"
            className="mb-2 inline-flex items-center gap-1 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to pages
          </Link>
          <h1 className="text-2xl font-semibold text-foreground">New Page</h1>
          <p className="mt-1 text-sm text-muted-foreground">Create a custom HTML page for your users.</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setShowPreview(v => !v)}
            className="rounded-lg border border-border-strong bg-card px-4 py-2 text-sm font-medium text-foreground hover:bg-accent transition-colors"
          >
            {showPreview ? 'Hide Preview' : 'Show Preview'}
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50 transition-colors"
          >
            {saving ? 'Saving...' : 'Save Page'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Title */}
        <div className="lg:col-span-2">
          <label className="block text-sm font-medium text-foreground">Title</label>
          <input
            type="text"
            value={title}
            onChange={e => handleTitleChange(e.target.value)}
            placeholder="e.g. Getting Started Guide"
            className="mt-1 block w-full rounded-lg border border-border-strong px-3 py-2 text-sm shadow-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-ring"
          />
        </div>

        {/* Slug */}
        <div>
          <label className="block text-sm font-medium text-foreground">Slug</label>
          <input
            type="text"
            value={slug}
            onChange={e => handleSlugChange(e.target.value)}
            placeholder="getting-started-guide"
            className="mt-1 block w-full rounded-lg border border-border-strong px-3 py-2 text-sm shadow-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-ring"
          />
          <p className="mt-1 text-xs text-muted-foreground">URL: /pages/{slug || '<slug>'}</p>
        </div>

        {/* Required Role */}
        <div>
          <label className="block text-sm font-medium text-foreground">Required Role</label>
          <Select
            value={requiredRole}
            onChange={e => setRequiredRole(e.target.value as Role)} wrapperClassName="mt-1"
          >
            {ROLE_OPTIONS.map(role => (
              <option key={role} value={role}>
                {role.charAt(0).toUpperCase() + role.slice(1)}
              </option>
            ))}
          </Select>
        </div>

        {/* Published toggle */}
        <div className="flex items-end gap-3">
          <label className="flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              checked={isPublished}
              onChange={e => setIsPublished(e.target.checked)}
              className="h-4 w-4 rounded border-border-strong text-primary focus:ring-ring"
            />
            <span className="text-sm font-medium text-foreground">Publish immediately</span>
          </label>
        </div>

        {/* Tags */}
        <div className="lg:col-span-3">
          <label className="block text-sm font-medium text-foreground mb-1">Tags</label>
          <div className="flex flex-wrap gap-1.5 rounded-lg border border-border-strong px-3 py-2 min-h-[42px] focus-within:ring-1 focus-within:ring-ring bg-card">
            {tags.map(tag => (
              <span key={tag} className="inline-flex items-center gap-1 rounded-full bg-primary-subtle px-2 py-0.5 text-xs font-medium text-info-strong">
                {tag}
                <button type="button" onClick={() => setTags(prev => prev.filter(t => t !== tag))} className="rounded-full hover:bg-primary-subtle">
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
            <input
              type="text"
              value={tagInput}
              onChange={e => setTagInput(e.target.value)}
              onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => {
                if ((e.key === 'Enter' || e.key === ',') && tagInput.trim()) {
                  e.preventDefault()
                  const newTag = tagInput.trim().toLowerCase()
                  if (!tags.includes(newTag)) setTags(prev => [...prev, newTag])
                  setTagInput('')
                } else if (e.key === 'Backspace' && !tagInput && tags.length > 0) {
                  setTags(prev => prev.slice(0, -1))
                }
              }}
              placeholder={tags.length === 0 ? 'Add tags (press Enter or comma)' : ''}
              className="flex-1 min-w-[160px] text-sm outline-none bg-transparent"
            />
          </div>
        </div>
      </div>

      {/* Editor and preview */}
      <div className={`grid gap-4 ${showPreview ? 'lg:grid-cols-2' : 'grid-cols-1'}`}>
        <div className="flex flex-col">
          <label className="mb-1 block text-sm font-medium text-foreground">
            Content (HTML)
          </label>
          <div className="overflow-hidden rounded-lg border border-border-strong" style={{ height: 500 }}>
            <Editor
              height="500px"
              defaultLanguage="html"
              value={content}
              onChange={handleEditorChange}
              options={{
                minimap: { enabled: false },
                fontSize: 13,
                wordWrap: 'on',
                scrollBeyondLastLine: false,
              }}
            />
          </div>
        </div>

        {showPreview && (
          <div className="flex flex-col">
            <label className="mb-1 block text-sm font-medium text-foreground">Preview</label>
            <iframe
              title="Page preview"
              sandbox="allow-scripts"
              src={`data:text/html;charset=utf-8,${encodeURIComponent(content)}`}
              className="h-[500px] w-full rounded-lg border border-border-strong bg-card"
            />
          </div>
        )}
      </div>
    </div>
  )
}
