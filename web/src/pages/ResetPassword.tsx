/** Redeeming a reset link. Outside the auth gate, like the share page: whoever opens this
 * cannot log in, which is the whole reason they're here - everything it needs is in the token. */

import { useState, type FormEvent } from 'react'
import { resetPassword } from '../lib/api'
import { useT } from '../lib/i18n'
import { Button } from '../components/Button'
import {
  EMPTY_PASSWORD,
  NewPasswordFields,
  passwordProblem,
  passwordReady,
} from '../components/NewPasswordFields'

export function ResetPasswordPage({ token }: { token: string }) {
  const t = useT()
  const [value, setValue] = useState(EMPTY_PASSWORD)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)

  const problem = passwordProblem(value, Boolean(value.repeat))

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await resetPassword(token, value.password)
      setDone(true)
    } catch (caught) {
      // The server's message says "invalid or already used" without saying which - expired,
      // spent and forged are only distinguishable to someone who didn't get the mail.
      setError(caught instanceof Error ? caught.message : t('auth.reset_invalid'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-page px-5 py-10">
      <div className="animate-fade-up w-full max-w-sm">
        <div className="text-center">
          <h1 className="text-2xl font-semibold tracking-tight text-ink">
            {done ? t('reset.done_title') : t('reset.title')}
          </h1>
          <p className="mt-2 text-sm text-ink-secondary">
            {done ? t('reset.done') : t('reset.description')}
          </p>
        </div>

        {done ? (
          <Button
            variant="primary"
            size="md"
            className="mt-8 w-full"
            // A full reload rather than a hash change: it drops the spent token out of the
            // address bar and remounts the app at the login screen.
            onClick={() => {
              window.location.hash = '#/overview'
              window.location.reload()
            }}
          >
            {t('reset.to_login')}
          </Button>
        ) : (
          <form
            onSubmit={submit}
            className="mt-8 rounded-card bg-surface p-6 shadow-card ring-hairline"
          >
            <NewPasswordFields value={value} onChange={setValue} idPrefix="reset" autoFocus />

            {(problem || error) && (
              <p role="alert" className="mt-4 text-xs text-neg">
                {problem ?? error}
              </p>
            )}

            <Button
              type="submit"
              variant="primary"
              size="md"
              loading={busy}
              disabled={!passwordReady(value)}
              className="mt-6 w-full"
            >
              {busy ? t('reset.pending') : t('reset.submit')}
            </Button>
          </form>
        )}
      </div>
    </div>
  )
}
