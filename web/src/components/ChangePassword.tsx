
import { useEffect, useState, type FormEvent } from 'react'
import { createPortal } from 'react-dom'
import { changePassword } from '../lib/api'
import { useT } from '../lib/i18n'
import { Button } from './Button'
import { Field } from './Field'
import {
  EMPTY_PASSWORD,
  NewPasswordFields,
  passwordProblem,
  passwordReady,
} from './NewPasswordFields'

export function ChangePassword({ onClose }: { onClose: () => void }) {
  const t = useT()
  const [current, setCurrent] = useState('')
  const [value, setValue] = useState(EMPTY_PASSWORD)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const problem = passwordProblem(value, Boolean(value.repeat))

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await changePassword(current, value.password)
      setSaved(true)
      // Cleared rather than left on screen: a filled password field surviving behind a
      // confirmation is a password sitting on an unlocked laptop.
      setCurrent('')
      setValue(EMPTY_PASSWORD)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t('auth.wrong_current_password'))
    } finally {
      setBusy(false)
    }
  }

  // Portalled to <body>: the trigger sits in a `sticky` sidebar, an ancestor context that clips
  // `fixed` children - the dialog used to render with its lower half cut off.
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center px-5">
      <div
        className="animate-fade-in absolute inset-0 bg-black/30"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="change-password-title"
        className="animate-fade-up relative w-full max-w-sm rounded-card bg-surface p-6 shadow-pop ring-hairline"
      >
        <h2 id="change-password-title" className="text-base font-semibold text-ink">
          {t('password.change')}
        </h2>

        {saved ? (
          <>
            <p className="mt-3 text-sm text-ink-secondary">{t('password.saved')}</p>
            <Button variant="primary" size="md" className="mt-6 w-full" onClick={onClose}>
              {t('shell.close')}
            </Button>
          </>
        ) : (
          <form onSubmit={submit} className="mt-5">
            <Field
              id="pw-current"
              label={t('password.current')}
              type="password"
              value={current}
              autoComplete="current-password"
              autoFocus
              onChange={setCurrent}
            />
            <div className="mt-4">
              <NewPasswordFields value={value} onChange={setValue} idPrefix="pw" />
            </div>

            {(problem || error) && (
              <p role="alert" className="mt-4 text-xs text-neg">
                {problem ?? error}
              </p>
            )}

            <div className="mt-6 flex gap-2">
              <Button variant="secondary" size="md" className="flex-1" onClick={onClose}>
                {t('password.cancel')}
              </Button>
              <Button
                type="submit"
                variant="primary"
                size="md"
                loading={busy}
                disabled={!current || !passwordReady(value)}
                className="flex-1"
              >
                {busy ? t('password.saving') : t('password.save')}
              </Button>
            </div>
          </form>
        )}
      </div>
    </div>,
    document.body,
  )
}
