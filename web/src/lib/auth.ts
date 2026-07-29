/**
 * Auth store. The token lives here and in localStorage; api.ts reads it through
 * getToken() so no component ever passes it around.
 */

import { create } from 'zustand'
import type { User } from '../types'

const TOKEN_KEY = 'solvigo.token'
const USER_KEY = 'solvigo.user'

function readStoredUser(): User | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as User) : null
  } catch {
    return null
  }
}

function readStoredToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

type AuthState = {
  token: string | null
  user: User | null
  signIn: (token: string, user: User) => void
  signOut: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  token: readStoredToken(),
  user: readStoredUser(),
  signIn: (token, user) => {
    try {
      localStorage.setItem(TOKEN_KEY, token)
      localStorage.setItem(USER_KEY, JSON.stringify(user))
    } catch {
      /* private browsing */
    }
    set({ token, user })
  },
  signOut: () => {
    try {
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
    } catch {
      /* private browsing */
    }
    set({ token: null, user: null })
  },
}))

/** Non-reactive read, for the fetch layer. */
export function getToken(): string | null {
  return useAuthStore.getState().token
}
