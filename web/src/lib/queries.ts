
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { feature } from 'topojson-client'
import type { GeometryCollection, Topology } from 'topojson-specification'
import worldUrl from 'world-atlas/countries-50m.json?url'
import type { SaveCardRequest } from '../types'
import { DEFAULT_PERIOD } from './periods'
import {
  deleteCard,
  fetchCards,
  fetchDashboard,
  fetchMovers,
  fetchRegions,
  fetchResult,
  saveCard,
  shareCard,
} from './api'
import { useLanguageStore } from './i18n'

export const queryKeys = {
  // Period is part of the key: two windows are two different results, and sharing one cache
  // entry between them would show last year's figures under this week's label.
  dashboard: (period: string) => ['dashboard', period] as const,
  movers: (period: string) => ['movers', period] as const,
  cards: ['cards'] as const,
  result: (queryId: string) => ['result', queryId] as const,
  regions: ['regions'] as const,
  countries: ['countries'] as const,
}

// Language is part of the key wherever the server writes text into the response (card titles,
// KPI labels, caveats) - TanStack has no way to know the request differed unless the key says so.
export function useDashboard(period: string = DEFAULT_PERIOD) {
  const lang = useLanguageStore((state) => state.lang)
  return useQuery({
    queryKey: [...queryKeys.dashboard(period), lang],
    queryFn: () => fetchDashboard(period),
    staleTime: 5 * 60 * 1000,
    // Keeps the previous window on screen while the next loads, so switching period doesn't
    // blank the page and bounce the layout.
    placeholderData: (previous) => previous,
  })
}

export function useMovers(period: string = DEFAULT_PERIOD) {
  const lang = useLanguageStore((state) => state.lang)
  return useQuery({
    queryKey: [...queryKeys.movers(period), lang],
    queryFn: () => fetchMovers(period),
    staleTime: 5 * 60 * 1000,
    placeholderData: (previous) => previous,
  })
}

/** `enabled` is false for cards without a query_id - clarify / cannot_answer cards. */
export function useResult(queryId: string | null) {
  return useQuery({
    queryKey: queryKeys.result(queryId ?? 'none'),
    queryFn: () => fetchResult(queryId as string),
    enabled: queryId !== null,
    staleTime: Infinity,
    gcTime: 30 * 60 * 1000,
  })
}

/** Region centroids. One per deployment and effectively static, so it's fetched once. */
export function useRegions() {
  return useQuery({
    queryKey: queryKeys.regions,
    queryFn: fetchRegions,
    staleTime: Infinity,
  })
}

/** Country shapes (Natural Earth 1:50m) for the map's land. A static file, fetched only once a
 * map is opened; geo.ts picks the countries the regions sit in. */
export function useCountries() {
  return useQuery({
    queryKey: queryKeys.countries,
    queryFn: async () => {
      const response = await fetch(worldUrl)
      if (!response.ok) throw new Error(`countries: ${response.status}`)
      const world = (await response.json()) as Topology<{ countries: GeometryCollection }>
      return feature(world, world.objects.countries).features.map((country) => country.geometry)
    },
    staleTime: Infinity,
  })
}

export function useSavedCards() {
  return useQuery({
    queryKey: queryKeys.cards,
    queryFn: fetchCards,
    staleTime: 60 * 1000,
  })
}

export function useSaveCard() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (body: SaveCardRequest) => saveCard(body),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.cards }),
  })
}

export function useDeleteCard() {
  const client = useQueryClient()
  return useMutation({
    mutationFn: (cardId: string) => deleteCard(cardId),
    onSuccess: () => client.invalidateQueries({ queryKey: queryKeys.cards }),
  })
}

export function useShareCard() {
  return useMutation({
    mutationFn: ({ cardId, mode }: { cardId: string; mode: 'snapshot' | 'live' }) =>
      shareCard(cardId, mode),
  })
}
