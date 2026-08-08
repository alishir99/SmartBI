
import { beforeEach } from 'vitest'
import { useLanguageStore } from './lib/i18n'

beforeEach(() => {
  useLanguageStore.setState({ lang: 'sv' })
})
