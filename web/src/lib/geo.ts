/** Coordinates come from the data (dim_store lat/lon, get_capabilities' mean per region), not
 * a hardcoded table - a hand-traced coastline was wrong the moment the app pointed elsewhere. */

import type { Geometry } from 'geojson'

export type LatLon = { lat: number; lon: number }
export type RegionPoint = LatLon & { region: string }

/** One land shape: an outer ring plus any holes, each ring as [lon, lat] pairs (GeoJSON order). */
export type Shape = number[][][]

/** How far (degrees) past the regions a country's island may lie and still be drawn: keeps
 * Gotland and Öland, drops far-off territories like Svalbard that would shrink the map. */
const NEARBY_DEG = 2

/** The land of every country holding at least one region, trimmed to the parts near the regions.
 * Empty when no region falls on land, and the map then shows markers only. */
export function outlineFor(countries: Geometry[], points: LatLon[]): Shape[] {
  if (points.length === 0) return []
  const lats = points.map((p) => p.lat)
  const lons = points.map((p) => p.lon)
  const box = {
    minLat: Math.min(...lats) - NEARBY_DEG,
    maxLat: Math.max(...lats) + NEARBY_DEG,
    minLon: Math.min(...lons) - NEARBY_DEG,
    maxLon: Math.max(...lons) + NEARBY_DEG,
  }
  return countries.flatMap((country) => {
    const shapes: Shape[] =
      country.type === 'Polygon' ? [country.coordinates] : country.type === 'MultiPolygon' ? country.coordinates : []
    const near = shapes.filter((shape) =>
      shape[0].some(([lon, lat]) => lat >= box.minLat && lat <= box.maxLat && lon >= box.minLon && lon <= box.maxLon),
    )
    // Tested on nearby shapes only: a far ring crossing 180° (eastern Russia) fools the ray cast
    // into "containing" Stockholm. ponytail: a market straddling 180° itself (Fiji) draws badly.
    return points.some((p) => near.some((shape) => ringContains(shape[0], p))) ? near : []
  })
}

/** Ray casting: is the point inside this ring? */
function ringContains(ring: number[][], { lat, lon }: LatLon): boolean {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [x1, y1] = ring[i]
    const [x2, y2] = ring[j]
    if (y1 > lat !== y2 > lat && lon < ((x2 - x1) * (lat - y1)) / (y2 - y1) + x1) inside = !inside
  }
  return inside
}

/** Look a region up by the label the API returns, tolerating a suffix like " län". */
export function findRegion(name: string, points: RegionPoint[]): RegionPoint | undefined {
  const exact = points.find((point) => point.region === name)
  if (exact) return exact
  const needle = normalise(name)
  return points.find((point) => normalise(point.region) === needle)
}

function normalise(value: string): string {
  return value.toLowerCase().trim()
}

export type Projection = {
  x: (point: LatLon) => number
  y: (point: LatLon) => number
}

/** Equirectangular with a cosine correction on longitude, taken at the mean latitude of the
 * points themselves - how much correction is needed depends entirely on where the data sits. */
export function project(
  points: LatLon[],
  width: number,
  height: number,
  padding: number,
): Projection {
  const lats = points.map((point) => point.lat)
  const lons = points.map((point) => point.lon)
  const meanLat = lats.reduce((sum, lat) => sum + lat, 0) / (lats.length || 1)
  const lonScale = Math.cos((meanLat * Math.PI) / 180)

  const minX = Math.min(...lons) * lonScale
  const maxX = Math.max(...lons) * lonScale
  const minY = Math.min(...lats)
  const maxY = Math.max(...lats)

  // A single region, or several sharing a latitude, gives a zero-width span - guard it, or
  // the scale is Infinity and every marker lands in the same pixel.
  const spanX = maxX - minX || 1
  const spanY = maxY - minY || 1

  // One scale for both axes, so the shape survives; points are then centred in whatever
  // box they didn't fill.
  const scale = Math.min((width - padding * 2) / spanX, (height - padding * 2) / spanY)
  const offsetX = (width - spanX * scale) / 2
  const offsetY = (height - spanY * scale) / 2

  return {
    x: (point) => (point.lon * lonScale - minX) * scale + offsetX,
    // SVG y grows downward and latitude grows north, so this flips.
    y: (point) => (maxY - point.lat) * scale + offsetY,
  }
}

/** Radius for a value, area-proportional rather than radius-proportional. */
export function radiusFor(
  value: number,
  max: number,
  minRadius: number,
  maxRadius: number,
): number {
  if (max <= 0 || value <= 0) return minRadius
  return minRadius + (maxRadius - minRadius) * Math.sqrt(value / max)
}
