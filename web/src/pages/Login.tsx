/** Login. */

import { useState, type FormEvent } from 'react'
import { login } from '../lib/api'
import { useAuthStore } from '../lib/auth'
import { Button } from '../components/Button'

export function LoginPage() {
  const signIn = useAuthStore((state) => state.signIn)
  // The page used to arrive with a working account's address and password one click away.
  // Anyone who reached the login screen was already past the only door there is.
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const response = await login(email.trim(), password)
      signIn(response.access_token, response.user)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Inloggningen misslyckades.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-page px-5 py-10">
      <div className="animate-fade-up w-full max-w-sm">
        <div className="text-center">
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Solvigo Insights</h1>
          <p className="mt-2 text-sm text-ink-secondary">
            Färdiga svar om din försäljning, direkt ur handlarens data.
          </p>
        </div>

        <form
          onSubmit={submit}
          className="mt-8 rounded-card bg-surface p-6 shadow-card ring-hairline"
        >
          <Field
            id="email"
            label="E-post"
            type="email"
            value={email}
            autoComplete="username"
            onChange={setEmail}
          />
          <div className="mt-4">
            <Field
              id="password"
              label="Lösenord"
              type="password"
              value={password}
              autoComplete="current-password"
              onChange={setPassword}
            />
          </div>

          {error && (
            <p role="alert" className="mt-4 text-xs text-neg">
              {error}
            </p>
          )}

          <Button
            type="submit"
            variant="primary"
            size="md"
            loading={busy}
            disabled={!email.trim() || !password}
            className="mt-6 w-full"
          >
            Logga in
          </Button>
        </form>

        {/* No credentials on the page - anyone who reached it would already be past the only
            door there is. But a reviewer who opens the app before reading anything is otherwise
            simply stuck, so say where they are. */}
        <p className="mt-5 text-center text-2xs text-ink-muted">
          Demokonton finns i repots README.
        </p>
      </div>
    </div>
  )
}

function Field({
  id,
  label,
  type,
  value,
  autoComplete,
  onChange,
}: {
  id: string
  label: string
  type: string
  value: string
  autoComplete: string
  onChange: (value: string) => void
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-xs font-medium text-ink-secondary">
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        autoComplete={autoComplete}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1.5 h-10 w-full rounded-tile bg-surface-2 px-3.5 text-sm text-ink outline-none ring-hairline transition-shadow duration-200 focus:ring-1 focus:ring-accent"
      />
    </div>
  )
}
