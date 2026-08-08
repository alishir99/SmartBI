
import { useEffect } from 'react'
import { useAuthStore } from './lib/auth'
import { useChatStore } from './lib/chat'
import { useResetToken, useRoute, useSharedToken } from './lib/router'
import { AppShell } from './components/AppShell'
import { LoginPage } from './pages/Login'
import { SharedPage } from './pages/Shared'
import { ResetPasswordPage } from './pages/ResetPassword'
import { OverviewPage } from './pages/Overview'
import { ProductsPage } from './pages/Products'
import { GeographyPage } from './pages/Geography'
import { SavedViewsPage } from './pages/SavedViews'

export function App() {
  const user = useAuthStore((state) => state.user)
  const token = useAuthStore((state) => state.token)
  const resetChat = useChatStore((state) => state.reset)

  const userId = user?.user_id ?? null
  useEffect(() => {
    resetChat()
  }, [userId, resetChat])

  const [route] = useRoute()
  const shared = useSharedToken()
  const reset = useResetToken()

  // Before the auth gate: a reset link is for someone who cannot sign in, and a stale session
  // must not hide the form from them.
  if (reset) return <ResetPasswordPage token={reset} />

  // Before the auth gate: the token alone authorises a share link, and a session the reader
  // happens to have changes nothing - the card resolves under the sharer's scope.
  if (shared) return <SharedPage token={shared} />

  if (!token || !user) return <LoginPage />

  return (
    <AppShell route={route}>
      {route === 'overview' && <OverviewPage />}
      {route === 'products' && <ProductsPage />}
      {route === 'geography' && <GeographyPage />}
      {route === 'saved-views' && <SavedViewsPage />}
    </AppShell>
  )
}
