import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App } from './App'
import { ApiError } from './lib/api'
import { useAuthStore } from './lib/auth'
import { loadConfig } from './lib/config'
import { apiUrl } from './lib/env'
import { currentLanguage } from './lib/i18n'
import './index.css'

function onError(error: unknown): void {
  if (error instanceof ApiError && error.status === 401) {
    useAuthStore.getState().signOut()
  }
}

const client = new QueryClient({
  queryCache: new QueryCache({ onError }),
  mutationCache: new MutationCache({ onError }),
  defaultOptions: {
    queries: {
      retry: (failureCount, error) =>
        !(error instanceof ApiError && error.status < 500) && failureCount < 2,
      refetchOnWindowFocus: false,
    },
  },
})

document.documentElement.lang = currentLanguage()

// /api/config only wakes the api; this also starts mcp and the DB pool while the user is
// still on the login screen, so the first dashboard isn't the one paying for the cold start.
void fetch(apiUrl('/api/warm')).catch(() => {})

void loadConfig().then(() => {
  createRoot(document.getElementById('root') as HTMLElement).render(
    <StrictMode>
      <QueryClientProvider client={client}>
        <App />
      </QueryClientProvider>
    </StrictMode>,
  )
})
