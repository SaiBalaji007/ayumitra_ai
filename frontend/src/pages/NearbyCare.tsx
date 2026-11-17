import 'leaflet/dist/leaflet.css'
import { useMutation } from '@tanstack/react-query'
import L from 'leaflet'
import { AlertTriangle, Clock, Globe, Loader2, MapPin, Navigation, Phone, Search } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { apiErrorMessage, careApi, type CareCategory, type Facility, type NearbyResult } from '@/services/api'

const CATEGORIES: { value: CareCategory; label: string }[] = [
  { value: 'all', label: 'All medical facilities' },
  { value: 'hospital', label: 'Hospitals' },
  { value: 'clinic', label: 'Clinics' },
  { value: 'pharmacy', label: 'Pharmacies / Medical shops' },
  { value: 'doctor', label: 'Doctors' },
]
const COLORS: Record<Facility['category'], string> = { hospital: '#ef4444', clinic: '#14b8a6', pharmacy: '#8b5cf6', doctor: '#f59e0b' }
const LABELS: Record<Facility['category'], string> = { hospital: 'Hospital', clinic: 'Clinic', pharmacy: 'Pharmacy', doctor: 'Doctor' }
const selectClass = 'flex h-10 w-full rounded-lg border border-input bg-background px-3 text-sm'
const NA = <span className="text-muted-foreground">Not available</span>

const escape = (s: string) => s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!)
const directionsUrl = (f: Facility) => `https://www.openstreetmap.org/directions?route=;${f.lat},${f.lon}`
const googleDirections = (f: Facility) => `https://www.google.com/maps/dir/?api=1&destination=${f.lat},${f.lon}`

function FacilityMap({ data, focus }: { data: NearbyResult; focus: Facility | null }) {
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const markers = useRef<Map<string, L.CircleMarker>>(new Map())

  useEffect(() => {
    if (!el.current) return
    const m = L.map(el.current).setView([data.place.lat, data.place.lon], 13)
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(m)
    L.circle([data.place.lat, data.place.lon], { radius: data.radius_km * 1000, color: '#14b8a6', weight: 1, fillOpacity: 0.04 }).addTo(m)
    L.circleMarker([data.place.lat, data.place.lon], { radius: 6, color: '#0f172a', fillColor: '#ffffff', fillOpacity: 1, weight: 2 })
      .addTo(m)
      .bindPopup(`<b>Search centre</b><br>${escape(data.place.name)}`)
    markers.current.clear()
    for (const f of data.facilities) {
      const mk = L.circleMarker([f.lat, f.lon], { radius: 7, color: '#ffffff', weight: 1.5, fillColor: COLORS[f.category], fillOpacity: 0.95 })
        .addTo(m)
        .bindPopup(
          `<b>${escape(f.name)}</b><br>${LABELS[f.category]} · ${f.distance_km} km` +
            `<br>Phone: ${f.phone ? escape(f.phone) : 'Not available'}` +
            (f.opening_hours ? `<br>Hours: ${escape(f.opening_hours)}` : '') +
            `<br><a href="${googleDirections(f)}" target="_blank" rel="noopener noreferrer">Get directions</a>`,
        )
      markers.current.set(f.id, mk)
    }
    map.current = m
    return () => {
      m.remove()
      map.current = null
    }
  }, [data])

  useEffect(() => {
    if (!focus || !map.current) return
    map.current.setView([focus.lat, focus.lon], 16)
    markers.current.get(focus.id)?.openPopup()
    el.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [focus])

  return <div ref={el} className="h-[360px] w-full overflow-hidden rounded-xl border sm:h-[440px]" role="region" aria-label="Map of nearby facilities" />
}

function FacilityCard({ f, onView }: { f: Facility; onView: () => void }) {
  return (
    <Card>
      <CardContent className="space-y-2 p-4 text-sm">
        <div className="flex items-start justify-between gap-2">
          <p className="font-medium">{f.name}</p>
          <span className="shrink-0 rounded-full px-2 py-0.5 text-xs font-medium text-white" style={{ background: COLORS[f.category] }}>
            {LABELS[f.category]}
          </span>
        </div>
        <p className="flex gap-2"><MapPin className="mt-0.5 size-3.5 shrink-0 text-primary" /> {f.address || NA} · {f.distance_km} km</p>
        <p className="flex gap-2"><Phone className="mt-0.5 size-3.5 shrink-0 text-primary" />{f.phone ? <a href={`tel:${f.phone}`} className="hover:underline">{f.phone}</a> : NA}</p>
        <p className="flex gap-2"><Clock className="mt-0.5 size-3.5 shrink-0 text-primary" /> {f.opening_hours || NA}</p>
        <p className="flex gap-2"><Globe className="mt-0.5 size-3.5 shrink-0 text-primary" />
          {f.website ? <a href={f.website} target="_blank" rel="noopener noreferrer" className="truncate text-primary hover:underline">{f.website}</a> : NA}
        </p>
        <div className="flex gap-2 pt-1">
          <Button size="sm" variant="outline" onClick={onView}><MapPin /> View on map</Button>
          <a href={googleDirections(f)} target="_blank" rel="noopener noreferrer" className="inline-flex h-8 items-center gap-1.5 rounded-md bg-primary px-3 text-xs font-medium text-primary-foreground hover:bg-primary/90">
            <Navigation className="size-3.5" /> Get directions
          </a>
          <a href={directionsUrl(f)} target="_blank" rel="noopener noreferrer" className="inline-flex h-8 items-center px-1 text-xs text-muted-foreground hover:underline">OSM route</a>
        </div>
      </CardContent>
    </Card>
  )
}

export default function NearbyCare() {
  const [city, setCity] = useState('')
  const [locality, setLocality] = useState('')
  const [category, setCategory] = useState<CareCategory>('all')
  const [radius, setRadius] = useState(5)
  const [focus, setFocus] = useState<Facility | null>(null)
  const search = useMutation({ mutationFn: careApi.nearby, onSuccess: () => setFocus(null) })

  function submit(e: FormEvent) {
    e.preventDefault()
    if (city.trim().length >= 2) search.mutate({ city: city.trim(), locality: locality.trim() || undefined, category, radius })
  }

  const data = search.data
  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <h2 className="text-2xl font-semibold tracking-tight">Find Hospitals & Medical Shops</h2>
        <p className="text-sm text-muted-foreground">Hospitals, clinics, doctors and pharmacies near a city or locality, from OpenStreetMap.</p>
      </div>

      <Card>
        <CardContent className="p-4">
          <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[1.4fr_1.2fr_1.2fr_0.7fr_auto] lg:items-end">
            <div className="space-y-1.5"><Label htmlFor="city">City</Label>
              <Input id="city" required minLength={2} maxLength={100} placeholder="e.g. Noida, Uttar Pradesh" value={city} onChange={(e) => setCity(e.target.value)} /></div>
            <div className="space-y-1.5"><Label htmlFor="loc">Locality / area (optional)</Label>
              <Input id="loc" maxLength={100} placeholder="e.g. Sector 18" value={locality} onChange={(e) => setLocality(e.target.value)} /></div>
            <div className="space-y-1.5"><Label htmlFor="cat">Category</Label>
              <select id="cat" className={selectClass} value={category} onChange={(e) => setCategory(e.target.value as CareCategory)}>
                {CATEGORIES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
              </select></div>
            <div className="space-y-1.5"><Label htmlFor="rad">Radius</Label>
              <select id="rad" className={selectClass} value={radius} onChange={(e) => setRadius(Number(e.target.value))}>
                {[2, 5, 10, 20].map((r) => <option key={r} value={r}>{r} km</option>)}
              </select></div>
            <Button type="submit" disabled={search.isPending || city.trim().length < 2}>
              {search.isPending ? <Loader2 className="animate-spin" /> : <Search />} Search
            </Button>
          </form>
          <p className="mt-3 text-xs text-muted-foreground">
            Searches around the centre of the city or locality you enter, not your live location. Details come from OpenStreetMap
            volunteers and may be incomplete; call ahead to confirm. In an emergency, call 112.
          </p>
        </CardContent>
      </Card>

      {search.isPending && (
        <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
          <Loader2 className="size-5 animate-spin text-primary" /> Finding medical facilities… this can take up to a minute.
        </div>
      )}
      {search.isError && <Alert variant="destructive"><AlertTriangle />{apiErrorMessage(search.error)}</Alert>}

      {data && !search.isPending && (
        <>
          <p className="text-sm">
            <span className="font-medium">{data.count}</span> {data.count === 1 ? 'place' : 'places'} within {data.radius_km} km of{' '}
            <span className="font-medium">{data.place.name}</span>, nearest first.
          </p>
          <div className="flex flex-wrap gap-3 text-xs">
            {(Object.keys(COLORS) as Facility['category'][]).map((k) => (
              <span key={k} className="inline-flex items-center gap-1.5"><span className="size-3 rounded-full" style={{ background: COLORS[k] }} />{LABELS[k]}</span>
            ))}
          </div>
          <FacilityMap data={data} focus={focus} />
          {data.count === 0 ? (
            <p className="rounded-xl border p-6 text-center text-sm text-muted-foreground">
              No facilities found in this area. Try a larger radius or another category.
            </p>
          ) : (
            <div className="grid gap-3 md:grid-cols-2">
              {data.facilities.map((f) => <FacilityCard key={f.id} f={f} onView={() => setFocus(f)} />)}
            </div>
          )}
          <p className="text-xs text-muted-foreground">{data.attribution}</p>
        </>
      )}
    </div>
  )
}
