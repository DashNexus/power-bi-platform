import { PageHeader } from '@/components/ui'
import { ProfileForm } from '@/components/settings/ProfileForm'

export const metadata = {
  title: 'Profile',
}

export default function ProfilePage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Profile"
        description="Your avatar, details, and password."
      />
      <ProfileForm />
    </div>
  )
}
