'use client'

/**
 * Minimal, dependency-free Markdown renderer for AI output.
 *
 * Handles the constructs assistants commonly produce — headings, bold/italic,
 * inline code, fenced code blocks, and bullet/numbered lists — as real React
 * elements (never dangerouslySetInnerHTML, so it is XSS-safe).
 *
 * Shared by the data-chat bubbles and the assist panel. The assist panel used to
 * render assistant replies in a `whitespace-pre-wrap` div, so a model that
 * answered in Markdown — which they all do — showed raw `**bold**` and `1.` to
 * the user. Only *assistant* text goes through here; a user's own message is
 * shown verbatim, because they typed it and did not ask for it to be reformatted.
 */
import React from 'react'

/** Parse inline markdown (code, bold, italic, links) into React nodes. */
function parseInline(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = []
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*\n]+\*|\[[^\]]+\]\([^)\s]+\))/g
  let last = 0
  let key = 0
  let match: RegExpExecArray | null
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index))
    const tok = match[0]
    if (tok.startsWith('`')) {
      nodes.push(
        <code key={key++} className="rounded bg-black/10 px-1 py-0.5 font-mono text-[0.85em]">
          {tok.slice(1, -1)}
        </code>,
      )
    } else if (tok.startsWith('**')) {
      nodes.push(<strong key={key++}>{tok.slice(2, -2)}</strong>)
    } else if (tok.startsWith('*')) {
      nodes.push(<em key={key++}>{tok.slice(1, -1)}</em>)
    } else {
      const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(tok)
      if (link) {
        nodes.push(
          <a
            key={key++}
            href={link[2]}
            target="_blank"
            rel="noopener noreferrer"
            className="text-primary underline"
          >
            {link[1]}
          </a>,
        )
      } else {
        nodes.push(tok)
      }
    }
    last = match.index + tok.length
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

const UL = /^\s*[-*]\s+/
const OL = /^\s*\d+\.\s+/
const HEADING = /^(#{1,6})\s+(.*)$/

export function MarkdownContent({ content }: { content: string }) {
  const lines = content.split('\n')
  const blocks: React.ReactNode[] = []
  let i = 0
  let key = 0

  while (i < lines.length) {
    const line = lines[i]

    // Fenced code block
    if (line.trim().startsWith('```')) {
      const code: string[] = []
      i++
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        code.push(lines[i])
        i++
      }
      i++ // consume closing fence
      blocks.push(
        <pre
          key={key++}
          className="my-2 overflow-x-auto rounded-lg bg-card p-3 text-xs leading-relaxed text-foreground"
        >
          <code className="font-mono">{code.join('\n')}</code>
        </pre>,
      )
      continue
    }

    // Heading
    const heading = HEADING.exec(line)
    if (heading) {
      const level = heading[1].length
      const cls = level <= 1 ? 'text-base font-semibold' : level === 2 ? 'text-sm font-semibold' : 'text-sm font-medium'
      blocks.push(
        <p key={key++} className={`${cls} mt-2`}>
          {parseInline(heading[2])}
        </p>,
      )
      i++
      continue
    }

    // Unordered list
    if (UL.test(line)) {
      const items: string[] = []
      while (i < lines.length && UL.test(lines[i])) {
        items.push(lines[i].replace(UL, ''))
        i++
      }
      blocks.push(
        <ul key={key++} className="my-1 list-disc space-y-0.5 pl-5">
          {items.map((it, ii) => (
            <li key={ii}>{parseInline(it)}</li>
          ))}
        </ul>,
      )
      continue
    }

    // Ordered list
    if (OL.test(line)) {
      const items: string[] = []
      while (i < lines.length && OL.test(lines[i])) {
        items.push(lines[i].replace(OL, ''))
        i++
      }
      blocks.push(
        <ol key={key++} className="my-1 list-decimal space-y-0.5 pl-5">
          {items.map((it, ii) => (
            <li key={ii}>{parseInline(it)}</li>
          ))}
        </ol>,
      )
      continue
    }

    // Blank line
    if (line.trim() === '') {
      i++
      continue
    }

    // Paragraph — gather consecutive plain lines
    const para: string[] = []
    while (
      i < lines.length &&
      lines[i].trim() !== '' &&
      !lines[i].trim().startsWith('```') &&
      !HEADING.test(lines[i]) &&
      !UL.test(lines[i]) &&
      !OL.test(lines[i])
    ) {
      para.push(lines[i])
      i++
    }
    blocks.push(
      <p key={key++} className="whitespace-pre-wrap leading-relaxed">
        {parseInline(para.join('\n'))}
      </p>,
    )
  }

  return <div className="space-y-1.5 text-sm">{blocks}</div>
}
