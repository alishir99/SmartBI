/** The root: an auth gate, then the shell with whatever the hash route points at. */

import { useEffect } from 'react'
import { useAuthStore } from './lib/auth'
import { useChatStore } from './lib/chat'
import { useRoute } from './lib/router'
import { AppShell } from './components/AppShell'
import { LoginPage } from './pages/Login'
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
