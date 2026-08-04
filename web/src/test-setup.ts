/**
 * Test defaults: Swedish, SEK, sv-SE.
 *
 * The language store reads `navigator.language`, which is `en-US` under jsdom - so without
 * this every existing suite would suddenly be asserting against English strings and a comma
 * decimal separator, and would be measuring the test environment rather than the code. Pinning
 * it makes the language an explicit choice: a test about English says so.
 */

import { beforeEach } from 'vitest'
import { useLanguageStore } from './lib/i18n'

beforeEach(() => {
  useLanguageStore.setState({ lang: 'sv' })
})
