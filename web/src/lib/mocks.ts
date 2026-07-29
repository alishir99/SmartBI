/**
 * Fixtures matching docs/API_CONTRACT.md exactly, so the UI is demoable and
 * visually verifiable before the API exists. Enabled with VITE_USE_MOCKS=true.
 *
 * Figures reflect the generated dataset: demo tenant Nordström Audio AB,
 * ~3.9 MSEK net sales/month, TVs and laptops at the top, Stockholms län ~36 %,
 * #2 of 6 brands in Hörlurar, coverage 2024-07-01 → 2026-06-30.
 */

import type {
  AnswerCard,
  ChatEvent,
  Column,
  DashboardResponse,
  Kpi,
  LoginResponse,
  Provenance,
  ResultResponse,
  ResultRow,
  SaveCardRequest,
  ShareResponse,
  User,
} from '../types'

const COVERAGE = { from: '2024-07-01', to: '2026-06-30' }
const PERIOD = { from: '2026-01-01', to: '2026-06-30' }
const PERIOD_LY = { from: '2025-01-01', to: '2025-06-30' }
const TRAILING_12 = { from: '2025-07-01', to: '2026-06-30' }
const SCOPE = 'supplier:8f2a'
const EXECUTED_AT = '2026-06-30T14:32:11Z'

// --- users ------------------------------------------------------------------

const NORDSTROM_USER: User = {
  user_id: 12,
  email: 'anna@nordstromaudio.se',
  display_name: 'Anna Bergström',
  role: 'supplier_admin',
  supplier_id: 3,
  supplier_name: 'Nordström Audio AB',
}

const LAGERKVIST_USER: User = {
  user_id: 21,
  email: 'erik@lagerkvisthem.se',
  display_name: 'Erik Lagerkvist',
  role: 'supplier_viewer',
  supplier_id: 7,
  supplier_name: 'Lagerkvist Hem AB',
}

const ACCOUNTS: Record<string, User> = {
  'anna@nordstromaudio.se': NORDSTROM_USER,
  'erik@lagerkvisthem.se': LAGERKVIST_USER,
}

export function mockLogin(email: string, password: string): LoginResponse {
  const user = ACCOUNTS[email.trim().toLowerCase()]
  if (!user || password !== 'demo1234') {
    throw new Error('Fel e-postadress eller lösenord.')
  }
  return { access_token: `mock.${user.user_id}.token`, token_type: 'bearer', user }
}

export function mockMe(token: string): User {
  const id = Number(token.split('.')[1])
  return id === LAGERKVIST_USER.user_id ? LAGERKVIST_USER : NORDSTROM_USER
}

// --- columns ----------------------------------------------------------------

const COL_MONTH: Column = { key: 'month', type: 'date', label: 'Månad' }
const COL_NET: Column = {
  key: 'net_sales_sek',
  type: 'number',
  label: 'Nettoförsäljning',
  unit: 'SEK',
}
const COL_CATEGORY_AVG: Column = {
  key: 'category_avg_sek',
  type: 'number',
  label: 'Kategorisnitt per varumärke',
  unit: 'SEK',
}
const COL_PRODUCT: Column = { key: 'product', type: 'text', label: 'Produkt' }
const COL_UNITS: Column = { key: 'units', type: 'number', label: 'Sålda enheter', unit: 'st' }
const COL_REGION: Column = { key: 'region', type: 'text', label: 'Län' }
const COL_SHARE: Column = { key: 'share_pct', type: 'number', label: 'Andel', unit: '%' }

// --- provenance helper ------------------------------------------------------

function provenance(over: Partial<Provenance>): Provenance {
  return {
    tool: 'query_sales',
    source: 'mv_sales_daily (rollup)',
    scope: SCOPE,
    currency: 'SEK',
    vat: 'exkl. moms',
    time_range: PERIOD,
    compare_range: null,
    coverage: COVERAGE,
    filters_applied: {},
    row_count: 0,
    truncated: false,
    executed_at: EXECUTED_AT,
    tool_args: {},
    ...over,
  }
}

// --- KPIs -------------------------------------------------------------------

const KPIS: Kpi[] = [
  {
    key: 'net_sales_sek',
    label: 'Försäljning',
    value: 23_480_500,
    unit: 'SEK',
    delta_pct: 8.2,
    delta_label: 'vs samma period förra året',
    rank_label: null,
  },
  {
    key: 'category_share_pct',
    label: 'Andel av kategori',
    value: 18.3,
    unit: '%',
    delta_pct: 0.7,
    delta_label: 'vs samma period förra året',
    rank_label: '#2 av 6 varumärken i Hörlurar',
  },
  {
    key: 'units',
    label: 'Sålda enheter',
    value: 18_642,
    unit: 'st',
    delta_pct: 5.4,
    delta_label: 'vs samma period förra året',
    rank_label: null,
  },
  {
    key: 'avg_price_sek',
    label: 'Snittpris',
    value: 1_259,
    unit: 'SEK',
    delta_pct: -2.1,
    delta_label: 'vs samma period förra året',
    rank_label: null,
  },
]

// --- result sets ------------------------------------------------------------

const TREND_ROWS: ResultRow[] = [
  { month: '2025-07', net_sales_sek: 3_214_000, category_avg_sek: 2_961_000 },
  { month: '2025-08', net_sales_sek: 3_486_500, category_avg_sek: 3_140_200 },
  { month: '2025-09', net_sales_sek: 3_702_000, category_avg_sek: 3_402_800 },
  { month: '2025-10', net_sales_sek: 3_918_500, category_avg_sek: 3_610_400 },
  { month: '2025-11', net_sales_sek: 5_264_000, category_avg_sek: 4_988_600 },
  { month: '2025-12', net_sales_sek: 5_831_500, category_avg_sek: 5_402_100 },
  { month: '2026-01', net_sales_sek: 3_128_000, category_avg_sek: 2_902_500 },
  { month: '2026-02', net_sales_sek: 3_342_500, category_avg_sek: 3_088_700 },
  { month: '2026-03', net_sales_sek: 3_764_000, category_avg_sek: 3_401_900 },
  { month: '2026-04', net_sales_sek: 3_905_500, category_avg_sek: 3_594_200 },
  { month: '2026-05', net_sales_sek: 4_118_000, category_avg_sek: 3_802_600 },
  { month: '2026-06', net_sales_sek: 5_222_500, category_avg_sek: 4_611_300 },
]

const TOP_PRODUCT_ROWS: ResultRow[] = [
  { product: 'Nordström TV N100 Pro 65"', net_sales_sek: 3_184_500, units: 268 },
  { product: 'Nordström Laptop L14 Air', net_sales_sek: 2_642_000, units: 312 },
  { product: 'Nordström TV N80 55"', net_sales_sek: 2_118_500, units: 289 },
  { product: 'Nordström Laptop L16 Studio', net_sales_sek: 1_874_000, units: 141 },
  { product: 'Nordström TV N100 Pro 55"', net_sales_sek: 1_605_500, units: 174 },
  { product: 'Nordström Soundbar S50', net_sales_sek: 1_342_000, units: 604 },
  { product: 'Nordström Hörlurar H3 Wireless', net_sales_sek: 1_128_500, units: 1_412 },
  { product: 'Nordström TV N60 43"', net_sales_sek: 964_000, units: 218 },
  { product: 'Nordström Laptop L13 Go', net_sales_sek: 842_500, units: 118 },
  { product: 'Nordström Hörlurar H1', net_sales_sek: 718_000, units: 2_390 },
]

const REGION_ROWS: ResultRow[] = [
  { region: 'Stockholms län', net_sales_sek: 8_453_000, share_pct: 36.0 },
  { region: 'Västra Götalands län', net_sales_sek: 4_227_000, share_pct: 18.0 },
  { region: 'Skåne län', net_sales_sek: 3_287_000, share_pct: 14.0 },
  { region: 'Uppsala län', net_sales_sek: 1_409_000, share_pct: 6.0 },
  { region: 'Östergötlands län', net_sales_sek: 1_174_000, share_pct: 5.0 },
  { region: 'Jönköpings län', net_sales_sek: 939_000, share_pct: 4.0 },
  { region: 'Västerbottens län', net_sales_sek: 704_000, share_pct: 3.0 },
  { region: 'Övriga län', net_sales_sek: 3_287_500, share_pct: 14.0 },
]

const STOCKHOLM_PRODUCT_ROWS: ResultRow[] = [
  { product: 'Nordström TV N100 Pro 65"', net_sales_sek: 1_284_600, units: 108 },
  { product: 'Nordström Laptop L14 Air', net_sales_sek: 1_042_300, units: 123 },
  { product: 'Nordström TV N80 55"', net_sales_sek: 762_700, units: 104 },
  { product: 'Nordström Laptop L16 Studio', net_sales_sek: 693_400, units: 52 },
  { product: 'Nordström Soundbar S50', net_sales_sek: 528_900, units: 238 },
  { product: 'Nordström TV N100 Pro 55"', net_sales_sek: 497_800, units: 54 },
  { product: 'Nordström Hörlurar H3 Wireless', net_sales_sek: 431_200, units: 539 },
  { product: 'Nordström TV N60 43"', net_sales_sek: 352_100, units: 80 },
]

const WEEKLY_SKANE_ROWS: ResultRow[] = [
  { week: '2026-W18', net_sales_sek: 118_400 },
  { week: '2026-W19', net_sales_sek: 132_900 },
  { week: '2026-W20', net_sales_sek: 127_300 },
  { week: '2026-W21', net_sales_sek: 141_600 },
  { week: '2026-W22', net_sales_sek: 136_200 },
  { week: '2026-W23', net_sales_sek: 158_700 },
  { week: '2026-W24', net_sales_sek: 149_100 },
  { week: '2026-W25', net_sales_sek: 164_800 },
  { week: '2026-W26', net_sales_sek: 172_400 },
]

const RESULTS: Record<string, ResultResponse> = {
  q_trend_01: {
    query_id: 'q_trend_01',
    columns: [COL_MONTH, COL_NET, COL_CATEGORY_AVG],
    rows: TREND_ROWS,
    row_count: TREND_ROWS.length,
    truncated: false,
  },
  q_top_products_01: {
    query_id: 'q_top_products_01',
    columns: [COL_PRODUCT, COL_NET, COL_UNITS],
    rows: TOP_PRODUCT_ROWS,
    row_count: TOP_PRODUCT_ROWS.length,
    truncated: false,
  },
  q_region_01: {
    query_id: 'q_region_01',
    columns: [COL_REGION, COL_NET, COL_SHARE],
    rows: REGION_ROWS,
    row_count: REGION_ROWS.length,
    truncated: false,
  },
  q_sthlm_products: {
    query_id: 'q_sthlm_products',
    columns: [COL_PRODUCT, COL_NET, COL_UNITS],
    rows: STOCKHOLM_PRODUCT_ROWS,
    row_count: 1_243,
    truncated: true,
  },
  q_skane_weekly: {
    query_id: 'q_skane_weekly',
    columns: [{ key: 'week', type: 'date', label: 'ISO-vecka' }, COL_NET],
    rows: WEEKLY_SKANE_ROWS,
    row_count: WEEKLY_SKANE_ROWS.length,
    truncated: false,
  },
}

export function mockResult(queryId: string): ResultResponse {
  const found = RESULTS[queryId]
  if (!found) throw new Error(`Okänt query_id: ${queryId}`)
  return found
}

// --- dashboard cards --------------------------------------------------------

const TREND_CARD: AnswerCard = {
  card_id: 'dash_trend',
  status: 'ok',
  narrative:
    'Försäljningen ligger på 23,5 Mkr för första halvåret 2026, 8,2 % högre än samma period förra året. Juni är starkast med 5,2 Mkr, och ditt varumärke har legat över kategorisnittet per varumärke varje månad under de senaste tolv månaderna.',
  insights: [
    'Juni 2026 är den starkaste månaden i perioden med 5,2 Mkr.',
    'Novemberkampanjen lyfte försäljningen 34 % över oktober.',
    'Avståndet till kategorisnittet är som störst i juni (+13 %).',
  ],
  caveats: ['Kategorisnittet är ett aggregat över 6 varumärken; enskilda konkurrenter visas inte.'],
  chart: {
    type: 'line',
    x: 'month',
    y: ['net_sales_sek', 'category_avg_sek'],
    series: null,
    sort: 'asc',
    limit: null,
    title: 'Försäljning per månad',
    subtitle: 'ditt varumärke vs kategorisnitt per varumärke · nettoförsäljning, exkl. moms',
  },
  query_id: 'q_trend_01',
  columns: [COL_MONTH, COL_NET, COL_CATEGORY_AVG],
  provenance: provenance({
    tool: 'dashboard',
    source: 'mv_brand_monthly (rollup)',
    time_range: TRAILING_12,
    compare_range: { from: '2024-07-01', to: '2025-06-30' },
    row_count: 12,
    filters_applied: {},
    tool_args: {
      measures: ['net_sales_sek'],
      dimensions: ['month'],
      time_range: TRAILING_12,
      compare_to: 'same_period_last_year',
    },
  }),
  suggestions: [],
}

const TOP_PRODUCTS_CARD: AnswerCard = {
  card_id: 'dash_top_products',
  status: 'ok',
  narrative:
    'Nordström TV N100 Pro 65" är den mest säljande produkten under första halvåret 2026 med 3,2 Mkr. TV-modellerna står för ungefär hälften av topp tio, medan hörlurarna säljer i klart högst antal enheter.',
  insights: [
    'Topp tio står för 70 % av försäljningen i perioden.',
    'Nordström Hörlurar H1 säljer 2 390 enheter — flest i antal, lägst i värde.',
  ],
  caveats: [],
  chart: {
    type: 'bar',
    x: 'product',
    y: ['net_sales_sek'],
    series: null,
    sort: 'desc',
    limit: 10,
    title: 'Topp 10 produkter',
    subtitle: 'jan–jun 2026 · nettoförsäljning, exkl. moms',
  },
  query_id: 'q_top_products_01',
  columns: [COL_PRODUCT, COL_NET, COL_UNITS],
  provenance: provenance({
    tool: 'dashboard',
    row_count: 10,
    tool_args: {
      measures: ['net_sales_sek', 'units'],
      dimensions: ['product'],
      time_range: PERIOD,
      order_by: { measure: 'net_sales_sek', dir: 'desc' },
      limit: 10,
    },
  }),
  suggestions: [],
}

const REGION_CARD: AnswerCard = {
  card_id: 'dash_region',
  status: 'ok',
  narrative:
    'Stockholms län är den största marknaden med 8,5 Mkr, 36 % av försäljningen under första halvåret 2026. Därefter följer Västra Götalands län med 18 % och Skåne län med 14 %.',
  insights: [
    'De tre största länen står tillsammans för 68 % av försäljningen.',
    'Fördelningen följer befolkningen tätt — ingen region avviker mer än 3 p.e.',
  ],
  caveats: ['Onlineförsäljning fördelas på leveransadressens län.'],
  chart: {
    type: 'bar',
    x: 'region',
    y: ['net_sales_sek'],
    series: null,
    sort: 'desc',
    limit: null,
    title: 'Försäljning per region',
    subtitle: 'jan–jun 2026 · nettoförsäljning, exkl. moms',
  },
  query_id: 'q_region_01',
  columns: [COL_REGION, COL_NET, COL_SHARE],
  provenance: provenance({
    tool: 'dashboard',
    row_count: 8,
    tool_args: {
      measures: ['net_sales_sek'],
      dimensions: ['region'],
      time_range: PERIOD,
      order_by: { measure: 'net_sales_sek', dir: 'desc' },
    },
  }),
  suggestions: [],
}

export function mockDashboard(): DashboardResponse {
  return { kpis: KPIS, cards: [TREND_CARD, TOP_PRODUCTS_CARD, REGION_CARD] }
}

// --- saved views ------------------------------------------------------------

const SAVED_SEED: AnswerCard = {
  ...REGION_CARD,
  card_id: 'card_01JQ4Z',
  chart: {
    ...REGION_CARD.chart!,
    title: 'Försäljning per region — sparad vy',
  },
}

let savedCards: AnswerCard[] = [SAVED_SEED]
let savedCounter = 1

export function mockListCards(): AnswerCard[] {
  return savedCards
}

export function mockSaveCard(request: SaveCardRequest, source?: AnswerCard): AnswerCard {
  savedCounter += 1
  const card: AnswerCard = {
    ...(source ?? REGION_CARD),
    card_id: `card_saved_${savedCounter}`,
    chart: { ...request.chart, title: request.title },
  }
  savedCards = [card, ...savedCards]
  return card
}

export function mockDeleteCard(cardId: string): void {
  savedCards = savedCards.filter((card) => card.card_id !== cardId)
}

export function mockShare(cardId: string, mode: 'snapshot' | 'live'): ShareResponse {
  return {
    url: `https://insights.solvigo.se/s/${mode}/${cardId.slice(-8)}-a91f`,
    expires_at: '2026-07-14T14:32:11Z',
  }
}

// --- chat -------------------------------------------------------------------

const CHAT_TOOL_SALES = 'query_sales'
const CHAT_TOOL_RESOLVE = 'resolve_entities'

type MockConversation = { events: ChatEvent[] }

function tokens(text: string): ChatEvent[] {
  // Chunk on word boundaries so the stream looks like a real token stream.
  return text.split(/(?<=\s)/).map((chunk) => ({ type: 'token', text: chunk }))
}

const STOCKHOLM_CARD: AnswerCard = {
  card_id: null,
  status: 'ok',
  narrative:
    'I Stockholms län säljer Nordström TV N100 Pro 65" bäst under första halvåret 2026 med 1,3 Mkr, följd av Nordström Laptop L14 Air med 1,0 Mkr. Stockholm står för 36 % av din totala försäljning i perioden.',
  insights: [
    'TV-modellerna tar tre av de fem toppositionerna i länet.',
    'Laptop L14 Air har en högre andel av försäljningen i Stockholm (12,3 %) än nationellt (11,3 %).',
  ],
  caveats: ['Endast fysiska butiker i Stockholms län; onlineförsäljning ingår inte i denna vy.'],
  chart: {
    type: 'bar',
    x: 'product',
    y: ['net_sales_sek'],
    series: null,
    sort: 'desc',
    limit: 8,
    title: 'Topp produkter i Stockholms län',
    subtitle: 'jan–jun 2026 · nettoförsäljning, exkl. moms',
  },
  query_id: 'q_sthlm_products',
  columns: [COL_PRODUCT, COL_NET, COL_UNITS],
  provenance: provenance({
    tool: CHAT_TOOL_SALES,
    source: 'mv_sales_daily (rollup)',
    row_count: 1_243,
    truncated: true,
    filters_applied: { region: ['Stockholms län'], channel: ['fysisk'] },
    tool_args: {
      measures: ['net_sales_sek', 'units'],
      dimensions: ['product'],
      filters: { region: ['Stockholms län'], channel: ['fysisk'] },
      time_range: PERIOD,
      order_by: { measure: 'net_sales_sek', dir: 'desc' },
      limit: 8,
    },
  }),
  suggestions: [],
}

const TREND_CHAT_CARD: AnswerCard = {
  ...TREND_CARD,
  card_id: null,
  narrative:
    'Försäljningen har vuxit varje månad sedan januari, från 3,1 Mkr till 5,2 Mkr i juni. Hela halvåret landar på 23,5 Mkr, 8,2 % över samma period 2025.',
  provenance: provenance({
    tool: CHAT_TOOL_SALES,
    source: 'mv_sales_daily (rollup)',
    time_range: TRAILING_12,
    compare_range: PERIOD_LY,
    row_count: 12,
    tool_args: {
      measures: ['net_sales_sek'],
      dimensions: ['month'],
      time_range: TRAILING_12,
      compare_to: 'same_period_last_year',
    },
  }),
}

const VALIDATION_FAILED_CARD: AnswerCard = {
  card_id: null,
  status: 'validation_failed',
  narrative: '',
  insights: [],
  caveats: [],
  chart: {
    type: 'line',
    x: 'week',
    y: ['net_sales_sek'],
    series: null,
    sort: 'asc',
    limit: null,
    title: 'Försäljning per vecka i Skåne län',
    subtitle: 'v. 18–26 2026 · nettoförsäljning, exkl. moms',
  },
  query_id: 'q_skane_weekly',
  columns: [{ key: 'week', type: 'date', label: 'ISO-vecka' }, COL_NET],
  provenance: provenance({
    tool: CHAT_TOOL_SALES,
    source: 'fact_sales_line',
    time_range: { from: '2026-04-27', to: '2026-06-28' },
    row_count: 9,
    filters_applied: { region: ['Skåne län'] },
    tool_args: {
      measures: ['net_sales_sek'],
      dimensions: ['iso_week'],
      filters: { region: ['Skåne län'] },
      time_range: { from: '2026-04-27', to: '2026-06-28' },
    },
  }),
  suggestions: [],
}

const CLARIFY_CARD: AnswerCard = {
  card_id: null,
  status: 'clarify',
  narrative:
    '"Lurar" kan syfta på flera saker i din katalog. Vilken menar du?',
  insights: [],
  caveats: [],
  chart: null,
  query_id: null,
  columns: [],
  provenance: null,
  suggestions: [
    'Kategorin Hörlurar (48 produkter)',
    'Nordström Hörlurar H3 Wireless',
    'Nordström Hörlurar H1',
    'Underkategorin Trådlösa hörlurar',
  ],
}

const CANNOT_ANSWER_CARD: AnswerCard = {
  card_id: null,
  status: 'cannot_answer',
  narrative:
    'Marginal och inköpskostnad finns inte i den data du har åtkomst till — vi har försäljning, enheter, snittpris och rabatt, men inte kostnadssidan. Här är frågor jag kan svara på istället.',
  insights: [],
  caveats: [],
  chart: null,
  query_id: null,
  columns: [],
  provenance: null,
  suggestions: [
    'Hur stor är vår rabattandel per kategori?',
    'Vad är snittpriset per produkt i år?',
    'Hur har nettoförsäljningen utvecklats per månad?',
  ],
}

const OUT_OF_COVERAGE_CARD: AnswerCard = {
  card_id: null,
  status: 'cannot_answer',
  narrative:
    'Datan täcker 1 juli 2024 till 30 juni 2026, så jag kan inte svara på frågor utanför det intervallet — och jag gör inga prognoser. Närmaste besvarbara fråga finns nedan.',
  insights: [],
  caveats: [],
  chart: null,
  query_id: null,
  columns: [],
  provenance: null,
  suggestions: [
    'Hur såg försäljningen ut första halvåret 2026?',
    'Jämför 2026 med samma period 2025',
    'Vilken månad var starkast under täckningsperioden?',
  ],
}

/** Keyword routing so the demo can show every status without a backend. */
function pickConversation(question: string): MockConversation {
  const q = question.toLowerCase()

  if (/margin|marginal|vinst|kostnad|cogs|inköpspris/.test(q)) {
    return {
      events: [
        { type: 'status', message: 'Läser vad datan innehåller…' },
        { type: 'tool_call', tool: 'get_capabilities', args: {} },
        { type: 'tool_result', tool: 'get_capabilities', row_count: 0 },
        { type: 'card', card: CANNOT_ANSWER_CARD },
      ],
    }
  }

  if (/2019|2020|2021|2022|2023|nästa kvartal|nästa år|prognos|kommer att/.test(q)) {
    return {
      events: [
        { type: 'status', message: 'Kontrollerar datatäckning…' },
        { type: 'tool_call', tool: 'get_capabilities', args: {} },
        { type: 'tool_result', tool: 'get_capabilities', row_count: 0 },
        { type: 'card', card: OUT_OF_COVERAGE_CARD },
      ],
    }
  }

  if (/\blurar\b|luren/.test(q)) {
    return {
      events: [
        { type: 'status', message: 'Slår upp "lurar" i katalogen…' },
        { type: 'tool_call', tool: CHAT_TOOL_RESOLVE, args: { text: 'lurar', kinds: ['product', 'category'] } },
        { type: 'tool_result', tool: CHAT_TOOL_RESOLVE, row_count: 4 },
        { type: 'card', card: CLARIFY_CARD },
      ],
    }
  }

  if (/vecka|veckovis|veckor/.test(q)) {
    return {
      events: [
        { type: 'status', message: 'Slår upp Skåne län…' },
        { type: 'tool_call', tool: CHAT_TOOL_RESOLVE, args: { text: 'Skåne', kinds: ['region'] } },
        { type: 'tool_result', tool: CHAT_TOOL_RESOLVE, row_count: 1 },
        {
          type: 'tool_call',
          tool: CHAT_TOOL_SALES,
          args: {
            measures: ['net_sales_sek'],
            dimensions: ['iso_week'],
            filters: { region: ['Skåne län'] },
          },
        },
        { type: 'tool_result', tool: CHAT_TOOL_SALES, row_count: 9 },
        { type: 'status', message: 'Verifierar siffrorna i svarstexten…' },
        { type: 'card', card: VALIDATION_FAILED_CARD },
      ],
    }
  }

  if (/månad|utveckling|trend|per månad|i år/.test(q)) {
    return {
      events: [
        { type: 'status', message: 'Hämtar försäljning per månad…' },
        {
          type: 'tool_call',
          tool: CHAT_TOOL_SALES,
          args: {
            measures: ['net_sales_sek'],
            dimensions: ['month'],
            time_range: TRAILING_12,
            compare_to: 'same_period_last_year',
          },
        },
        { type: 'tool_result', tool: CHAT_TOOL_SALES, row_count: 12 },
        ...tokens(TREND_CHAT_CARD.narrative),
        { type: 'card', card: TREND_CHAT_CARD },
      ],
    }
  }

  // Default: the case's own example question.
  return {
    events: [
      { type: 'status', message: 'Slår upp Stockholm…' },
      {
        type: 'tool_call',
        tool: CHAT_TOOL_RESOLVE,
        args: { text: 'Stockholm', kinds: ['region', 'store'] },
      },
      { type: 'tool_result', tool: CHAT_TOOL_RESOLVE, row_count: 3 },
      { type: 'status', message: 'Hämtar försäljning…' },
      {
        type: 'tool_call',
        tool: CHAT_TOOL_SALES,
        args: {
          measures: ['net_sales_sek', 'units'],
          dimensions: ['product'],
          filters: { region: ['Stockholms län'], channel: ['fysisk'] },
          time_range: PERIOD,
          order_by: { measure: 'net_sales_sek', dir: 'desc' },
          limit: 8,
        },
      },
      { type: 'tool_result', tool: CHAT_TOOL_SALES, row_count: 1_243 },
      ...tokens(STOCKHOLM_CARD.narrative),
      { type: 'card', card: STOCKHOLM_CARD },
    ],
  }
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

/** Replays a scripted conversation with believable pacing. */
export async function mockChatStream(
  question: string,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const { events } = pickConversation(question)
  for (const event of events) {
    if (signal?.aborted) return
    const delay =
      event.type === 'token' ? 18 : event.type === 'tool_result' ? 520 : event.type === 'card' ? 220 : 340
    await sleep(delay)
    if (signal?.aborted) return
    onEvent(event)
  }
}

export const MOCK_EXAMPLE_QUESTIONS = [
  'Vilka produkter säljer bäst i Stockholm?',
  'Hur har försäljningen utvecklats per månad?',
  'Hur går det för lurar?',
  'Vad är vår marginal?',
  'Visa försäljning per vecka i Skåne',
]
