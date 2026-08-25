// @vitest-environment jsdom
/**
 * Tests for DataTable.
 *
 * Verifies rendering of columns, row data, empty state, and pagination
 * controls including the page-change callback.
 */
import '@testing-library/jest-dom/vitest'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DataTable } from '@/components/admin/DataTable'
import type { ColumnDef } from '@/components/admin/DataTable'

const COLUMNS: ColumnDef[] = [
  { key: 'name', header: 'Name' },
  { key: 'email', header: 'Email' },
  { key: 'role', header: 'Role' },
]

const ROWS = [
  { name: 'Alice', email: 'alice@example.com', role: 'admin' },
  { name: 'Bob', email: 'bob@example.com', role: 'analyst' },
  { name: 'Carol', email: 'carol@example.com', role: 'viewer' },
]

describe('DataTable', () => {
  it('renders column headers', () => {
    render(
      <DataTable columns={COLUMNS} data={ROWS} total={3} page={1} pageSize={10} />,
    )

    expect(screen.getByText('Name')).toBeInTheDocument()
    expect(screen.getByText('Email')).toBeInTheDocument()
    expect(screen.getByText('Role')).toBeInTheDocument()
  })

  it('renders all row data', () => {
    render(
      <DataTable columns={COLUMNS} data={ROWS} total={3} page={1} pageSize={10} />,
    )

    expect(screen.getByText('Alice')).toBeInTheDocument()
    expect(screen.getByText('bob@example.com')).toBeInTheDocument()
    expect(screen.getByText('viewer')).toBeInTheDocument()
  })

  it('shows "No records found." when data is empty', () => {
    render(
      <DataTable columns={COLUMNS} data={[]} total={0} page={1} pageSize={10} />,
    )

    expect(screen.getByText('No records found.')).toBeInTheDocument()
  })

  it('renders a dash for null/undefined cell values', () => {
    const rowsWithNull = [{ name: 'Dave', email: null, role: undefined }]
    render(
      <DataTable
        columns={COLUMNS}
        data={rowsWithNull as unknown as Record<string, unknown>[]}
        total={1}
        page={1}
        pageSize={10}
      />,
    )

    const dashes = screen.getAllByText('—')
    expect(dashes.length).toBeGreaterThanOrEqual(2)
  })

  it('shows pagination footer with correct record range', () => {
    render(
      <DataTable columns={COLUMNS} data={ROWS} total={25} page={1} pageSize={10} />,
    )

    expect(screen.getByText('Showing 1–10 of 25')).toBeInTheDocument()
  })

  it('hides pagination footer when total is 0', () => {
    render(
      <DataTable columns={COLUMNS} data={[]} total={0} page={1} pageSize={10} />,
    )

    expect(screen.queryByText(/Showing/)).not.toBeInTheDocument()
  })

  it('calls onPageChange with next page when Next button is clicked', async () => {
    const user = userEvent.setup()
    const onPageChange = vi.fn()

    render(
      <DataTable
        columns={COLUMNS}
        data={ROWS}
        total={25}
        page={1}
        pageSize={10}
        onPageChange={onPageChange}
      />,
    )

    await user.click(screen.getByLabelText('Next page'))
    expect(onPageChange).toHaveBeenCalledWith(2)
  })

  it('calls onPageChange with previous page when Prev button is clicked', async () => {
    const user = userEvent.setup()
    const onPageChange = vi.fn()

    render(
      <DataTable
        columns={COLUMNS}
        data={ROWS}
        total={25}
        page={2}
        pageSize={10}
        onPageChange={onPageChange}
      />,
    )

    await user.click(screen.getByLabelText('Previous page'))
    expect(onPageChange).toHaveBeenCalledWith(1)
  })

  it('disables Previous button on the first page', () => {
    render(
      <DataTable columns={COLUMNS} data={ROWS} total={25} page={1} pageSize={10} />,
    )

    expect(screen.getByLabelText('Previous page')).toBeDisabled()
  })

  it('disables Next button on the last page', () => {
    render(
      <DataTable columns={COLUMNS} data={ROWS} total={3} page={1} pageSize={10} />,
    )

    expect(screen.getByLabelText('Next page')).toBeDisabled()
  })

  it('uses a custom render function for a column', () => {
    const columns: ColumnDef[] = [
      {
        key: 'role',
        header: 'Role',
        render: (value) => <span data-testid="badge">{String(value).toUpperCase()}</span>,
      },
    ]
    render(
      <DataTable columns={columns} data={[{ role: 'admin' }]} total={1} page={1} pageSize={10} />,
    )

    expect(screen.getByTestId('badge')).toHaveTextContent('ADMIN')
  })
})
