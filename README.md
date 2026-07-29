# Solvigo Insights — AI-native försäljningsdashboard

"BI utan BI-avdelning" för leverantörer i svensk detaljhandel. En leverantör loggar in och
landar på en **färdig dashboard** — inte en tom chattruta — och kan sedan fördjupa sig genom
att fråga sin data på vanlig svenska. Både dashboarden och chatten läser data på exakt samma
väg: genom en MCP-server.

> **Kärnpåståendet:** siffrorna du ser har aldrig passerat språkmodellen.
> Modellen väljer *frågan* och *presentationen*. Värdena går
> Postgres → MCP → API → diagram, längs en väg modellen inte rör.

Designresonemanget i sin helhet ligger i [`IMPLEMENTATION_PLAN.md`](../IMPLEMENTATION_PLAN.md).
Den här filen är hur du kör systemet och de val som är värda att förstå först.

---

## Kör det

```bash
cp .env.example .env          # lägg in LLM_API_KEY
python scripts/generate_data.py --seed 42
docker compose up
```

- Webb: http://localhost:5173
- API: http://localhost:8000/docs

MCP-servern och Postgres publiceras **inte** på värden i standarduppsättningen. De behöver
det inte — API:t når dem över compose-nätverket — och `internal_token` är tänkt som
djupförsvar bakom en oåtkomlig port, inte som hela åtkomstkontrollen. För att kunna anropa
verktygen direkt eller öppna `psql` och se RLS neka en läsning över tenant-gränsen:

```bash
docker compose -f docker-compose.yml -f docker-compose.demo.yml up
```

Då finns MCP health på http://localhost:8081/health och Postgres på `localhost:5432`.

`SOLVIGO_ENV=dev` i `.env.example` är det som tillåter de inkomna standardhemligheterna.
Utan den vägrar både API:t och MCP-servern att starta så länge `JWT_SECRET`,
`INTERNAL_TOKEN`, `POSTGRES_PASSWORD` eller `APP_DB_PASSWORD` står kvar på värdena som
ligger i repot — de är publika, och en okonfigurerad driftsättning ska falla högljutt
i stället för att köra vidare på dem.

Demokonton (lösenord `demo1234`):

| E-post | Leverantör |
|---|---|
| `anna@nordstromaudio.se` | Nordström Audio AB |
| `erik@lagerkvisthem.se` | Lagerkvist Hem AB |

Två konton finns för att kunna **visa** dataisolering live: samma fråga, olika inloggning,
olika siffror.

### Utan Docker

```bash
uv venv && uv pip install -e ".[dev]"
python scripts/generate_data.py --seed 42
python scripts/seed.py                      # kräver en Postgres 16 med pgvector
python -m mcp_server.server                 # :8081
uvicorn api.main:app --reload               # :8000
cd web && npm install && npm run dev        # :5173
```

### Tester

```bash
pip install -e ".[dev]"       # allt testerna behöver, inklusive sqlglot
pytest                        # semantiskt lager, verktyg, API, validator
cd web && npm test            # diagramkontraktet: ordning, gräns, serier, skala
cd web && npm run build       # typkontroll + bygge
python eval/run_eval.py       # gyllene frågor mot ground truth
python eval/run_eval.py --adversarial
```

`pytest` kräver ingen databas. Sviten innehåller också ett fåtal integrationstester —
de påståenden som bara en riktig, seedad Postgres kan pröva: att RLS faktiskt stoppar en
läsning över tenant-gränsen när anropet går genom verktygen, och att verktygen
reproducerar `ground_truth.json`. De hoppas över automatiskt när ingen databas svarar,
och körs så här mot en igång-körande stack:

```bash
POSTGRES_HOST=localhost pytest -q -m integration
```

Frontenden kan köras utan backend för design- och demoarbete: sätt `VITE_USE_MOCKS=true`
i `web/.env.local` så serveras fixturerna i `web/src/lib/mocks.ts` i stället för API:et.

---

## Arkitektur

```
┌───────────────────────────────────────────────────────────────────────────┐
│  React 19 + Vite + TS      Recharts · TanStack Query                      │
│  Dashboard (kort)  ·  Chattpanel (SSE)  ·  Mina vyer                      │
└───────────────┬───────────────────────────────────────────────────────────┘
                │ HTTPS + JWT (Bearer)
┌───────────────▼───────────────────────────────────────────────────────────┐
│  FastAPI                                                                  │
│   ├ auth: JWT → TenantContext{supplier_id}   ← aldrig från modellen       │
│   ├ /api/dashboard   deterministisk, ingen LLM                            │
│   ├ /api/chat        agentturn (SSE)                                      │
│   └ /api/result/{query_id}   fullt resultat ── diagrammens datakälla      │
│                                                                           │
│   Agentpipeline:  PLAN+EXECUTE → VALIDATE (numeriskt) → RENDER (kort)     │
└───────────────┬───────────────────────────────────────────────────────────┘
                │ MCP (streamable HTTP, internt)
                │ TenantContext injiceras här — inte del av något verktygsschema
┌───────────────▼───────────────────────────────────────────────────────────┐
│  MCP-server (FastMCP)                  "det semantiska lagret"            │
│   get_capabilities()    vad som finns, vilka enheter, vad som är tillåtet  │
│   resolve_entities()    fritext → kanoniska ID (pg_trgm + pgvector)        │
│   query_sales()         mått × dimensioner × filter → rader                │
│   query_market_share()  egen vs kategori, k-anonymiserat, aldrig namngivet │
└───────────────┬───────────────────────────────────────────────────────────┘
                │ asyncpg, roll `app_readonly`, set_config('app.supplier_id')
┌───────────────▼───────────────────────────────────────────────────────────┐
│  PostgreSQL 16 + pgvector + pg_trgm                                       │
│   stjärnschema · materialiserade rollups · RLS · barriärvyer              │
└───────────────────────────────────────────────────────────────────────────┘
```

**Notera de två konsumenterna.** Den deterministiska dashboarden och LLM-agenten anropar
*samma fyra verktyg*. MCP är inte ett omslag vi lade till för modellens skull — det är enda
vägen till data. Därför kan chatten och dashboarden inte visa olika siffror för samma sak.

---

## De val som är värda att förstå

### 1. Ett semantiskt lager, inte text-to-SQL

Det här är beslutet jag räknar med att bli hårdast utfrågad om.

| | Text-to-SQL | Ett verktyg per fråga | **Semantiskt frågeverktyg** |
|---|---|---|---|
| Klarar frågor vi inte förutsett | ✅ | ❌ | ✅ |
| Kan inte råka dubbelräkna | ❌ | ✅ | ✅ |
| Leverantörsomfång serverside | ⚠️ stränginjektion | ✅ | ✅ |
| Enheter kan fästas på resultatet | ❌ | ✅ | ✅ |
| Testbart isolerat | ❌ | ✅ | ✅ |

De sa att de ställer egna frågor live — det stryker kolumn 2. Allt annat stryker kolumn 1.

Konkret: `mcp_server/semantic/model.py` är ett register över vad som får mätas och delas upp.
`compiler.py` översätter en typad spec till SQL där **varje identifierare kommer från
registret** och **varje värde är en bunden parameter**. En fientlig sträng blir ett
valideringsfel, inte en fråga. Det finns 43 tester på just det — de flesta parsar den
genererade SQL:en med `sqlglot` och kontrollerar att inget literalvärde tog sig in i den.

### 2. Så vet vi att siffrorna är verkliga

Fyra lager, i den ordning de bär vikt:

1. **Strukturellt.** `query_sales` returnerar hela resultatmängden. API:t cachar den under ett
   `query_id` och skickar bara en **kapad förhandsvisning (25 rader)** till modellen.
   Diagrammet hämtas sedan från `/api/result/{query_id}`. Modellen ser alltså aldrig de
   värden diagrammet ritar. Det är en egenskap hos arkitekturen, inte hos promptkvaliteten.
2. **Numerisk validering.** Berättelsen *är* genererad text, så efter verktygsloopen plockas
   varje siffra ut ur prosan och måste finnas i resultatmängden — eller vara en tillåten
   härledning (summa, medel, differens, andel) inom avrundningstolerans. Vid fel: en
   omgenerering med den felande siffran citerad tillbaka. Vid andra felet: `validation_failed`,
   prosan utelämnas, diagrammet står kvar. **Att misslyckas synligt slår att misslyckas
   trovärdigt.**
3. **Härkomst.** Varje kort bär en källchip: verktyg · filter · omfång · antal rader ·
   rollup eller faktatabell · tidsstämpel. Expanderad visar den exakta verktygsargumenten.
4. **Mätning.** `eval/` kör 81 svenska frågor — 52 gyllene och 29 adversariella — mot facit
   som räknats fram **oberoende** med pandas ur samma genererade data. Det gör "hallucinerar
   den?" till ett tal jag kan rapportera. Talen står nedan.

### Vad mätningen säger

Kört mot `deepseek-v4-pro` (se *Kända begränsningar*). Två tal, medvetet hållna isär:

| | |
|---|---|
| **Garantierna** (`adversarial.yaml`, 29 fall) | **27–29 av 29**, och **inget fall faller två körningar i rad**. Ingen konkurrentsiffra, ingen kategoritotal under k-tröskeln och ingen rad från en annan leverantör nådde något kort. Samtliga sex promptinjektionsfall avvisas. |
| **Svarskvaliteten** (`golden_questions.yaml`, 52 fall) | **36–40 av 52 (69–77 %)** beroende på körning. |

Spannet är inte slarv, det är resultatet. Två körningar på **identisk kod** gav 36 och 40 —
30 fall passerar stabilt, 6 faller stabilt, och 16 växlar mellan körningar. Ett enskilt värde
från den här uppsättningen betyder därför ingenting; det är därför det står ett spann och ett
stickprov här i stället för en siffra med två decimaler. Rätt nästa steg är *n* körningar per
fall och median, inte en snyggare enskild siffra.

Det viktiga är att de två talen inte rör sig ihop. Svarskvaliteten hänger på modellen och
varierar. Grundgarantin gör det inte: en siffra i prosan som inte går att belägga i
resultatmängden fångas, texten döljs och diagrammet står kvar. Det är inte hög kvalitet, men
det är ärligt, och det är skillnaden mellan ett fel som syns och ett fel som är trovärdigt.

De 6 stabila fallen är svarskvalitet, inte grundning: modellen utelämnar huvudsiffran, hoppar
över `resolve_entities` eller får ordningen i en serie om bakfoten. Inget av dem är ett
påhittat värde som nått ett kort.

**Vad mätningen hittade i skyddet självt.** Uppsättningen fanns för att mäta modellen och
råkade i stället fälla validatorn. Fem av de stabilt fallerande fallen delade form — alla
frågade efter toppsäljande produkter — och loggen visade varför: överträdelserna var `139`,
`217`, `282` och `191 St`. Det är inga belopp, det är modellbeteckningar inne i produktnamn
(`Nordström TV N100 Pro`, `Vidar Hörlurar V191 Studio`), och `St` i "Studio" lästes som
enheten `st`. Validatorn dolde alltså prosan på den vanligaste frågan en leverantör ställer.
Namnen maskas nu med resultatets egna rader innan tal extraheras — bara text verktyget redan
returnerat, aldrig en siffra — och två regressionstester håller båda riktningarna: namn med
riktiga belopp passerar, ett påhittat belopp bredvid ett maskat namn fångas fortfarande.
Poängen är inte buggen utan att en enskild siffra dolde den: 55 % såg ut som en svag modell
och var i själva verket ett skydd som brann av på fel indata.

Modellen får aldrig räkna något databasen kan räkna. Därför finns `compare_to` i verktyget:
periodjämförelser är den vanligaste följdfrågan, och att låta modellen hämta två resultat och
subtrahera är precis där aritmetiska fel uppstår.

### 3. Leverantörsisolering — tre oberoende lager

1. **`supplier_id` finns inte i något verktygsschema.** Modellen kan inte formulera
   "visa leverantör 7". Det testas i `mcp_server/tests/test_schemas.py`, och det är
   det viktigaste testet i repot.
2. **Omfånget kommer från anslutningen, inte argumenten.** API:t skickar det som en
   HTTP-header från en verifierad JWT; MCP-servern sätter `app.supplier_id` på transaktionen.
3. **Postgres RLS** på faktatabellen och dimensionerna, plus **security-barriärvyer** över
   rollup-vyerna.

> Rättelse till planen, värd att nämna: PostgreSQL stöder **inte** RLS på materialiserade
> vyer — `CREATE POLICY` tar bara tabeller. Rollups skyddas därför av motsvarande
> konstruktion: ingen `GRANT` på den materialiserade vyn alls, och åtkomst enbart via en
> `security_barrier`-vy med samma predikat som en policy skulle haft.

Vad en leverantör får se om andra:

| | |
|---|---|
| ✅ Egna varumärken | Full detalj: produkt × butik × dag |
| ✅ Kategoritotaler | Endast aggregat, k-anonymiserat |
| ✅ Egen placering | "#2 av 6 varumärken i Hörlurar" |
| ❌ Namngivna konkurrentsiffror | Aldrig — inte filtrerade, inte åtkomliga |
| ❌ Kundnivå | Aldrig — verktygens minsta kornighet förbjuder det |

**k-anonymitet:** marknadsandelar utelämnas om urvalet har färre än 5 varumärken eller
färre än 100 köp. Annars vore "din andel" bara en subtraktion från en namngiven konkurrents
omsättning. Datagenereringen innehåller **avsiktligt** en tunn underkategori
(`Vintersport`, 3 varumärken) så att skyddet *går att visa*, inte bara påstå.

### 4. Rollups är en integritetsgräns, inte bara cache

`mv_category_daily` och `mv_brand_monthly` är de enda objekt `query_market_share` får läsa.
Konkurrentdata är därför inte "bortfiltrerad" av applikationslogik — den fanns aldrig i det
objekt verktyget når. En rollup som aggregerat bort identitet är en strukturellt starkare
garanti än en `WHERE`-sats.

### 5. Genererad data, inte lånad

Tre publika datamängder utvärderades (Online Retail II, Olist, Superstore). Ingen har den
struktur marknadsandel kräver: flera konkurrerande varumärken per kategori, ägda av olika
leverantörer, med överlappande sortiment. Och ingen ger ett **facit**.

`scripts/generate_data.py --seed 42` är deterministisk — samma seed ger byte-identisk
utdata — och skriver både CSV:erna och `ground_truth.json`. Att det stämmer är inget
påstående: `eval/tests/test_determinism.py` genererar två gånger och jämför SHA-256 per
fil, och kontrollerar dessutom att en *annan* seed ger andra siffror, så testet inte
skulle kunna passera på en generator som ignorerar sin seed. Hela facit vilar på det —
`ground_truth.json` beskriver bara datan om ingen oseedad slump når utdatan.
Formen: 8 leverantörer, 14 varumärken, 6 kategorier / 22 underkategorier, 392 produkter,
81 butiker över alla 21 län plus onlinekanal, 24 månader, ~811 000 orderrader, 848 MSEK.

Ärligt motargument, som jag säger i videon istället för att gömma: syntetisk data kan vara
för städad. Därför injicerar generatorn medvetet verklig smuts — ~1,5 % returer,
~0,8 % kontantköp utan kund, en utgången produkt med avbruten serie, en butik som öppnar
mitt i perioden, prisdrift över tid, och den tunna kategorin ovan.

### 6. LLM-leverantör

**DeepSeek `deepseek-v4-pro`, körd genom Anthropics SDK** mot
`https://api.deepseek.com/anthropic`. DeepSeek exponerar ett Anthropic-kompatibelt endpoint
med fullt `tools`-stöd, och MCP:s verktygsdeskriptor (`{name, description, inputSchema}`) är
i praktiken identisk med Anthropics (`input_schema`) — så konverteringen är ett namnbyte, inte
ett adapterlager. Att byta till riktig Claude är `base_url` plus modellnamn, inget annat.

Vad det kostar, sagt rakt ut:

- Endpointen **ignorerar `cache_control`**, så promptcachningen (~90 % besparing på det
  stabila prefixet) uteblir. Systemprompten är ändå strukturerad som ett stabilt block så
  att den vinsten finns kvar den dag vi byter.
- `anthropic-beta`-headers stöds inte, så SDK:ns `tool_runner` går bort — verktygsloopen är
  skriven explicit, med tak på antal verktygsanrop.
- **Datan lämnar EU.** Grundningsarkitekturen håller, men modellen ser en kapad
  radförhandsvisning, så jag kan inte hävda dataresidens. För produktion i EU pekar man om
  `base_url`.

---

## Repostruktur

```
solvigo-insights/
├─ db/sql/               01_schema · 02_indexes · 03_rollups · 04_rls
├─ mcp_server/
│  ├─ semantic/          registret + spec→SQL-kompilatorn
│  ├─ tools/             de fyra verktygen + deras scheman
│  └─ tests/             86 tester, varav 79 utan databas
├─ api/                  FastAPI: auth, MCP-klient, agentloop, validator, SSE
├─ web/src/
│  ├─ charts/            spec→diagram, deterministiskt (+ enhetstester)
│  ├─ components/        kortrenderare, källchip, chattpanel, skal
│  ├─ pages/             översikt · produkter · geografi · mina vyer
│  └─ lib/               api, SSE, formatering (sv-SE), stores
├─ scripts/              generate_data · seed · embed_entities
├─ eval/                 gyllene frågor + adversariellt + drivrutin
└─ docs/API_CONTRACT.md  fryst gränssnitt mellan backend och frontend
```

---

## Demofrågor att prova

1. "Vad var min försäljning senaste 12 månaderna, och hur står det sig mot året innan?"
2. "Vilka produkter säljer bäst i Stockholm?" — och som följdfråga: "…mätt i antal istället?"
   (svaret ändras: intäkter domineras av TV och datorer, volym av billiga varor)
3. "Hur går det för vårt märke jämfört med kategorin i Hörlurar?"
4. "Visa försäljningen per län som diagram."
5. "Vad är vår marginal?" — **ska nekas**, med förslag på vad som *går* att svara på.
6. "Visa Lumia Nordics siffror." — **ska nekas**; en annan leverantör är inte uttryckbar.
7. Marknadsandel i "Vintersport" — **ska utelämnas** av k-anonymitetsskyddet.

Punkt 5–7 är inte kantfall att undvika i en demo. De är produkten som fungerar.

---

## Vad jag hade gjort härnäst

Riktiga konnektorer och inkrementell inläsning (dbt/CDC) istället för en seed-körning ·
SSO/SCIM · metrikdefinitioner formellt godkända ihop med kedjan · larm och prenumerationer ·
kostnadstak per tenant · promptcachning och modellrouting (billig klassificerare först) ·
PDF-export · tillgänglighet och mobil.

Kända luckor i det som ligger här: ingen realtidsström; rollup-refresh är manuell;
utvärderingsuppsättningen är min egen och delar därmed mina blinda fläckar; syntetisk data
kan inte visa verklig smuts; ingen återkoppling från tummen upp/ner tillbaka in i evalen.

**Delningslänkar är halva.** `POST /api/share` finns och gör den intressanta delen — en
signerad, tidsbegränsad token som bär *ursprungsleverantörens* omfång, så att en live-länk
körs om under den som delade och aldrig under den som läser. Läsänden saknas: hash-routern
har inga parametriserade rutter, så `/delad/{token}` leder ingenstans. Knappen är därför
dold (`SHARE_UI_ENABLED` i `CardActions.tsx`) i stället för att erbjuda en länk till en tom
sida. Det som återstår är en sida som verifierar token och renderar kortet under det omfång
token anger — en halvdag, inte ett designproblem.

Fyra till, som mätningen ovan grävde fram och som jag hellre skriver ned än städar undan:

- **Modellen är inte Claude.** Allt är kört mot `deepseek-v4-pro` via Anthropic-SDK:t
  (beslut D1 — byt `LLM_BASE_URL` och `LLM_MODEL`, inget annat ändras). Svarskvaliteten
  ovan är därför ett golv, inte ett tak: `deepseek-v4-flash` gav 62 % och pro 73 % på samma
  uppsättning. Grundgarantin är oberoende av modellvalet; svarskvaliteten är det inte.
- **31 % av de gyllene fallen är icke-deterministiska** (16 av 52 växlar mellan två
  körningar på identisk kod). Andelen *steg* när validatorbuggen ovan rättades: fall som
  förut föll varje gång växlar nu i stället, vilket är framsteg men inte stabilitet. Med en
  modell som ibland utelämnar huvudsiffran krävs upprepade körningar för att ett tal ska
  betyda något. Nästa steg är *n* körningar per fall och median, inte att jaga en bra körning.
- **Kortet bär ett enda `query_id`.** En tur som anropar flera verktyg exponerar bara det
  sista resultatet mot `/api/result`. Det syntes när evalen skulle kontrollera
  `suppressed`-flaggan från `query_market_share`: raden fanns, men klienten kunde inte nå den
  eftersom en efterföljande `query_sales` tagit över kortets `query_id`. Härkomst per
  verktygsanrop, inte per kort, är rätt form.
- **Modellen svarar ibland på en angränsande fråga i stället för att avböja.** "Vilka kunder
  köpte mest?" kan besvaras med `customer_segment` i stället för ett nekande. Ingen kundrad
  lämnar någonsin verktygslagret — kornighetsgolvet håller — men ett aggregat som *ser ut*
  som ett svar på fel fråga är sitt eget problem.





