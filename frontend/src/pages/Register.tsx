import { AlertCircle, Check, Loader2 } from 'lucide-react'
import { useState, type ChangeEvent, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuth } from '@/contexts/AuthContext'
import AuthLayout from '@/layouts/AuthLayout'
import { apiErrorMessage } from '@/services/api'
import { cn } from '@/lib/utils'

export default function Register() {
  const { register } = useAuth()
  const navigate = useNavigate()
  const [form, setForm] = useState({ first_name: '', last_name: '', email: '', password: '' })
  const [agreed, setAgreed] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  const set = (key: keyof typeof form) => (e: ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [key]: e.target.value }))

  const longEnough = form.password.length >= 8
  const notNumeric = form.password.length > 0 && !/^\d+$/.test(form.password)
  const canSubmit = form.first_name.trim() && form.email && longEnough && notNumeric && agreed && !pending

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setPending(true)
    try {
      await register({
        ...form,
        first_name: form.first_name.trim(),
        last_name: form.last_name.trim(),
        email: form.email.trim().toLowerCase(),
      })
      navigate('/app', { replace: true })
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setPending(false)
    }
  }

  return (
    <AuthLayout
      title="Create your account"
      subtitle={
        <>
          Already have one?{' '}
          <Link to="/login" className="font-medium text-primary hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-5" noValidate>
        {error && (
          <Alert variant="destructive">
            <AlertCircle />
            {error}
          </Alert>
        )}
        <div className="grid grid-cols-2 gap-3">
          <div className="space-y-2">
            <Label htmlFor="first_name">First name</Label>
            <Input id="first_name" autoComplete="given-name" required value={form.first_name} onChange={set('first_name')} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="last_name">Last name</Label>
            <Input id="last_name" autoComplete="family-name" value={form.last_name} onChange={set('last_name')} />
          </div>
        </div>
        <div className="space-y-2">
          <Label htmlFor="email">Email</Label>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            required
            value={form.email}
            onChange={set('email')}
            placeholder="you@example.com"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            autoComplete="new-password"
            required
            value={form.password}
            onChange={set('password')}
            aria-describedby="password-rules"
          />
          <ul id="password-rules" className="space-y-1 text-xs">
            {[
              [longEnough, 'At least 8 characters'],
              [notNumeric, 'Not only numbers'],
            ].map(([ok, label]) => (
              <li key={String(label)} className={cn('flex items-center gap-1.5', ok ? 'text-success' : 'text-muted-foreground')}>
                <Check className={cn('size-3', !ok && 'opacity-30')} />
                {label}
              </li>
            ))}
          </ul>
        </div>
        <label className="flex cursor-pointer items-start gap-3 text-sm text-muted-foreground">
          <input
            type="checkbox"
            checked={agreed}
            onChange={(e) => setAgreed(e.target.checked)}
            className="mt-0.5 size-4 accent-primary"
          />
          <span>
            I understand AyuMitra AI provides educational information only and does not replace advice from a doctor or
            pharmacist.
          </span>
        </label>
        <Button type="submit" className="w-full" disabled={!canSubmit}>
          {pending && <Loader2 className="animate-spin" />}
          Create account
        </Button>
      </form>
    </AuthLayout>
  )
}
