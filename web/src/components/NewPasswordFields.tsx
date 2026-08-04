/**
 * "New password" plus "repeat it", and the one rule both places enforce.
 *
 * Shared by the reset page and the change-password panel so the two cannot drift on what a
 * valid password is - and so the minimum length shown is the one the server will actually
 * apply, which is why it comes from `/api/config` rather than from a constant here.
 */

import { passwordMinLength } from '../lib/config'
import { t } from '../lib/i18n'
import { Field } from './Field'

export type NewPassword = { password: string; repeat: string }

export const EMPTY_PASSWORD: NewPassword = { password: '', repeat: '' }

/**
 * Why this pair is not yet submittable, or null when it is.
 *
 * Returns a *reason*, not a boolean, so the caller shows the specific problem rather than a
 * disabled button with no explanation. Silent while the user is still typing the confirmation:
 * "the passwords do not match" under a half-typed second field is noise, not help.
 */
export function passwordProblem(value: NewPassword, touched: boolean): string | null {
  const min = passwordMinLength()
  if (value.password.length < min) {
    return value.password && touched ? t('password.too_short', { min }) : null
  }
  if (value.repeat && value.password !== value.repeat) return t('password.mismatch')
  return null
}

/** True when the pair is complete and consistent - the condition for enabling submit. */
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
