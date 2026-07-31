/** TanStack Query hooks. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { SaveCardRequest } from '../types'
import { DEFAULT_PERIOD } from './periods'
import {
  deleteCard,
  fetchCards,
  fetchDashboard,
  fetchResult,
  saveCard,
  shareCard,
} from './api'

export const queryKeys = {
  // The period is part of the key: two windows are two different results, and sharing one cache
  // entry between them would show last year's figures under this week's label.
  dashboard: (period: string) => ['dashboard', period] as const,
  cards: ['cards'] as const,
  result: (queryId: string) => ['result', queryId] as const,
}

export function useDashboard(period: string = DEFAULT_PERIOD) {
  return useQuery({
    queryKey: queryKeys.dashboard(period),
    queryFn: () => fetchDashboard(period),
    staleTime: 5 * 60 * 1000,
    // Keeps the previous window on screen while the next one loads, so switching period does
    // not blank the page and bounce the layout.
    placeholderData: (previous) => previous,
  })
}

/** `enabled` is false for cards without a query_id — clarify / cannot_answer cards. */
export function useResult(queryId: string | null) {
  return useQuery({
    queryKey: queryKeys.result(queryId ?? 'none'),
    queryFn: () => fetchResult(queryId as string),
    enabled: queryId !== null,
    staleTime: Infinity,
    gcTime: 30 * 60 * 1000,
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
