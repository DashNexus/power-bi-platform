/**
 * Barrel for the shared UI primitives.
 *
 * Import from `@/components/ui` rather than from the individual files so a
 * primitive can be split or renamed without touching call sites.
 */
export {
  Avatar,
  AvatarGroup,
  avatarSrc,
  userInitials,
  type AvatarProps,
  type AvatarGroupProps,
  type AvatarSize,
} from './Avatar'
export { Button, buttonVariants, type ButtonProps } from './Button'
export {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
  type CardProps,
} from './Card'
export {
  Field,
  FieldError,
  Input,
  Label,
  Select,
  Textarea,
  controlClasses,
  type ControlSize,
  type InputProps,
  type SelectProps,
  type TextareaProps,
} from './Input'
export { Badge, StatusBadge, statusTone, type BadgeProps, type StatusBadgeProps } from './Badge'
export { MarkdownContent } from './MarkdownContent'
export { PageHeader, SectionHeader } from './PageHeader'
export { EmptyState, ErrorState } from './EmptyState'
export {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableEmpty,
  TableHead,
  TableHeaderCell,
  TableRow,
} from './Table'
export { Alert, LoadingRows, Skeleton, Spinner, type AlertProps } from './Feedback'
export { Tabs, type TabItem } from './Tabs'
export { Brand, APP_NAME } from './Brand'
export { DetailList, DetailRow, Modal } from './Modal'
export { Toggle, ToggleRow } from './Toggle'
