import { Loader2 } from 'lucide-react'
import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router-dom'
import { GuestOnly, RequireAuth } from '@/components/RouteGuards'
import MarketingLayout from '@/layouts/MarketingLayout'
import NotFound from '@/pages/NotFound'

// Route-level code splitting: visitors to the landing page don't download the app, and vice versa.
const Landing = lazy(() => import('@/pages/Landing'))
const Login = lazy(() => import('@/pages/Login'))
const Register = lazy(() => import('@/pages/Register'))
const AppLayout = lazy(() => import('@/layouts/AppLayout'))
const Dashboard = lazy(() => import('@/pages/Dashboard'))
const ComingSoon = lazy(() => import('@/pages/ComingSoon'))
const Documents = lazy(() => import('@/pages/Documents'))

const UPCOMING = [
  { path: 'prescriptions', title: 'Prescription intelligence', phase: 'Phase 9', description: 'Extract medicines and instructions, confirm uncertain fields, and read verified medicine information.' },
  { path: 'assistant', title: 'AI medical assistant', phase: 'Phase 8', description: 'Ask questions about your reports and get answers with cited evidence.' },
  { path: 'timeline', title: 'Health timeline', phase: 'Phase 11', description: 'Compare reports over time and chart how your parameters change.' },
  { path: 'nutrition', title: 'Nutrition & lifestyle', phase: 'Phase 11', description: 'General food, activity and lifestyle education linked to your results.' },
  { path: 'exports', title: 'Reports & exports', phase: 'Phase 11', description: 'Download summaries with their evidence and disclaimers.' },
  { path: 'settings', title: 'Settings', phase: 'Coming soon', description: 'Profile, privacy controls, and data management including deletion.' },
]

function PageFallback() {
  return (
    <div className="grid min-h-[50svh] place-items-center">
      <Loader2 className="size-6 animate-spin text-primary" aria-label="Loading" />
    </div>
  )
}

export default function App() {
  return (
    <Suspense fallback={<PageFallback />}>
      <Routes>
        <Route element={<MarketingLayout />}>
          <Route index element={<Landing />} />
        </Route>

        <Route element={<GuestOnly />}>
          <Route path="login" element={<Login />} />
          <Route path="register" element={<Register />} />
        </Route>

        <Route element={<RequireAuth />}>
          <Route path="app" element={<AppLayout />}>
            <Route index element={<Dashboard />} />
            <Route path="documents" element={<Documents />} />
            {UPCOMING.map(({ path, ...props }) => (
              <Route key={path} path={path} element={<ComingSoon {...props} />} />
            ))}
            <Route path="*" element={<NotFound />} />
          </Route>
        </Route>

        <Route element={<MarketingLayout />}>
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  )
}
