import { redirect } from 'next/navigation'

// Root path has no content — redirect to the platform home.
// The (platform)/layout.tsx will redirect unauthenticated users to /login.
export default function RootPage() {
  redirect('/home')
}
