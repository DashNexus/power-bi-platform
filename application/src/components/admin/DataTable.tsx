'use client'

/**
 * Generic paginated data table.
 *
 * Accepts a column definition array and a data array. Pagination state is
 * controlled externally — the parent page owns the current page and calls
 * onPageChange to trigger a new server fetch.
 */
import { useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface ColumnDef {
  key: string
  header: string
  render?: (value: unknown, row: Record<string, unknown>) => React.ReactNode
}

interface DataTableProps {
  columns: ColumnDef[]
  data: Record<string, unknown>[]
  total: number
  page: number
  pageSize: number
  onPageChange?: (page: number) => void
}

export function DataTable({
  columns,
  data,
  total,
  page,
  pageSize,
  onPageChange,
}: DataTableProps) {
  const [currentPage, setCurrentPage] = useState(page)

  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const start = (currentPage - 1) * pageSize + 1
  const end = Math.min(currentPage * pageSize, total)

  function goToPage(p: number) {
    if (p < 1 || p > totalPages) return
    setCurrentPage(p)
    onPageChange?.(p)
  }

  function renderCell(col: ColumnDef, row: Record<string, unknown>) {
    const value = row[col.key]
    if (col.render) return col.render(value, row)
    if (value === null || value === undefined) return <span className="text-muted-foreground">—</span>
    return String(value)
  }

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-border text-sm">
          <thead className="bg-muted">
            <tr>
              {columns.map(col => (
                <th
                  key={col.key}
                  scope="col"
                  className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground"
                >
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {data.length === 0 ? (
              <tr>
                <td
                  colSpan={columns.length}
                  className="px-4 py-10 text-center text-sm text-muted-foreground"
                >
                  No records found.
                </td>
              </tr>
            ) : (
              data.map((row, i) => (
                <tr
                  key={i}
                  className="hover:bg-accent transition-colors duration-100"
                >
                  {columns.map(col => (
                    <td key={col.key} className="px-4 py-3 text-foreground whitespace-nowrap">
                      {renderCell(col, row)}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination footer */}
      {total > 0 && (
        <div className="flex items-center justify-between border-t border-border px-4 py-3">
          <p className="text-xs text-muted-foreground">
            Showing {start}–{end} of {total.toLocaleString()}
          </p>

          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => goToPage(currentPage - 1)}
              disabled={currentPage === 1}
              aria-label="Previous page"
              className={cn(
                'rounded-lg p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground',
                'disabled:opacity-40 disabled:cursor-not-allowed transition-colors',
              )}
            >
              <ChevronLeft className="h-4 w-4" />
            </button>

            <span className="px-2 text-xs text-muted-foreground">
              Page {currentPage} of {totalPages}
            </span>

            <button
              type="button"
              onClick={() => goToPage(currentPage + 1)}
              disabled={currentPage === totalPages}
              aria-label="Next page"
              className={cn(
                'rounded-lg p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground',
                'disabled:opacity-40 disabled:cursor-not-allowed transition-colors',
              )}
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
