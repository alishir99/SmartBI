/** Shared by the reset page and the change-password panel so the two forms cannot drift on
 * what a valid password is - the shown minimum comes from /api/config, the server's own rule. */

import { passwordMinLength } from '../lib/config'
import { t } from '../lib/i18n'
import { Field } from './Field'

export type NewPassword = { password: string; repeat: string }

export const EMPTY_PASSWORD: NewPassword = { password: '', repeat: '' }

/** Why the pair isn't submittable yet, or null - a reason, not a boolean, so the caller shows
 * the specific problem. Silent about a mismatch while the user is still typing the repeat. */
export function passwordProblem(value: NewPassword, touched: boolean): string | null {
  const min = passwordMinLength()
  if (value.password.length < min) {
    return value.password && touched ? t('password.too_short', { min }) : null
  }
  if (value.repeat && value.password !== value.repeat) return t('password.mismatch')
  return null
}

export function passwordReady(value: NewPassword): boolean {
  return (
    value.password.length >= passwordMinLength() && value.password === value.repeat
  )
}

export function NewPasswordFields({
  value,
  onChange,
  idPrefix,
  autoFocus = false,
}: {
  value: NewPassword
  onChange: (next: NewPassword) => void
  /** Distinguishes the two forms' inputs when both exist in one document. */
  idPrefix: string
  autoFocus?: boolean
}) {
  return (
    <>
      <Field
        id={`${idPrefix}-new`}
        label={t('password.new')}
        type="password"
        value={value.password}
        // Tells a password manager to offer a generated one and to store what is typed.
        autoComplete="new-password"
        autoFocus={autoFocus}
        hint={t('password.rule', { min: passwordMinLength() })}
        onChange={(password) => onChange({ ...value, password })}
      />
      <div className="mt-4">
        <Field
          id={`${idPrefix}-repeat`}
          label={t('password.repeat')}
          type="password"
          value={value.repeat}
          autoComplete="new-password"
          onChange={(repeat) => onChange({ ...value, repeat })}
        />
      </div>
    </>
  )
}
