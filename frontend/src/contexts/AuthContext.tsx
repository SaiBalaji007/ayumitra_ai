import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { authApi, tokens, type RegisterPayload, type User } from '@/services/api'

type AuthCtx = {
  user: User | null
  /** True while a stored session is being validated on first load. */
  initializing: boolean
  login: (email: string, password: string) => Promise<void>
  register: (payload: RegisterPayload) => Promise<void>
  logout: () => void
  /** Re-read the signed-in user after a profile change. */
  refreshUser: () => Promise<void>
}

const Ctx = createContext<AuthCtx | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [initializing, setInitializing] = useState(() => Boolean(tokens.access))

  const logout = useCallback(() => {
    tokens.clear()
    setUser(null)
  }, [])

  // Restore an existing session.
  useEffect(() => {
    if (!tokens.access) return
    authApi
      .me()
      .then(setUser)
      .catch(() => tokens.clear())
      .finally(() => setInitializing(false))
  }, [])

  // The API client fires this when the refresh token has expired.
  useEffect(() => {
    window.addEventListener('ayumitra:logout', logout)
    return () => window.removeEventListener('ayumitra:logout', logout)
  }, [logout])

  const login = useCallback(async (email: string, password: string) => {
    const { access, refresh } = await authApi.login(email, password)
    tokens.set(access, refresh)
    setUser(await authApi.me())
  }, [])

  const register = useCallback(
    async (payload: RegisterPayload) => {
      await authApi.register(payload)
      await login(payload.email, payload.password)
    },
    [login],
  )

  const refreshUser = useCallback(async () => {
    setUser(await authApi.me())
  }, [])

  return <Ctx.Provider value={{ user, initializing, login, register, logout, refreshUser }}>{children}</Ctx.Provider>
}

// oxlint-disable-next-line react/only-export-components -- hook lives beside its provider
export function useAuth() {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
