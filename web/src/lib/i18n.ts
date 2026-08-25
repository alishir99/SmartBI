/** A plain lookup table, not i18next: two languages and ~150 strings don't need lazy
 * namespaces or an interpolation DSL. `MEASURE_LABELS` translates by key because the
 * semantic layer's own `label` is monolingual by design (a data contract, not a UI one). */

import { create } from 'zustand'

export type Language = 'sv' | 'en'

export const LANGUAGES: Language[] = ['sv', 'en']

export const LANGUAGE_NAMES: Record<Language, string> = { sv: 'Svenska', en: 'English' }

const LANGUAGE_KEY = 'smartbi.lang'

function isLanguage(value: unknown): value is Language {
  return LANGUAGES.includes(value as Language)
}

function readStoredLanguage(): Language {
  try {
    const stored = localStorage.getItem(LANGUAGE_KEY)
    if (isLanguage(stored)) return stored
  } catch {
    /* private browsing */
  }
  for (const tag of navigator.languages ?? [navigator.language]) {
    const base = tag?.split('-')[0]
    if (isLanguage(base)) return base
  }
  return 'sv'
}

type LanguageState = { lang: Language; setLanguage: (lang: Language) => void }

export const useLanguageStore = create<LanguageState>((set) => ({
  lang: readStoredLanguage(),
  setLanguage: (lang) => {
    try {
      localStorage.setItem(LANGUAGE_KEY, lang)
    } catch {
      /* private browsing */
    }
    // The <html lang> attribute is what a screen reader reads pronunciation from, and it's
    // wrong on every page the moment the switcher is used.
    document.documentElement.lang = lang
    set({ lang })
  },
}))

/** Readable outside React - format.ts and tooltext.ts run from render paths that aren't
 * components, so a hook can't reach them; this reads the same value the hook would return. */
export function currentLanguage(): Language {
  return useLanguageStore.getState().lang
}

export function t(key: string, params?: Record<string, string | number>): string {
  const table = STRINGS[currentLanguage()]
  const template = table[key] ?? STRINGS.sv[key] ?? key
  if (!params) return template
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole,
  )
}

/** A hook, so a component re-renders on language change - `t` alone reads the store without
 * subscribing, right for a chart formatter but wrong for a heading. */
export function useT(): typeof t {
  useLanguageStore((state) => state.lang)
  return t
}

/** `1 produkt` / `2 produkter`, via the language's own plural rules. */
export function plural(count: number, key: string): string {
  const rule = new Intl.PluralRules(currentLanguage()).select(count)
  return t(`${key}.${rule}`, { count })
}


/** Measures and dimensions by their semantic-layer key. Falls back to the server's label, so
 * an unrecognised or derived column still reads as something. */
export function columnLabel(key: string, fallback: string): string {
  // Derived columns are a base key plus a suffix the compiler owns - translating the base and
  // re-applying the suffix means one entry per measure, not one per measure × suffix.
  const derived = /^(.*?)(_compare|_delta_pct|_delta_pe|_delta|_ma)$/.exec(key)
  if (derived) {
    const base = MEASURE_LABELS[derived[1]]
    if (base) return `${t(base)} ${t(`column${derived[2]}`)}`
    return fallback
  }
  const label = MEASURE_LABELS[key]
  return label ? t(label) : fallback
}

const MEASURE_LABELS: Record<string, string> = {
  net_sales_sek: 'measure.net_sales',
  gross_sales_sek: 'measure.gross_sales',
  discount_sek: 'measure.discount',
  units: 'measure.units',
  avg_price_sek: 'measure.avg_price',
  discount_rate: 'measure.discount_rate',
  orders: 'measure.orders',
  own_net_sek: 'measure.own_net',
  category_net_sek: 'measure.category_net',
  share_pct: 'measure.share_pct',
  rank: 'measure.rank',
  n_brands: 'measure.n_brands',
  day: 'dimension.day',
  week: 'dimension.week',
  month: 'dimension.month',
  quarter: 'dimension.quarter',
  year: 'dimension.year',
  product: 'dimension.product',
  brand: 'dimension.brand',
  subcategory: 'dimension.subcategory',
  category: 'dimension.category',
  region: 'dimension.region',
  channel: 'dimension.channel',
  store: 'dimension.store',
  city: 'dimension.city',
  customer_segment: 'dimension.customer_segment',
  loyalty_tier: 'dimension.loyalty_tier',
  month_of_year: 'dimension.month_of_year',
  weekday: 'dimension.weekday',
  is_holiday: 'dimension.is_holiday',
  campaign_id: 'dimension.campaign',
}


type Table = Record<string, string>

const sv: Table = {
  'unit.count': 'st',
  'unit.percentage_points': 'p.e.',
  // Spelled out, for prose: "1,2 p.e." mid-sentence reads as a chip that fell out of a tile.
  'unit.percentage_points_long': 'procentenheter',
  'unit.percent': '%',
  'value.missing': '–',

  column_compare: '(jämförelse)',
  column_delta: '(förändring)',
  column_delta_pct: '(förändring %)',
  column_delta_pe: '(förändring p.e.)',
  column_ma: '(glidande medel)',
  'measure.net_sales': 'Nettoförsäljning',
  'measure.gross_sales': 'Bruttoförsäljning',
  'measure.discount': 'Rabatt',
  'measure.units': 'Sålda enheter',
  'measure.avg_price': 'Snittpris',
  'measure.discount_rate': 'Rabattgrad',
  'measure.orders': 'Antal köp',
  'measure.own_net': 'Egen försäljning',
  'measure.category_net': 'Kategorin totalt',
  'measure.share_pct': 'Andel',
  'measure.rank': 'Placering',
  'measure.n_brands': 'Antal varumärken',
  'dimension.day': 'Dag',
  'dimension.week': 'Vecka',
  'dimension.month': 'Månad',
  'dimension.quarter': 'Kvartal',
  'dimension.year': 'År',
  'dimension.product': 'Produkt',
  'dimension.brand': 'Varumärke',
  'dimension.subcategory': 'Underkategori',
  'dimension.category': 'Kategori',
  'dimension.region': 'Region',
  'dimension.channel': 'Kanal',
  'dimension.store': 'Butik',
  'dimension.city': 'Stad',
  'dimension.customer_segment': 'Kundsegment',
  'dimension.loyalty_tier': 'Lojalitetsnivå',
  'dimension.month_of_year': 'Månad på året',
  'dimension.weekday': 'Veckodag',
  'dimension.is_holiday': 'Dagtyp',
  'dimension.campaign': 'Kampanj',

  'nav.overview': 'Översikt',
  'nav.products': 'Produkter',
  'nav.geography': 'Geografi',
  'nav.saved': 'Mina vyer',
  'shell.ask': 'Fråga datan',
  'shell.resize_chat': 'Ändra chattens bredd',
  'shell.sign_out': 'Logga ut',
  'shell.language': 'Språk',
  'shell.close': 'Stäng',
  'shell.menu': 'Huvudmeny',
  'role.supplier_viewer': 'Leverantör · läsare',
  'role.supplier_admin': 'Leverantör · administratör',
  'role.retail_analyst': 'Analytiker',
  'role.system_admin': 'Systemadministratör',
  'theme.light': 'Ljust läge',
  'theme.dark': 'Mörkt läge',
  'theme.system': 'Följer systemet',

  'period.last_7_days': 'Senaste veckan',
  'period.last_7_days.short': 'Vecka',
  'period.last_30_days': 'Senaste 30 dagarna',
  'period.last_30_days.short': '30 dgr',
  'period.last_90_days': 'Senaste kvartalet',
  'period.last_90_days.short': 'Kvartal',
  'period.last_month': 'Förra månaden',
  'period.last_month.short': 'Månad',
  'period.ytd': 'Hittills i år',
  'period.ytd.short': 'I år',
  'period.last_12_months': 'Senaste 12 mån',
  'period.last_12_months.short': '12 mån',
  'period.all_time': 'Hela perioden',
  'period.all_time.short': 'Allt',
  'period.previous': 'vs föregående period',

  'login.title': 'SmartBI Insights',
  'login.subtitle': 'Din försäljning hos handlaren, utan omvägar.',
  'login.email': 'E-post',
  'login.password': 'Lösenord',
  'login.submit': 'Logga in',
  'login.pending': 'Loggar in…',
  'login.forgot': 'Glömt lösenordet?',
  'login.back': 'Tillbaka till inloggning',

  'forgot.title': 'Återställ lösenord',
  'forgot.description':
    'Skriv adressen du loggar in med, så skickar vi en länk för att välja ett nytt lösenord.',
  'forgot.submit': 'Skicka återställningslänk',
  'forgot.pending': 'Skickar…',
  'reset.title': 'Välj ett nytt lösenord',
  'reset.description': 'Länken gäller en gång. Efter det loggar du in med det nya lösenordet.',
  'reset.submit': 'Spara lösenordet',
  'reset.pending': 'Sparar…',
  'reset.done_title': 'Lösenordet är ändrat',
  'reset.done': 'Du kan nu logga in med ditt nya lösenord.',
  'reset.to_login': 'Till inloggningen',

  'password.change': 'Byt lösenord',
  'password.current': 'Nuvarande lösenord',
  'password.new': 'Nytt lösenord',
  'password.repeat': 'Upprepa nytt lösenord',
  'password.save': 'Spara',
  'password.saving': 'Sparar…',
  'password.saved': 'Lösenordet är ändrat.',
  'password.mismatch': 'Lösenorden stämmer inte överens.',
  'password.too_short': 'Lösenordet måste vara minst {min} tecken.',
  'password.cancel': 'Avbryt',
  'password.rule': 'Minst {min} tecken. Längd skyddar bättre än specialtecken.',
  'login.failed': 'Inloggningen misslyckades.',
  'login.demo_hint': 'Demokonton finns i repots README.',
  'shared.eyebrow': 'Delad vy · SmartBI Insights',
  'shared.title': 'Delad vy',
  'shared.by':
    'Delad av {name}. Siffrorna hämtas färskt ur {name}s data varje gång länken öppnas, under deras behörighet - aldrig under din.',
  'shared.expires': 'Länken slutar fungera {date}.',
  'shared.footer':
    'SmartBI Insights - färdiga svar om försäljningen, direkt ur handlarens data.',

  'overview.title': 'Översikt',
  'overview.description': 'Din försäljning hos handlaren, mot perioden dessförinnan.',
  'products.title': 'Produkter',
  'products.description': 'Vad som rör sig mest upp och ned mot föregående period.',
  'geography.title': 'Geografi',
  'geography.description':
    'Försäljning per region. Rangordningen är det man läser av - kartan visar var efterfrågan ligger.',
  'geography.tab_ranking': 'Rangordning',
  'geography.tab_map': 'Karta',
  'geography.tab_group': 'Vy',
  'geography.empty_title': 'Ingen regional vy tillgänglig',
  'geography.map_unavailable_title': 'Kartan kan inte ritas för den här datan',
  'geography.map_unavailable':
    'Kartan behöver koordinater per region, och den här datakällan har inga. Rangordningen visar samma siffror.',
  'geography.result_error_title': 'Kunde inte läsa resultatet',
  'geography.result_error': 'Kartan ritas från samma resultat som stapeldiagrammet.',
  'saved.title': 'Mina vyer',
  'saved.description': 'Sparade kort körs om mot färsk data varje gång du öppnar dem.',
  'saved.empty_title': 'Inga sparade vyer än',
  'saved.empty':
    'Fäst ett kort från översikten eller från ett chattsvar, så hamnar det här.',
  'page.ask_more': 'Fråga vidare',
  'page.no_view_title': 'Ingen färdig vy för den här dimensionen',
  'page.no_view': 'Fråga i chatten så byggs vyn från din data.',
  'page.data_through': 'data t.o.m. {date}',

  'chat.title': 'Fråga datan',
  'chat.subtitle': 'Svar direkt ur din försäljningsdata',
  'chat.placeholder': 'Fråga om din försäljning…',
  'chat.send': 'Skicka',
  'chat.thinking': 'Tänker…',
  'chat.pipeline': 'Så hanteras frågan',
  'chat.step_llm': 'Modellen tolkar frågan och väljer verktyg',
  'chat.step_mcp': 'Anropet går genom MCP-servern',
  'chat.step_db': 'Databasen körs mot din behörighet',
  'chat.step_done': ' - klart',
  'chat.step_active': ' - pågår',
  'chat.aborted': 'Svaret avbröts innan något kort hade skapats.',
  'chat.unexpected': 'Ett oväntat fel inträffade.',
  'chat.no_stream': 'Svaret innehöll ingen ström.',
  'chat.clear': 'Rensa',
  'chat.close': 'Stäng',
  'chat.stop': 'Avbryt',
  'chat.input_label': 'Ställ en fråga om din försäljning',
  'chat.welcome':
    'Ställ frågan på svenska. Varje svar kommer med ett diagram som ritas ur raderna frågan hämtade - aldrig ur en siffra modellen hittat på.',
  'chat.try': 'Prova',
  'chat.step_mcp_back': 'Raderna kommer tillbaka genom MCP',
  'chat.step_llm_writes': 'Modellen formulerar svaret ur raderna',
  'chat.flow_done': 'svaret kommer från raderna, inte från modellens minne',

  'card.clarify': 'Behöver en precisering',
  'card.cannot_answer': 'Det här har jag inte underlag för',
  'card.can_answer': 'Det här kan jag svara på',
  'card.no_chart': 'Inget diagram för det här svaret.',
  'card.answer': 'Svar',
  'card.explain': 'Om diagrammet',
  'card.did_you_mean': 'Menade du',
  'card.preview': 'Preliminärt - första resultatet i turen, svaret kan hämta fler',
  'card.validation_failed':
    'Svarstexten kunde inte verifieras mot datan och har därför utelämnats. Diagrammet nedan kommer direkt från databasen.',
  'card.chart_data_failed': 'Kunde inte hämta underlaget till diagrammet.',
  'card.truncated':
    'Visar de första {shown} raderna av {total}. Hela underlaget finns i CSV-exporten.',
  'card.retry': 'Försök igen',
  'card.view_mode': 'Visningsläge',
  'card.view_chart': 'Diagram',
  'card.view_table': 'Tabell',
  'card.export_csv': 'Exportera som CSV',
  'card.save': 'Spara i Mina vyer',
  'card.saved': 'Sparad i Mina vyer',
  'card.delete': 'Ta bort sparad vy',
  'card.share': 'Dela',
  'card.share_note':
    'Körs om mot färsk data vid varje öppning - alltid under din behörighet, aldrig läsarens. Slutar gälla automatiskt.',
  'card.share_copy': 'Kopiera länk',
  'card.share_copied': 'Kopierad',
  'card.share_failed': 'Kunde inte skapa länken. Försök igen.',
  'card.no_comparison': 'Ingen jämförelseperiod',
  'card.other': 'Övrigt',
  'card.other_note': 'mindre poster är summerade till Övrigt',
  'chart.folded_note': 'Mindre poster är summerade till “{other}”.',
  'card.no_regional_data': 'Ingen regional data i det här resultatet.',
  'card.map_caption': '{label} per region · {unit} · cirkelns yta står i proportion till värdet',
  'card.map_title': '{label} per region',
  'card.map_share': '{percent} av perioden',
  'card.subtitle_vat': '{period} · nettoförsäljning, {vat}',
  'value.one': '{count} värde',
  'value.other': '{count} värden',

  'source.plural': 'Källor',
  'source.singular': 'Källa',
  'source.own_sales': 'Din egen försäljning',
  'source.market_share': 'Din försäljning och kategorins totaler',
  'source.compare_period': 'Jämförelseperiod',
  'source.coverage': 'Datatäckning',
  'source.currency': 'Valuta',
  'source.fetched': 'Hämtat',
  'source.claims': 'Siffror i texten som kommer härifrån',
  'source.fetches': '{count} hämtningar',
  'source.explainer':
    'Talen i svaret kommer härifrån. Språkmodellen väljer vilken fråga som ställs och hur svaret formuleras, men värdena hämtas ur din data och räknas fram innan texten skrivs.',
  'source.is_charted': 'Diagrammet ritas från den här',
  'source.basis': 'Underlag',
  'source.period': 'Period',
  'source.rows': 'Rader',
  'source.rows_count': '{count} rader',
  'source.truncated': ' (trunkerad)',
  'source.selection': 'Urval',
  'vat.excl': 'exkl. moms',
  'vat.incl': 'inkl. moms',

  'tool.get_capabilities': 'Datakatalog',
  'tool.resolve_entities': 'Uppslag',
  'tool.query_sales': 'Försäljning',
  'tool.query_market_share': 'Marknadsandel',
  'tool.dashboard': 'Översikt',
  'tool.doing.capabilities': 'läser vad datan innehåller',
  'tool.doing.resolve': 'slår upp "{text}"',
  'tool.doing.resolve_generic': 'slår upp entiteter',
  'tool.doing.market_share': 'hämtar andel av kategori',
  'tool.doing.sales': 'hämtar försäljning',
  'tool.doing.scoped': 'hämtar {grain} i {scope}',
  'tool.doing.scope_only': 'hämtar {scope}',
  'tool.doing.grain_only': 'hämtar {grain}',
  'tool.per': 'per {dimension}',
  'channel.online': 'onlinekanalen',
  'channel.physical': 'fysiska butiker',

  'filter.region': 'Region',
  'filter.channel': 'Kanal',
  'filter.category': 'Kategori',
  'filter.category_ids.one': '{count} kategori',
  'filter.category_ids.other': '{count} kategorier',
  'filter.product_ids.one': '{count} produkt',
  'filter.product_ids.other': '{count} produkter',
  'filter.brand_ids.one': '{count} varumärke',
  'filter.brand_ids.other': '{count} varumärken',
  'filter.store_ids.one': '{count} butik',
  'filter.store_ids.other': '{count} butiker',

  'error.generic': 'Något gick fel när datan skulle hämtas.',
  'error.expired': 'Sessionen har gått ut. Logga in igen.',
  'error.forbidden': 'Du har inte åtkomst till den här datan.',

  'ask.grew_fastest': 'Var växer vi snabbast jämfört med förra året?',
  'ask.weekly_in_region': 'Visa försäljning per vecka per region',
  'ask.best_online': 'Vilka regioner säljer mest online?',
  'ask.category_share_region': 'Hur stor är vår andel av kategorin i den största regionen?',
  'ask.why_falling': 'Varför tappar produkten som backar mest?',
  'ask.online_vs_store': 'Vilka produkter säljer bäst online jämfört med i butik?',
  'ask.top_products': 'Visa topp 10 produkter',
  'ask.highest_avg_price': 'Vilken produkt har högst snittpris?',
  'ask.best_sellers': 'Vilka produkter säljer bäst?',
  'ask.monthly_trend': 'Hur har försäljningen utvecklats per månad?',
  'ask.margin': 'Vad är vår marginal?',
  'ask.tell_me_more': 'Berätta mer om den här perioden.',
  'ask.what_happened': 'Vad hände i {period}?',
  'ask.tell_me_about': 'Berätta mer om {subject}.',
  'ask.what_drove': 'Vad ligger bakom {subject} på {value} den här perioden?',
  'ask.why_changed': 'Varför {direction} {measure} {magnitude}{comparison}?',
  'ask.rose': 'ökade',
  'ask.fell': 'minskade',
  'ask.compared_with': ' jämfört med {period}',
  'ask.measure.net_sales_sek': 'försäljningen',
  'ask.measure.category_share_pct': 'andelen av kategorin',
  'ask.measure.units': 'antalet sålda enheter',
  'ask.measure.avg_price_sek': 'snittpriset',
}

const en: Table = {
  'unit.count': 'pcs',
  'unit.percentage_points': 'pp',
  'unit.percentage_points_long': 'percentage points',
  'unit.percent': '%',
  'value.missing': '–',

  column_compare: '(comparison)',
  column_delta: '(change)',
  column_delta_pct: '(change %)',
  column_delta_pe: '(change pp)',
  column_ma: '(moving average)',
  'measure.net_sales': 'Net sales',
  'measure.gross_sales': 'Gross sales',
  'measure.discount': 'Discount',
  'measure.units': 'Units sold',
  'measure.avg_price': 'Average price',
  'measure.discount_rate': 'Discount rate',
  'measure.orders': 'Orders',
  'measure.own_net': 'Your sales',
  'measure.category_net': 'Category total',
  'measure.share_pct': 'Share',
  'measure.rank': 'Rank',
  'measure.n_brands': 'Brands',
  'dimension.day': 'Day',
  'dimension.week': 'Week',
  'dimension.month': 'Month',
  'dimension.quarter': 'Quarter',
  'dimension.year': 'Year',
  'dimension.product': 'Product',
  'dimension.brand': 'Brand',
  'dimension.subcategory': 'Subcategory',
  'dimension.category': 'Category',
  'dimension.region': 'Region',
  'dimension.channel': 'Channel',
  'dimension.store': 'Store',
  'dimension.city': 'City',
  'dimension.customer_segment': 'Customer segment',
  'dimension.loyalty_tier': 'Loyalty tier',
  'dimension.month_of_year': 'Month of year',
  'dimension.weekday': 'Weekday',
  'dimension.is_holiday': 'Day type',
  'dimension.campaign': 'Campaign',

  'nav.overview': 'Overview',
  'nav.products': 'Products',
  'nav.geography': 'Geography',
  'nav.saved': 'Saved views',
  'shell.ask': 'Ask the data',
  'shell.resize_chat': 'Resize the chat panel',
  'shell.sign_out': 'Sign out',
  'shell.language': 'Language',
  'shell.close': 'Close',
  'shell.menu': 'Main menu',
  'role.supplier_viewer': 'Supplier · viewer',
  'role.supplier_admin': 'Supplier · admin',
  'role.retail_analyst': 'Analyst',
  'role.system_admin': 'System admin',
  'theme.light': 'Light',
  'theme.dark': 'Dark',
  'theme.system': 'Match system',

  'period.last_7_days': 'Last 7 days',
  'period.last_7_days.short': 'Week',
  'period.last_30_days': 'Last 30 days',
  'period.last_30_days.short': '30 days',
  'period.last_90_days': 'Last quarter',
  'period.last_90_days.short': 'Quarter',
  'period.last_month': 'Last month',
  'period.last_month.short': 'Month',
  'period.ytd': 'Year to date',
  'period.ytd.short': 'YTD',
  'period.last_12_months': 'Last 12 months',
  'period.last_12_months.short': '12 months',
  'period.all_time': 'All time',
  'period.all_time.short': 'All',
  'period.previous': 'vs previous period',

  'login.title': 'SmartBI Insights',
  'login.subtitle': 'Your sales at the retailer, without the detours.',
  'login.email': 'Email',
  'login.password': 'Password',
  'login.submit': 'Sign in',
  'login.pending': 'Signing in…',
  'login.forgot': 'Forgot your password?',
  'login.back': 'Back to sign in',

  'forgot.title': 'Reset your password',
  'forgot.description':
    'Enter the address you sign in with and we will send a link to choose a new password.',
  'forgot.submit': 'Send reset link',
  'forgot.pending': 'Sending…',
  'reset.title': 'Choose a new password',
  'reset.description':
    'This link works once. After that, sign in with your new password.',
  'reset.submit': 'Save password',
  'reset.pending': 'Saving…',
  'reset.done_title': 'Your password has been changed',
  'reset.done': 'You can now sign in with your new password.',
  'reset.to_login': 'Go to sign in',

  'password.change': 'Change password',
  'password.current': 'Current password',
  'password.new': 'New password',
  'password.repeat': 'Repeat new password',
  'password.save': 'Save',
  'password.saving': 'Saving…',
  'password.saved': 'Your password has been changed.',
  'password.mismatch': 'The passwords do not match.',
  'password.too_short': 'Password must be at least {min} characters.',
  'password.cancel': 'Cancel',
  'password.rule': 'At least {min} characters. Length protects better than special characters.',
  'login.failed': 'Sign-in failed.',
  'login.demo_hint': 'Demo accounts are in the repository README.',
  'shared.eyebrow': 'Shared view · SmartBI Insights',
  'shared.title': 'Shared view',
  'shared.by':
    'Shared by {name}. The figures are read fresh from {name}’s data every time the link is opened, under their permissions - never under yours.',
  'shared.expires': 'The link stops working on {date}.',
  'shared.footer':
    'SmartBI Insights - ready answers about your sales, straight from the retailer’s data.',

  'overview.title': 'Overview',
  'overview.description': 'Your sales at the retailer, against the period before.',
  'products.title': 'Products',
  'products.description': 'What moved most, up and down, against the previous period.',
  'geography.title': 'Geography',
  'geography.description':
    'Sales by region. The ranking is what you read off - the map shows where demand sits.',
  'geography.tab_ranking': 'Ranking',
  'geography.tab_map': 'Map',
  'geography.tab_group': 'View',
  'geography.empty_title': 'No regional view available',
  'geography.map_unavailable_title': 'The map cannot be drawn for this data',
  'geography.map_unavailable':
    'The map needs coordinates per region, and this data source has none. The ranking shows the same figures.',
  'geography.result_error_title': 'Could not read the result',
  'geography.result_error': 'The map is drawn from the same result as the bar chart.',
  'saved.title': 'Saved views',
  'saved.description': 'Saved cards are re-run against fresh data every time you open them.',
  'saved.empty_title': 'No saved views yet',
  'saved.empty': 'Pin a card from the overview or from a chat answer and it lands here.',
  'page.ask_more': 'Ask more',
  'page.no_view_title': 'No ready-made view for this dimension',
  'page.no_view': 'Ask in the chat and the view is built from your data.',
  'page.data_through': 'data through {date}',

  'chat.title': 'Ask the data',
  'chat.subtitle': 'Answers straight from your sales data',
  'chat.placeholder': 'Ask about your sales…',
  'chat.send': 'Send',
  'chat.thinking': 'Thinking…',
  'chat.pipeline': 'How the question is handled',
  'chat.step_llm': 'The model reads the question and picks tools',
  'chat.step_mcp': 'The call goes through the MCP server',
  'chat.step_db': 'The database runs under your permissions',
  'chat.step_done': ' - done',
  'chat.step_active': ' - running',
  'chat.aborted': 'The answer was cut off before a card had been created.',
  'chat.unexpected': 'Something unexpected went wrong.',
  'chat.no_stream': 'The response carried no stream.',
  'chat.clear': 'Clear',
  'chat.close': 'Close',
  'chat.stop': 'Stop',
  'chat.input_label': 'Ask a question about your sales',
  'chat.welcome':
    'Ask in plain English. Every answer comes with a chart drawn from the rows the question fetched - never from a figure the model made up.',
  'chat.try': 'Try',
  'chat.step_mcp_back': 'The rows come back through MCP',
  'chat.step_llm_writes': 'The model writes the answer from the rows',
  'chat.flow_done': 'the answer comes from the rows, not from the model’s memory',

  'card.clarify': 'Needs narrowing down',
  'card.cannot_answer': "I have no basis for this",
  'card.can_answer': 'Here is what I can answer',
  'card.no_chart': 'No chart for this answer.',
  'card.answer': 'Answer',
  'card.explain': 'About the chart',
  'card.did_you_mean': 'Did you mean',
  'card.preview': 'Preliminary - the first result in the turn, the answer may fetch more',
  'card.validation_failed':
    'The answer text could not be verified against the data and has therefore been withheld. The chart below comes straight from the database.',
  'card.chart_data_failed': 'Could not load the data behind the chart.',
  'card.truncated':
    'Showing the first {shown} rows of {total}. The full result is in the CSV export.',
  'card.retry': 'Try again',
  'card.view_mode': 'View mode',
  'card.view_chart': 'Chart',
  'card.view_table': 'Table',
  'card.export_csv': 'Export as CSV',
  'card.save': 'Save to Saved views',
  'card.saved': 'Saved to Saved views',
  'card.delete': 'Delete saved view',
  'card.share': 'Share',
  'card.share_note':
    'Re-run against fresh data on every open - always under your permissions, never the reader’s. Expires automatically.',
  'card.share_copy': 'Copy link',
  'card.share_copied': 'Copied',
  'card.share_failed': 'Could not create the link. Try again.',
  'card.no_comparison': 'No comparison period',
  'card.other': 'Other',
  'card.other_note': 'smaller entries are summed into Other',
  'chart.folded_note': 'Smaller entries are summed into “{other}”.',
  'card.no_regional_data': 'No regional data in this result.',
  'card.map_caption': '{label} by region · {unit} · circle area is proportional to the value',
  'card.map_title': '{label} by region',
  'card.map_share': '{percent} of the period',
  'card.subtitle_vat': '{period} · net sales, {vat}',
  'value.one': '{count} value',
  'value.other': '{count} values',

  'source.plural': 'Sources',
  'source.singular': 'Source',
  'source.own_sales': 'Your own sales',
  'source.market_share': 'Your sales and the category totals',
  'source.compare_period': 'Comparison period',
  'source.coverage': 'Data coverage',
  'source.currency': 'Currency',
  'source.fetched': 'Fetched',
  'source.claims': 'Figures in the text that come from here',
  'source.fetches': '{count} fetches',
  'source.explainer':
    'The figures in the answer come from here. The language model picks which question is asked and how the answer is worded, but the values are read from your data and computed before the text is written.',
  'source.is_charted': 'The chart is drawn from this one',
  'source.basis': 'Basis',
  'source.period': 'Period',
  'source.rows': 'Rows',
  'source.rows_count': '{count} rows',
  'source.truncated': ' (truncated)',
  'source.selection': 'Selection',
  'vat.excl': 'excl. VAT',
  'vat.incl': 'incl. VAT',

  'tool.get_capabilities': 'Data catalogue',
  'tool.resolve_entities': 'Lookup',
  'tool.query_sales': 'Sales',
  'tool.query_market_share': 'Market share',
  'tool.dashboard': 'Overview',
  'tool.doing.capabilities': 'reading what the data holds',
  'tool.doing.resolve': 'looking up "{text}"',
  'tool.doing.resolve_generic': 'looking up entities',
  'tool.doing.market_share': 'fetching category share',
  'tool.doing.sales': 'fetching sales',
  'tool.doing.scoped': 'fetching {grain} in {scope}',
  'tool.doing.scope_only': 'fetching {scope}',
  'tool.doing.grain_only': 'fetching {grain}',
  'tool.per': 'by {dimension}',
  'channel.online': 'the online channel',
  'channel.physical': 'physical stores',

  'filter.region': 'Region',
  'filter.channel': 'Channel',
  'filter.category': 'Category',
  'filter.category_ids.one': '{count} category',
  'filter.category_ids.other': '{count} categories',
  'filter.product_ids.one': '{count} product',
  'filter.product_ids.other': '{count} products',
  'filter.brand_ids.one': '{count} brand',
  'filter.brand_ids.other': '{count} brands',
  'filter.store_ids.one': '{count} store',
  'filter.store_ids.other': '{count} stores',

  'error.generic': 'Something went wrong while fetching the data.',
  'error.expired': 'Your session has expired. Sign in again.',
  'error.forbidden': 'You do not have access to this data.',

  'ask.grew_fastest': 'Where are we growing fastest compared with last year?',
  'ask.weekly_in_region': 'Show weekly sales by region',
  'ask.best_online': 'Which regions sell the most online?',
  'ask.category_share_region': 'What is our category share in the largest region?',
  'ask.why_falling': 'Why is the worst-performing product falling?',
  'ask.online_vs_store': 'Which products sell best online compared with in store?',
  'ask.top_products': 'Show the top 10 products',
  'ask.highest_avg_price': 'Which product has the highest average price?',
  'ask.best_sellers': 'Which products sell best?',
  'ask.monthly_trend': 'How have sales developed month by month?',
  'ask.margin': 'What is our margin?',
  'ask.tell_me_more': 'Tell me more about this period.',
  'ask.what_happened': 'What happened in {period}?',
  'ask.tell_me_about': 'Tell me more about {subject}.',
  'ask.what_drove': 'What is behind {subject} at {value} this period?',
  'ask.why_changed': 'Why did {measure} {direction} {magnitude}{comparison}?',
  'ask.rose': 'rise',
  'ask.fell': 'fall',
  'ask.compared_with': ' compared with {period}',
  'ask.measure.net_sales_sek': 'sales',
  'ask.measure.category_share_pct': 'the category share',
  'ask.measure.units': 'the number of units sold',
  'ask.measure.avg_price_sek': 'the average price',
}

export const STRINGS: Record<Language, Table> = { sv, en }
