/**
 * Login. Two demo accounts are listed on purpose: tenant isolation is a claim best
 * *shown*, and switching from Anna to Erik makes the same question return a different
 * company's numbers. The list is seeded data, not a credential store — it appears only
 * when the app runs against the demo seed.
 */

import { useState, type FormEvent } from 'react'
import { login } from '../lib/api'
import { useAuthStore } from '../lib/auth'
import { Button } from '../components/Button'
import { IconShield } from '../components/Icons'

const DEMO_ACCOUNTS = [
  { email: 'anna@nordstromaudio.se', label: 'Anna Lindqvist · Nordström Audio AB' },
  { email: 'erik@lagerkvisthem.se', label: 'Erik Sandberg · Lagerkvist Hem AB' },
]
const DEMO_PASSWORD = 'demo1234'

export function LoginPage() {
  const signIn = useAuthStore((state) => state.signIn)
  const [email, setEmail] = useState(DEMO_ACCOUNTS[0].email)
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
            Färdiga svar om din försäljning — med källa till varje siffra.
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

        <div className="mt-6 rounded-tile bg-surface-2 p-4">
          <p className="flex items-center gap-2 text-2xs font-medium text-ink-secondary">
            <IconShield className="h-3.5 w-3.5 text-ink-muted" />
            Demokonton
          </p>
          <ul className="mt-2.5 space-y-1.5">
            {DEMO_ACCOUNTS.map((account) => (
              <li key={account.email}>
                <button
                  type="button"
                  onClick={() => {
                    setEmail(account.email)
                    setPassword(DEMO_PASSWORD)
                  }}
                  className="w-full rounded-lg px-2 py-1.5 text-left text-2xs text-ink-secondary transition-colors duration-200 hover:bg-surface-3 hover:text-ink"
                >
                  {account.label}
                </button>
              </li>
            ))}
          </ul>
          <p className="mt-2 px-2 text-2xs text-ink-muted">
            Samma fråga, olika leverantör — så syns isoleringen live.
          </p>
        </div>
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
