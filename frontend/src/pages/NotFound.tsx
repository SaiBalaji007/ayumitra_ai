import { Link } from 'react-router-dom'
import { buttonVariants } from '@/components/ui/button'

export default function NotFound() {
  return (
    <div className="grid min-h-[60svh] place-items-center px-4 text-center">
      <div>
        <p className="text-sm font-medium text-primary">404</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">Page not found</h1>
        <p className="mt-3 text-muted-foreground">The page you're looking for doesn't exist or has moved.</p>
        <Link to="/" className={buttonVariants({ className: 'mt-8' })}>
          Go home
        </Link>
      </div>
    </div>
  )
}
