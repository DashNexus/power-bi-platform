// @vitest-environment jsdom
/**
 * Tests for the form control primitives.
 *
 * The Select cases guard the dark-mode fix: hand-rolled selects across the app
 * omitted a surface class and rendered UA-default white on dark cards, so every
 * control must carry the themed surface, and layout classes must land on the
 * positioning wrapper rather than the control.
 */
import '@testing-library/jest-dom/vitest'
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Input, Select, Textarea, controlClasses } from '@/components/ui/Input'

describe('controlClasses', () => {
  it('names a themed surface and foreground', () => {
    const classes = controlClasses()

    expect(classes).toContain('bg-card')
    expect(classes).toContain('text-foreground')
  })

  it('defaults to the medium density', () => {
    expect(controlClasses()).toContain('px-3 py-2 text-sm')
  })

  it('tightens padding and type at the small density', () => {
    expect(controlClasses(false, 'sm')).toContain('px-2 py-1 text-xs')
  })

  it('swaps in the error ring when invalid', () => {
    expect(controlClasses(true)).toContain('border-destructive')
  })
})

describe('Select', () => {
  it('renders its options', () => {
    render(
      <Select aria-label="Region">
        <option value="emea">EMEA</option>
      </Select>,
    )

    expect(screen.getByRole('option', { name: 'EMEA' })).toBeInTheDocument()
  })

  it('carries the themed surface so it is not white on a dark card', () => {
    render(<Select aria-label="Region" />)

    expect(screen.getByLabelText('Region').className).toContain('bg-card')
  })

  it('suppresses the UA arrow, which ignores the page theme', () => {
    render(<Select aria-label="Region" />)

    expect(screen.getByLabelText('Region').className).toContain('appearance-none')
  })

  it('reserves room for the redrawn arrow', () => {
    render(<Select aria-label="Region" />)

    expect(screen.getByLabelText('Region').className).toContain('pr-9')
  })

  it('narrows the arrow gutter at the small density', () => {
    render(<Select aria-label="Region" size="sm" />)

    expect(screen.getByLabelText('Region').className).toContain('pr-7')
  })

  it('puts wrapperClassName on the wrapper, not the control', () => {
    render(<Select aria-label="Region" wrapperClassName="ml-auto" />)
    const select = screen.getByLabelText('Region')

    expect(select.className).not.toContain('ml-auto')
    expect(select.parentElement?.className).toContain('ml-auto')
  })

  it('marks an invalid control for assistive tech', () => {
    render(<Select aria-label="Region" invalid />)

    expect(screen.getByLabelText('Region')).toHaveAttribute('aria-invalid', 'true')
  })

  it('leaves aria-invalid off when valid', () => {
    render(<Select aria-label="Region" />)

    expect(screen.getByLabelText('Region')).not.toHaveAttribute('aria-invalid')
  })
})

describe('Input and Textarea', () => {
  it('gives Input the themed surface', () => {
    render(<Input aria-label="Name" />)

    expect(screen.getByLabelText('Name').className).toContain('bg-card')
  })

  it('gives Textarea the themed surface', () => {
    render(<Textarea aria-label="Notes" />)

    expect(screen.getByLabelText('Notes').className).toContain('bg-card')
  })
})
