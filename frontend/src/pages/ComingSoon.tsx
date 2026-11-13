import { Construction } from 'lucide-react'
import { Link } from 'react-router-dom'
import { buttonVariants } from '@/components/ui/button'

/** Placeholder for app sections that are built in later roadmap phases. */
export default function ComingSoon({ title, phase, description }: { title: string; phase: string; description: string }) {
  return (
    <div className="mx-auto flex max-w-lg flex-col items-center py-20 text-center">
      <div className="mb-5 grid size-14 place-items-center rounded-2xl bg-primary/12 text-primary">
        <Construction className="size-6" />
      </div>
      <p className="text-sm font-medium text-primary">{phase}</p>
      <h2 className="mt-2 text-2xl font-semibold tracking-tight">{title}</h2>
      <p className="mt-3 text-muted-foreground">{description}</p>
      <Link to="/app" className={buttonVariants({ variant: 'outline', className: 'mt-8' })}>
        Back to dashboard
      </Link>
    </div>
  )
}
