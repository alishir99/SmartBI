import { feature } from 'topojson-client'
import type { GeometryCollection, Topology } from 'topojson-specification'
import { describe, expect, it } from 'vitest'
import worldJson from 'world-atlas/countries-50m.json?raw'
import { outlineFor } from './geo'

const world = JSON.parse(worldJson) as Topology<{ countries: GeometryCollection }>
const countries = feature(world, world.objects.countries).features.map((country) => country.geometry)

const lats = (shapes: number[][][][]) => shapes.flatMap((shape) => shape[0].map(([, lat]) => lat))

describe('outlineFor', () => {
  it('draws Sweden, islands included, for Swedish regions', () => {
    const regions = [
      { lat: 59.43, lon: 18.12 }, // Stockholm
      { lat: 55.6, lon: 13.0 }, // Malmö
      { lat: 66.8, lon: 21.4 }, // Norrbotten
      { lat: 57.63, lon: 18.3 }, // Gotland
    ]
    const outline = outlineFor(countries, regions)
    expect(outline.length).toBeGreaterThan(2) // mainland, Gotland, Öland
    expect(Math.min(...lats(outline))).toBeLessThan(55.5) // Skåne's tip
    expect(Math.min(...lats(outline))).toBeGreaterThan(55.2) // ...and nothing further south (Kaliningrad)
    expect(Math.max(...lats(outline))).toBeGreaterThan(68.9) // Kiruna's north
  })

  it('leaves out far-off land of the same country', () => {
    const outline = outlineFor(countries, [{ lat: 59.91, lon: 10.75 }, { lat: 69.65, lon: 18.96 }]) // Oslo, Tromsø
    expect(Math.max(...lats(outline))).toBeLessThan(72) // no Svalbard
  })

  it('draws nothing when no region is on land', () => {
    expect(outlineFor(countries, [{ lat: 0, lon: -30 }])).toEqual([])
  })
})
