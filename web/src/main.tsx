import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App } from './App'
import { ApiError } from './lib/api'
import { useAuthStore } from './lib/auth'
import { loadConfig } from './lib/config'
import { currentLanguage } from './lib/i18n'
import './index.css'

/** An expired token should end the session everywhere at once, not once per component. */
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

// The <html lang> a screen reader reads the page's pronunciation from, set before first paint.
document.documentElement.lang = currentLanguage()

// Awaited, so the first render already knows the currency. Resolving it a tick later would
// flip every amount on screen once the config landed, which reads as a glitch - and, for the
// moment before it, as a wrong number. `loadConfig` never rejects; an unreachable API falls
// back to the build's defaults and is about to be visible everywhere else anyway.
void loadConfig().then(() => {
  createRoot(document.getElementById('root') as HTMLElement).render(
    <StrictMode>
      <QueryClientProvider client={client}>
        <App />
      </QueryClientProvider>
    </StrictMode>,
  )
})
