/**
 * Shared types for the change-history UI.
 *
 * Mirrors the `ChangeRecord` schema in `api/app/routers/changes.py`. The
 * resource types are the ones registered in `services/mutation_registry.py`;
 * anything else is 422'd by the API rather than rendered here.
 */

/** One change-ledger entry as returned by GET /changes*. */
export interface ChangeRecord {
  id: number
  correlation_id: string
  resource_type: string
  resource_id: number | null
  resource_name: string | null
  action: 'create' | 'update' | 'delete'
  source: 'ai' | 'user' | 'system'
  actor_name: string | null
  created_at: string
  reverted_at: string | null
  diff: Array<{ field: string; old: unknown; new: unknown }>
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  /** Rows sharing this correlation id; > 1 must revert as a group. */
  correlation_size: number
}

/** Human labels for the resource types the ledger tracks. */
export const CHANGE_RESOURCE_LABELS: Record<string, string> = {
  dashboard: 'dashboard',
  dashboard_filter: 'dashboard filter',
  dashboard_permission: 'dashboard share',
  custom_page: 'page',
  custom_page_permission: 'page share',
  data_dict_entry: 'data dictionary entry',
}
