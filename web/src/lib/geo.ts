/**
 * Where the 21 län sit, and how to get them onto an SVG.
 *
 * These are not hand-placed. Each coordinate is the mean position of that county's stores
 * in `data/generated/dim_store.csv`, so the layout is derived from the same data the map
 * plots rather than from an eyeballed sketch of Sweden. That matters for a demo: the shape
 * a viewer recognises is evidence the positions are real, and a county sitting slightly off
 * where a wall map would put it is honest — it is where this supplier's shops actually are.
 *
 * The coastline they sit on is equally real: `swedenOutline.ts` is generated from Natural
 * Earth's public-domain 1:10m boundaries, not traced. Nothing on this map is drawn by hand —
 * which is the only reason it is allowed to sit next to measured figures.
 *
 * County *borders* are still absent. Natural Earth's admin-1 set would supply them and turn
 * this into a choropleth; the outline is the useful 90% and costs 10 kB.
 */

import { OUTLINE_BOUNDS } from './swedenOutline'

export type RegionPoint = { region: string; lat: number; lon: number }

/** Mean store position per county. Sorted north to south. */
export const REGION_POINTS: RegionPoint[] = [
  { region: 'Norrbottens län', lat: 65.4602, lon: 21.8345 },
  { region: 'Västerbottens län', lat: 64.2874, lon: 20.6299 },
  { region: 'Jämtlands län', lat: 63.1774, lon: 14.6303 },
  { region: 'Västernorrlands län', lat: 62.8393, lon: 18.0235 },
  { region: 'Gävleborgs län', lat: 60.6566, lon: 16.9582 },
  { region: 'Dalarnas län', lat: 60.5446, lon: 15.5184 },
  { region: 'Uppsala län', lat: 59.863, lon: 17.6141 },
  { region: 'Västmanlands län', lat: 59.6065, lon: 16.5464 },
  { region: 'Stockholms län', lat: 59.4304, lon: 18.1294 },
  { region: 'Värmlands län', lat: 59.4033, lon: 13.5033 },
  { region: 'Örebro län', lat: 59.2785, lon: 15.2035 },
  { region: 'Södermanlands län', lat: 59.1628, lon: 16.6929 },
  { region: 'Östergötlands län', lat: 58.4982, lon: 15.8889 },
  { region: 'Västra Götalands län', lat: 57.715, lon: 12.4526 },
  { region: 'Gotlands län', lat: 57.6338, lon: 18.2899 },
  { region: 'Jönköpings län', lat: 57.4775, lon: 14.1392 },
  { region: 'Kalmar län', lat: 57.2012, lon: 16.517 },
  { region: 'Kronobergs län', lat: 56.8735, lon: 14.815 },
  { region: 'Hallands län', lat: 56.6786, lon: 12.8592 },
  { region: 'Blekinge län', lat: 56.1537, lon: 15.5822 },
  { region: 'Skåne län', lat: 55.8263, lon: 13.2404 },
]

const BY_NAME = new Map(REGION_POINTS.map((point) => [point.region, point]))

/**
 * Look a county up by the label the API returns. Falls back to a loose match so that
 * "Skåne" finds "Skåne län" — the tools return canonical names, but a saved view or a chat
 * answer may carry the short form.
 */
export function findRegion(name: string): RegionPoint | undefined {
  const exact = BY_NAME.get(name)
  if (exact) return exact
  const needle = name.toLowerCase().replace(/\s*län$/, '').trim()
  return REGION_POINTS.find(
    (point) => point.region.toLowerCase().replace(/\s*län$/, '').trim() === needle,
  )
}

/**
 * Equirectangular projection with a cosine correction on longitude.
 *
 * Sweden spans roughly 55.5°N to 69°N, where a degree of longitude is about half the
 * ground distance of a degree of latitude. Plotting raw lon/lat would stretch the country
 * sideways into something nobody recognises; scaling x by cos(mean latitude) keeps the
 * proportions close enough to read as Sweden without pulling in a projection library.
 */
const MEAN_LAT_RAD = ((55.8 + 65.5) / 2) * (Math.PI / 180)
const LON_SCALE = Math.cos(MEAN_LAT_RAD)

export type Projection = { x: (point: RegionPoint) => number; y: (point: RegionPoint) => number }

/**
 * Project a lon/lat onto the map's viewBox.
 *
 * The bounds come from `OUTLINE_BOUNDS` — the extent of the *coastline*, not of the store
 * centroids. That is the whole point: fitting to the centroids would scale the bubbles to
 * their own bounding box and float them off the country beneath. Both layers now derive
 * from one set of numbers, so a county's circle sits where the county is.
 */
export function project(): Projection {
  const { minX, maxX, minY, maxY, width, height, padding } = OUTLINE_BOUNDS

  // One scale for both axes, so the aspect ratio survives; the country is then centred in
  // whatever box it did not fill.
  const scale = Math.min(
    (width - padding * 2) / (maxX - minX),
    (height - padding * 2) / (maxY - minY),
  )
  const offsetX = (width - (maxX - minX) * scale) / 2
  const offsetY = (height - (maxY - minY) * scale) / 2

  return {
    x: (point) => (point.lon * LON_SCALE - minX) * scale + offsetX,
    // SVG y grows downward and latitude grows north, so this flips.
    y: (point) => (maxY - point.lat) * scale + offsetY,
  }
}

/**
 * Radius for a value, area-proportional rather than radius-proportional.
 *
 * A circle whose *radius* tracks the value exaggerates the top of the range enormously —
 * Stockholm outsells Gotland roughly fortyfold here, which would be a 40x radius and a
 * 1600x blob. Area is what the eye actually compares, so the radius follows the square root.
 */
export function radiusFor(value: number, max: number, minRadius: number, maxRadius: number): number {
  if (max <= 0 || value <= 0) return minRadius
  return minRadius + (maxRadius - minRadius) * Math.sqrt(value / max)
}
