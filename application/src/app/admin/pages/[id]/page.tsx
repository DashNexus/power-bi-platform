'use client'

/**
 * Edit an existing custom HTML page.
 *
 * Loads the current page content and its full version history. The version
 * history sidebar lets admins restore any previous snapshot. Changes are
 * saved via PUT /admin/pages/{id}; restores via POST /admin/pages/{id}/versions/{vid}/restore.
 */
import type { KeyboardEvent } from 'react';
import { useState, useCallback, useEffect } from 'react'
import { use } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import dynamic from 'next/dynamic'
import { useSession } from 'next-auth/react'
import { toast } from 'sonner'
import { ArrowLeft, Users, X } from 'lucide-react'
import { createClientFetch } from '@/lib/api'
import { ShareResourceDialog } from '@/components/admin/ShareResourceDialog'

const Editor = dynamic(() => import('@monaco-editor/react'), { ssr: false })

interface PageData {
  id: number
  title: string
  slug: string
  content: string
  is_published: boolean
  is_home_page: boolean
  tags: string[]
  created_at: string
  updated_at: string
}

interface PageVersion {
  id: number
  page_id: number
  content: string
  created_at: string
}


interface EditPagePageProps {
  params: Promise<{ id: string }>
}

// ---------- Main page ----------

export default function EditPagePage({ params }: EditPagePageProps) {
  const { id } = use(params)
  const router = useRouter()
  const { data: session } = useSession()

  const [page, setPage] = useState<PageData | null>(null)
  const [versions, setVersions] = useState<PageVersion[]>([])
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [isPublished, setIsPublished] = useState(true)
  const [tags, setTags] = useState<string[]>([])
  const [tagInput, setTagInput] = useState('')
  const [showPreview, setShowPreview] = useState(false)
  const [showPerms, setShowPerms] = useState(false)
  const [previewVersionContent, setPreviewVersionContent] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [restoring, setRestoring] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)

  const apiFetch = createClientFetch(session?.user?.access_token)

  useEffect(() => {
    async function load() {
      if (!session?.user?.access_token) return
      try {
        const [pageData, versionData] = await Promise.all([
          apiFetch<PageData>(`/admin/pages/${id}`),
          apiFetch<PageVersion[]>(`/admin/pages/${id}/versions`),
        ])
        setPage(pageData)
        setTitle(pageData.title)
        setContent(pageData.content)
        setIsPublished(pageData.is_published)
        setTags(pageData.tags ?? [])
        setVersions(versionData)
      } catch {
        toast.error('Failed to load page.')
      } finally {
        setLoading(false)
      }
    }
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, session?.user?.access_token])

  const handleEditorChange = useCallback((value: string | undefined) => {
    setContent(value ?? '')
  }, [])

  async function handleSave() {
    if (!title.trim()) {
      toast.error('Title is required.')
      return
    }

    setSaving(true)
    try {
      const updated = await apiFetch<PageData>(`/admin/pages/${id}`, {
        method: 'PUT',
        body: JSON.stringify({
          title: title.trim(),
          content,
          is_published: isPublished,
          tags,
        }),
      })
      setPage(updated)
      const versionData = await apiFetch<PageVersion[]>(`/admin/pages/${id}/versions`)
      setVersions(versionData)
      toast.success('Page updated successfully.')
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to save page.'
      toast.error(message)
    } finally {
      setSaving(false)
    }
  }

  async function handleRestore(versionId: number) {
    setRestoring(versionId)
    try {
      const updated = await apiFetch<PageData>(
        `/admin/pages/${id}/versions/${versionId}/restore`,
        { method: 'POST' },
      )
      setPage(updated)
      setContent(updated.content)
      setPreviewVersionContent(null)
      const versionData = await apiFetch<PageVersion[]>(`/admin/pages/${id}/versions`)
      setVersions(versionData)
      toast.success('Version restored.')
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to restore version.'
      toast.error(message)
    } finally {
      setRestoring(null)
    }
  }

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
        Loading page...
      </div>
    )
  }

  if (!page) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-2">
        <p className="text-sm text-muted-foreground">Page not found.</p>
        <button
          type="button"
          onClick={() => router.push('/admin/pages')}
          className="text-sm text-primary hover:underline"
        >
          Back to pages
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-6">
      {showPerms && (
        <ShareResourceDialog
          resourceLabel="Page"
          resourceName={page.title}
          permissionsPath={`/admin/pages/${page.id}/permissions`}
          apiFetch={apiFetch}
          onClose={() => setShowPerms(false)}
        />
      )}

      <div className="flex items-center justify-between">
        <div>
          <Link
            href="/admin/pages"
            className="mb-2 inline-flex items-center gap-1 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to pages
          </Link>
          <h1 className="text-2xl font-semibold text-foreground">Edit Page</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{page.slug}</code>
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => setShowPerms(true)}
            className="inline-flex items-center gap-2 rounded-lg border border-border-strong bg-card px-4 py-2 text-sm font-medium text-foreground hover:bg-accent transition-colors"
          >
            <Users className="h-4 w-4" />
            Manage Access
          </button>
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
            onChange={e => setTitle(e.target.value)}
            className="mt-1 block w-full rounded-lg border border-border-strong px-3 py-2 text-sm shadow-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-ring"
          />
        </div>

        {/* Published toggle */}
        <div className="flex items-end gap-4">
          <label className="flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              checked={isPublished}
              onChange={e => setIsPublished(e.target.checked)}
              className="h-4 w-4 rounded border-border-strong text-primary focus:ring-ring"
            />
            <span className="text-sm font-medium text-foreground">Published</span>
          </label>
        </div>
      </div>

      {/* Tags */}
      <div>
        <label className="block text-sm font-medium text-foreground mb-1">Tags</label>
        <div className="flex flex-wrap gap-1.5 rounded-lg border border-border-strong px-3 py-2 min-h-[42px] focus-within:ring-1 focus-within:ring-ring bg-card">
          {tags.map(tag => (
            <span
              key={tag}
              className="inline-flex items-center gap-1 rounded-full bg-primary-subtle px-2 py-0.5 text-xs font-medium text-info-strong"
            >
              {tag}
              <button
                type="button"
                onClick={() => setTags(prev => prev.filter(t => t !== tag))}
                className="rounded-full hover:bg-primary-subtle"
              >
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

      <div className="flex gap-6">
        {/* Editor / preview area */}
        <div className={`flex flex-col ${versions.length > 0 ? 'flex-1' : 'w-full'}`}>
          <div className={`grid gap-4 ${showPreview ? 'lg:grid-cols-2' : 'grid-cols-1'}`}>
            <div>
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

            {(showPreview || previewVersionContent !== null) && (
              <div>
                <div className="mb-1 flex items-center justify-between">
                  <label className="block text-sm font-medium text-foreground">
                    {previewVersionContent !== null ? 'Version Preview' : 'Preview'}
                  </label>
                  {previewVersionContent !== null && (
                    <button
                      type="button"
                      onClick={() => setPreviewVersionContent(null)}
                      className="text-xs text-muted-foreground hover:text-foreground"
                    >
                      ✕ Close version
                    </button>
                  )}
                </div>
                <iframe
                  title="Page preview"
                  sandbox="allow-scripts"
                  src={`data:text/html;charset=utf-8,${encodeURIComponent(previewVersionContent ?? content)}`}
                  className="h-[500px] w-full rounded-lg border border-border-strong bg-card"
                />
              </div>
            )}
          </div>
        </div>

        {/* Version history sidebar */}
        {versions.length > 0 && (
          <div className="w-64 shrink-0">
            <h2 className="mb-3 text-sm font-semibold text-foreground">Version History</h2>
            <div className="flex flex-col gap-2 overflow-y-auto" style={{ maxHeight: 520 }}>
              {versions.map((v, index) => (
                <div
                  key={v.id}
                  className="rounded-lg border border-border bg-card p-3 shadow-sm"
                >
                  <p className="text-xs font-medium text-foreground">
                    {index === 0 ? 'Latest snapshot' : `Version ${versions.length - index}`}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {new Date(v.created_at).toLocaleString('en-US', {
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </p>
                  <div className="mt-2 flex items-center gap-3">
                    <button
                      type="button"
                      onClick={() => {
                        setPreviewVersionContent(v.content)
                        if (!showPreview) setShowPreview(true)
                      }}
                      className="text-xs font-medium text-muted-foreground hover:text-foreground"
                    >
                      Preview
                    </button>
                    <button
                      type="button"
                      onClick={() => handleRestore(v.id)}
                      disabled={restoring === v.id}
                      className="text-xs font-medium text-primary hover:text-primary disabled:opacity-50"
                    >
                      {restoring === v.id ? 'Restoring...' : 'Restore'}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
