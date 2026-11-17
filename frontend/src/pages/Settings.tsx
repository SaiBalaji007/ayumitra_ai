import { useMutation, useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react'
import { useState, type FormEvent, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuth } from '@/contexts/AuthContext'
import { apiErrorMessage, authApi, profileApi, type PatientProfile } from '@/services/api'

const SEX = [
  ['undisclosed', 'Prefer not to say'],
  ['female', 'Female'],
  ['male', 'Male'],
  ['intersex', 'Intersex'],
] as const
const TODAY = new Date().toISOString().slice(0, 10)
const BLOOD = ['unknown', 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-']
const selectClass =
  'flex h-10 w-full rounded-lg border border-input bg-background px-3 text-sm shadow-xs focus-visible:border-ring focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/25'
const textareaClass = selectClass.replace('h-10', 'min-h-20 py-2')

function Status({ pending, success, error, ok }: { pending: boolean; success: boolean; error: unknown; ok: string }) {
  if (pending) return <Loader2 className="size-4 animate-spin text-muted-foreground" aria-label="Saving" />
  if (error) return <Alert variant="destructive"><AlertTriangle />{apiErrorMessage(error)}</Alert>
  if (success) return <span className="flex items-center gap-1 text-sm text-success"><CheckCircle2 className="size-4" />{ok}</span>
  return null
}

function Field({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
    </div>
  )
}

function AccountCard() {
  const { user, refreshUser } = useAuth()
  const [first, setFirst] = useState(user?.first_name ?? '')
  const [last, setLast] = useState(user?.last_name ?? '')
  const save = useMutation({
    mutationFn: () => authApi.updateMe({ first_name: first.trim(), last_name: last.trim() }),
    onSuccess: () => refreshUser(),
  })
  return (
    <Card>
      <CardHeader>
        <CardTitle>Account</CardTitle>
        <CardDescription>Signed in as {user?.email}. Your email is your login and can't be changed here.</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate() }}>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="first" label="First name"><Input id="first" value={first} required maxLength={150} onChange={(e) => setFirst(e.target.value)} /></Field>
            <Field id="last" label="Last name"><Input id="last" value={last} maxLength={150} onChange={(e) => setLast(e.target.value)} /></Field>
          </div>
          <div className="flex items-center gap-3">
            <Button type="submit" disabled={save.isPending}>Save</Button>
            <Status pending={save.isPending} success={save.isSuccess} error={save.error} ok="Saved" />
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

function ProfileForm({ initial }: { initial: PatientProfile }) {
  const [p, setP] = useState(initial)
  const set = <K extends keyof PatientProfile>(k: K, v: PatientProfile[K]) => setP({ ...p, [k]: v })
  const save = useMutation({
    mutationFn: () =>
      profileApi.update({ ...p, date_of_birth: p.date_of_birth || null, height_cm: p.height_cm || null, weight_kg: p.weight_kg || null }),
  })
  return (
    <form className="space-y-4" onSubmit={(e: FormEvent) => { e.preventDefault(); save.mutate() }}>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field id="dob" label="Date of birth">
          <Input id="dob" type="date" value={p.date_of_birth ?? ''} max={TODAY} onChange={(e) => set('date_of_birth', e.target.value)} />
        </Field>
        <Field id="sex" label="Sex">
          <select id="sex" className={selectClass} value={p.sex} onChange={(e) => set('sex', e.target.value as PatientProfile['sex'])}>
            {SEX.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </Field>
        <Field id="blood" label="Blood group">
          <select id="blood" className={selectClass} value={p.blood_group} onChange={(e) => set('blood_group', e.target.value)}>
            {BLOOD.map((b) => <option key={b} value={b}>{b === 'unknown' ? 'Unknown' : b}</option>)}
          </select>
        </Field>
        <Field id="height" label="Height (cm)">
          <Input id="height" type="number" min={30} max={260} step="0.1" value={p.height_cm ?? ''} onChange={(e) => set('height_cm', e.target.value)} />
        </Field>
        <Field id="weight" label="Weight (kg)">
          <Input id="weight" type="number" min={1} max={400} step="0.1" value={p.weight_kg ?? ''} onChange={(e) => set('weight_kg', e.target.value)} />
        </Field>
        <Field id="diet" label="Dietary preference">
          <Input id="diet" maxLength={40} placeholder="e.g. vegetarian" value={p.dietary_preference} onChange={(e) => set('dietary_preference', e.target.value)} />
        </Field>
      </div>
      <div className="grid gap-4 sm:grid-cols-3">
        <Field id="allergies" label="Allergies">
          <textarea id="allergies" className={textareaClass} value={p.allergies} onChange={(e) => set('allergies', e.target.value)} />
        </Field>
        <Field id="conditions" label="Long-term conditions">
          <textarea id="conditions" className={textareaClass} value={p.chronic_conditions} onChange={(e) => set('chronic_conditions', e.target.value)} />
        </Field>
        <Field id="meds" label="Current medicines (your notes)">
          <textarea id="meds" className={textareaClass} value={p.current_medications_note} onChange={(e) => set('current_medications_note', e.target.value)} />
        </Field>
      </div>
      <div className="flex items-center gap-3">
        <Button type="submit" disabled={save.isPending}>Save profile</Button>
        <Status pending={save.isPending} success={save.isSuccess} error={save.error} ok="Profile saved" />
      </div>
    </form>
  )
}

function ProfileCard() {
  const q = useQuery({ queryKey: ['profile'], queryFn: profileApi.get })
  return (
    <Card>
      <CardHeader>
        <CardTitle>Health profile</CardTitle>
        <CardDescription>Self-reported and optional. Visible only to you.</CardDescription>
      </CardHeader>
      <CardContent>
        {q.isPending ? <Loader2 className="size-5 animate-spin text-primary" aria-label="Loading" />
          : q.isError ? <Alert variant="destructive"><AlertTriangle />{apiErrorMessage(q.error)}</Alert>
          : <ProfileForm initial={q.data} />}
      </CardContent>
    </Card>
  )
}

function PasswordCard() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const change = useMutation({
    mutationFn: () => authApi.changePassword(current, next),
    onSuccess: () => { setCurrent(''); setNext(''); setConfirm('') },
  })
  const mismatch = confirm.length > 0 && confirm !== next
  return (
    <Card>
      <CardHeader>
        <CardTitle>Password</CardTitle>
        <CardDescription>At least 8 characters; avoid common passwords or ones similar to your name or email.</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={(e: FormEvent) => { e.preventDefault(); if (!mismatch) change.mutate() }}>
          <div className="grid gap-4 sm:grid-cols-3">
            <Field id="cur" label="Current password"><Input id="cur" type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} /></Field>
            <Field id="new" label="New password"><Input id="new" type="password" autoComplete="new-password" required minLength={8} value={next} onChange={(e) => setNext(e.target.value)} /></Field>
            <Field id="conf" label="Confirm new password">
              <Input id="conf" type="password" autoComplete="new-password" required aria-invalid={mismatch} value={confirm} onChange={(e) => setConfirm(e.target.value)} />
            </Field>
          </div>
          {mismatch && <p className="text-sm text-destructive">The passwords don't match.</p>}
          <div className="flex items-center gap-3">
            <Button type="submit" disabled={change.isPending || mismatch}>Change password</Button>
            <Status pending={change.isPending} success={change.isSuccess} error={change.error} ok="Password changed" />
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

function DeleteCard() {
  const { logout } = useAuth()
  const navigate = useNavigate()
  const [password, setPassword] = useState('')
  const [sure, setSure] = useState(false)
  const del = useMutation({
    mutationFn: () => authApi.deleteAccount(password),
    onSuccess: () => { logout(); navigate('/', { replace: true }) },
  })
  return (
    <Card className="border-destructive/40">
      <CardHeader>
        <CardTitle className="text-destructive">Delete account</CardTitle>
        <CardDescription>
          Permanently deletes your account, every uploaded document file, extracted report, prescription and assistant
          conversation. This can't be undone. Download any reports you want to keep first.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={(e: FormEvent) => { e.preventDefault(); if (sure) del.mutate() }}>
          <Field id="delpw" label="Enter your password to confirm">
            <Input id="delpw" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} className="sm:max-w-sm" />
          </Field>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} />
            I understand that all my data will be permanently deleted.
          </label>
          <div className="flex items-center gap-3">
            <Button type="submit" variant="destructive" disabled={!sure || !password || del.isPending}>Delete my account</Button>
            <Status pending={del.isPending} success={false} error={del.error} ok="" />
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

export default function Settings() {
  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-muted-foreground">Your account, health profile and data.</p>
      </div>
      <AccountCard />
      <ProfileCard />
      <PasswordCard />
      <DeleteCard />
    </div>
  )
}
