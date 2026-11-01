import { Link } from 'react-router-dom'
import { EmptyState } from '../components/ui/StateViews'

export default function NotFound() {
  return (
    <EmptyState
      title="This page does not exist"
      description="The address may be mistyped, or the page may have moved."
      action={
        <Link to="/" className="text-sm font-medium text-brand-700 hover:underline">
          Go to the dashboard
        </Link>
      }
    />
  )
}
