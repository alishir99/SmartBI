/** The root: an auth gate, then the shell with whatever the hash route points at. */

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

  // Before the auth gate, and before the share check: whoever follows a reset link is by
  // definition someone who cannot sign in, and a stale session must not hide the form from
  // them either.
  if (reset) return <ResetPasswordPage token={reset} />

  // Before the auth gate: a share link is for someone who has no account here, and the token
  // is what authorises it. A session, if the reader happens to have one, changes nothing -
  // the card is still resolved under the scope of whoever shared it.
  if (shared) return <SharedPage token={shared} />

  if (!token || !user) return <LoginPage />

  return (
    <AppShell route={route}>
      {route === 'oversikt' && <OverviewPage />}
      {route === 'produkter' && <ProductsPage />}
      {route === 'geografi' && <GeographyPage />}
      {route === 'mina-vyer' && <SavedViewsPage />}
    </AppShell>
  )
}
