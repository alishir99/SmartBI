/** Login, and the "I cannot get in" path next to it. */

import { useState, type FormEvent, type ReactNode } from 'react'
import { forgotPassword, login } from '../lib/api'
import { useAuthStore } from '../lib/auth'
import { useT } from '../lib/i18n'
import { Button } from '../components/Button'
import { Field } from '../components/Field'

export function LoginPage() {
  const [mode, setMode] = useState<'signIn' | 'forgot'>('signIn')

  return (
    <div className="flex min-h-screen items-center justify-center bg-page px-5 py-10">
      <div className="animate-fade-up w-full max-w-sm">
        {mode === 'signIn' ? (
          <SignInForm onForgot={() => setMode('forgot')} />
        ) : (
          <ForgotForm onBack={() => setMode('signIn')} />
        )}
      </div>
    </div>
  )
}

function Header({ title, description }: { title: string; description: string }) {
  return (
    <div className="text-center">
      <h1 className="text-2xl font-semibold tracking-tight text-ink">{title}</h1>
      <p className="mt-2 text-sm text-ink-secondary">{description}</p>
    </div>
  )
}

function Card({
  children,
  onSubmit,
}: {
  children: ReactNode
  onSubmit: (event: FormEvent) => void
}) {
  return (
    <form
      onSubmit={onSubmit}
      className="mt-8 rounded-card bg-surface p-6 shadow-card ring-hairline"
    >
      {children}
    </form>
  )
}

function LinkButton({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="mt-4 block w-full text-center text-2xs text-ink-secondary underline-offset-4 hover:text-ink hover:underline"
    >
      {children}
    </button>
  )
}

function SignInForm({ onForgot }: { onForgot: () => void }) {
  const t = useT()
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
      setError(caught instanceof Error ? caught.message : t('login.failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <Header title={t('login.title')} description={t('login.subtitle')} />
      <Card onSubmit={submit}>
        <Field
          id="email"
          label={t('login.email')}
          type="email"
          value={email}
          autoComplete="username"
          onChange={setEmail}
        />
        <div className="mt-4">
          <Field
            id="password"
            label={t('login.password')}
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
          {busy ? t('login.pending') : t('login.submit')}
        </Button>

        <LinkButton onClick={onForgot}>{t('login.forgot')}</LinkButton>
      </Card>

      {/* No credentials on the page - anyone who reached it would already be past the only
          door there is. But a reviewer who opens the app before reading anything is otherwise
          simply stuck, so say where they are. */}
      <p className="mt-5 text-center text-2xs text-ink-muted">{t('login.demo_hint')}</p>
    </>
  )
}

function ForgotForm({ onBack }: { onBack: () => void }) {
  const t = useT()
  const [email, setEmail] = useState('')
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState<string | null>(null)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    try {
      setSent(await forgotPassword(email.trim()))
    } catch {
      // Shows the same confirmation as a success, on purpose. The server already answers
      // identically for a known and an unknown address so this form cannot be used to find out
      // who has an account; surfacing a failure only here would rebuild that oracle out of the
      // error path - "your address failed differently" is the same answer.
      setSent(t('auth.reset_sent'))
    } finally {
      setBusy(false)
    }
  }

  if (sent) {
    return (
      <>
        <Header title={t('forgot.title')} description={sent} />
        <Button variant="secondary" size="md" className="mt-8 w-full" onClick={onBack}>
          {t('login.back')}
        </Button>
      </>
    )
  }

  return (
    <>
      <Header title={t('forgot.title')} description={t('forgot.description')} />
      <Card onSubmit={submit}>
        <Field
          id="forgot-email"
          label={t('login.email')}
          type="email"
          value={email}
          autoComplete="username"
          autoFocus
          onChange={setEmail}
        />
        <Button
          type="submit"
          variant="primary"
          size="md"
          loading={busy}
          disabled={!email.trim()}
          className="mt-6 w-full"
        >
          {busy ? t('forgot.pending') : t('forgot.submit')}
        </Button>
        <LinkButton onClick={onBack}>{t('login.back')}</LinkButton>
      </Card>
    </>
  )
}
