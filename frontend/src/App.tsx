import { Loader2 } from 'lucide-react'
import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { GuestOnly, RequireAuth } from '@/components/RouteGuards'
import MarketingLayout from '@/layouts/MarketingLayout'
import NotFound from '@/pages/NotFound'

// Route-level code splitting: visitors to the landing page don't download the app, and vice versa.
const Landing = lazy(() => import('@/pages/Landing'))
const Login = lazy(() => import('@/pages/Login'))
const Register = lazy(() => import('@/pages/Register'))
const AppLayout = lazy(() => import('@/layouts/AppLayout'))
const Dashboard = lazy(() => import('@/pages/Dashboard'))
const Documents = lazy(() => import('@/pages/Documents'))
const Assistant = lazy(() => import('@/pages/Assistant'))
const Reports = lazy(() => import('@/pages/Reports'))
const Prescriptions = lazy(() => import('@/pages/Prescriptions'))
const Timeline = lazy(() => import('@/pages/Timeline'))
const Settings = lazy(() => import('@/pages/Settings'))
const Diet = lazy(() => import('@/pages/Diet'))
const Lifestyle = lazy(() => import('@/pages/Lifestyle'))
const NearbyCare = lazy(() => import('@/pages/NearbyCare'))
const PrescriptionAnalyzer = lazy(() => import('@/pages/PrescriptionAnalyzer'))

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
            <Route path="assistant" element={<Assistant />} />
            <Route path="reports" element={<Reports />} />
            <Route path="reports/:id" element={<Reports />} />
            <Route path="prescriptions" element={<Prescriptions />} />
            <Route path="prescriptions/:id" element={<Prescriptions />} />
            <Route path="timeline" element={<Timeline />} />
            <Route path="nearby" element={<NearbyCare />} />
            <Route path="prescription-analyzer" element={<PrescriptionAnalyzer />} />
            <Route path="diet" element={<Diet />} />
            <Route path="lifestyle" element={<Lifestyle />} />
            <Route path="nutrition" element={<Navigate to="/app/diet" replace />} />
            {/* PDF export lives on each lab report's page. */}
            <Route path="exports" element={<Navigate to="/app/reports" replace />} />
            <Route path="settings" element={<Settings />} />
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
