/** Coordinates come from the data (dim_store lat/lon, get_capabilities' mean per region), not
 * a hardcoded table - a hand-traced coastline was wrong the moment the app pointed elsewhere. */

export type RegionPoint = { region: string; lat: number; lon: number }

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
  x: (point: RegionPoint) => number
  y: (point: RegionPoint) => number
}

/** Equirectangular with a cosine correction on longitude, taken at the mean latitude of the
 * points themselves - how much correction is needed depends entirely on where the data sits. */
export function project(
  points: RegionPoint[],
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
