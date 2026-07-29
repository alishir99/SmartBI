import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App } from './App'
import { ApiError } from './lib/api'
import { useAuthStore } from './lib/auth'
import './index.css'

/**
 * An expired token should end the session everywhere at once, not once per component.
 * Both caches funnel 401s through the same handler, so the app falls back to the login
 * screen the moment the first request is refused.
 */
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
      // A 401 or 403 will not become a 200 on the next try; only retry transport failures.
      retry: (failureCount, error) =>
        !(error instanceof ApiError && error.status < 500) && failureCount < 2,
      refetchOnWindowFocus: false,
    },
  },
})

createRoot(document.getElementById('root') as HTMLElement).render(
  <StrictMode>
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)
