import { motion } from 'framer-motion'
import { Quote, ShieldCheck } from 'lucide-react'
import type { ReactNode } from 'react'
import { Logo } from '@/components/Logo'
import { ThemeToggle } from '@/components/ThemeToggle'

/** Split-screen shell for login and registration. */
export default function AuthLayout({ title, subtitle, children }: { title: string; subtitle: ReactNode; children: ReactNode }) {
  return (
    <div className="grid min-h-svh lg:grid-cols-2">
      <div className="flex flex-col px-4 py-6 sm:px-10">
        <div className="flex items-center justify-between">
          <Logo />
          <ThemeToggle />
        </div>
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center py-10"
        >
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          <p className="mt-2 mb-8 text-sm text-muted-foreground">{subtitle}</p>
          {children}
        </motion.div>
        <p className="text-center text-xs text-muted-foreground">
          Educational tool only. Not a substitute for professional medical advice.
        </p>
      </div>

      <div className="relative hidden overflow-hidden bg-navy lg:block">
        <div className="bg-grid-light absolute inset-0 opacity-30" />
        <div className="absolute -top-32 -right-32 size-96 rounded-full bg-violet/35 blur-3xl" />
        <div className="absolute -bottom-40 -left-24 size-96 rounded-full bg-teal/40 blur-3xl" />
        <div className="relative flex h-full flex-col justify-end p-12 text-white">
          <p className="mb-auto text-sm font-medium tracking-wide text-mint">Your Health Documents. Understood Intelligently.</p>
          <Quote className="mb-6 size-8 opacity-60" />
          <p className="max-w-md text-2xl leading-snug font-medium text-balance">
            Every explanation is grounded in retrieved medical evidence, and every claim links to its source.
          </p>
          <div className="mt-10 flex items-center gap-2 text-sm text-white/75">
            <ShieldCheck className="size-4" /> Your documents are private and isolated to your account.
          </div>
        </div>
      </div>
    </div>
  )
}
