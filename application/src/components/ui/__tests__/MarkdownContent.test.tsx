// @vitest-environment jsdom
/**
 * Tests for the shared Markdown renderer.
 *
 * It exists because assistants answer in Markdown whether or not you asked them
 * to. The assist panel rendered replies in a `whitespace-pre-wrap` div, so users
 * saw raw `**bold**` and `1.` markers.
 *
 * It must also never use dangerouslySetInnerHTML: this content comes from a model,
 * which can be steered by whatever text a user pasted in.
 */
import '@testing-library/jest-dom/vitest'
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MarkdownContent } from '@/components/ui'

describe('MarkdownContent', () => {
  it('renders bold as an element, not literal asterisks', () => {
    render(<MarkdownContent content="A **Happy Birthday** slide" />)

    expect(screen.getByText('Happy Birthday').tagName).toBe('STRONG')
    expect(screen.queryByText(/\*\*/)).not.toBeInTheDocument()
  })

  it('renders italics', () => {
    render(<MarkdownContent content="an *emphasised* word" />)

    expect(screen.getByText('emphasised').tagName).toBe('EM')
  })

  it('renders inline code', () => {
    render(<MarkdownContent content="use `add_timeline_slide` for that" />)

    expect(screen.getByText('add_timeline_slide').tagName).toBe('CODE')
  })

  it('renders a bullet list as a real list', () => {
    const { container } = render(<MarkdownContent content={'- one\n- two'} />)

    expect(container.querySelectorAll('ul li')).toHaveLength(2)
  })

  it('renders a numbered list as an ordered list', () => {
    const { container } = render(<MarkdownContent content={'1. first\n2. second'} />)

    expect(container.querySelectorAll('ol li')).toHaveLength(2)
  })

  it('renders headings without leaving hash marks', () => {
    render(<MarkdownContent content="## Slide Created" />)

    expect(screen.getByText('Slide Created')).toBeInTheDocument()
    expect(screen.queryByText(/^#/)).not.toBeInTheDocument()
  })

  it('renders a fenced code block preserving its newlines', () => {
    const { container } = render(
      <MarkdownContent content={'```\nline one\nline two\n```'} />,
    )

    const pre = container.querySelector('pre code')
    expect(pre?.textContent).toBe('line one\nline two')
  })

  it('renders links as anchors that open safely', () => {
    render(<MarkdownContent content="see [the docs](https://example.test/x)" />)

    const link = screen.getByRole('link', { name: 'the docs' })
    expect(link).toHaveAttribute('href', 'https://example.test/x')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
  })

  it('does not execute embedded HTML', () => {
    const { container } = render(
      <MarkdownContent content={'<img src=x onerror="alert(1)">'} />,
    )

    // Rendered as text, never parsed into a live element.
    expect(container.querySelector('img')).toBeNull()
    expect(container.textContent).toContain('<img')
  })

  it('handles empty content without crashing', () => {
    const { container } = render(<MarkdownContent content="" />)

    expect(container).toBeInTheDocument()
  })

  it('keeps a plain paragraph plain', () => {
    render(<MarkdownContent content="Just an ordinary sentence." />)

    expect(screen.getByText('Just an ordinary sentence.')).toBeInTheDocument()
  })
})
