"""Server-side strings, in the languages the product ships in.

Only the text the *server* produces lives here: dashboard card titles, KPI labels, the period
nouns, the caveats the render step writes. Everything the client owns is in
`web/src/lib/i18n.ts`. The split follows who writes the string, not who displays it - a card
title has to survive being saved, shared and re-opened by a reader with no session, and a
string the server never wrote is a string a share link cannot carry.

Column labels are deliberately NOT here. They come off the semantic model as keys the client
already knows (`net_sales_sek`, `region`), so the client translates them and falls back to
whatever label the server sent. That keeps the semantic layer monolingual - it is a data
contract, not a presentation one.
"""

from __future__ import annotations

from contextvars import ContextVar

from .config import settings

# The languages the UI ships in. Adding one is this dict plus its twin in web/src/lib/i18n.ts.
LANGUAGES = ("sv", "en")

# Request-scoped, the same way api/logs.py carries the turn id. The alternative was a `lang`
# parameter on every function in render.py - fifteen signatures changed so that one caveat at
# the bottom could pick a string. The language is a property of the request, so it travels
# with the request.
_language: ContextVar[str] = ContextVar("language", default="")


def use(requested: str | None) -> str:
    """Set the language for everything under this request. Returns what was resolved."""
    lang = resolve(requested)
    _language.set(lang)
    return lang


def current() -> str:
    return _language.get() or resolve(None)


def tr(key: str, **kwargs: object) -> str:
    """`t` against the current request's language - what server code calls.

    Not named `_`: that is Python's throwaway, and `chart, _ = validate_chart(...)` three lines
    above a `_("some.key")` rebinds the translator to a list of validation problems. Ruff caught
    exactly that on the share route, where it would have been a TypeError the moment a supplier
    had no name.
    """
    return t(current(), key, **kwargs)


def resolve(requested: str | None) -> str:
    """The language to answer in: what was asked for, else the deployment's default.

    Accepts a bare tag or a full `Accept-Language` value, so a browser header works unparsed.
    An unknown language falls back rather than 400s - a wrong language is a bad answer, a
    rejected request is no answer.
    """
    for candidate in (requested or "").replace(";", ",").split(","):
        tag = candidate.strip().split("-")[0].lower()
        if tag in LANGUAGES:
            return tag
    return settings.app_language if settings.app_language in LANGUAGES else LANGUAGES[0]


def t(lang: str, key: str, **kwargs: object) -> str:
    """One string. Missing keys fall back to Swedish, then to the key itself."""
    table = STRINGS.get(lang) or {}
    template = table.get(key) or STRINGS["sv"].get(key) or key
    return template.format(**kwargs) if kwargs else template


STRINGS: dict[str, dict[str, str]] = {
    "sv": {
        # periods
        "period.last_7_days": "Senaste veckan",
        "period.last_30_days": "Senaste 30 dagarna",
        "period.last_90_days": "Senaste kvartalet",
        "period.last_month": "Förra månaden",
        "period.ytd": "Hittills i år",
        "period.last_12_months": "Senaste 12 mån",
        "period.all_time": "Hela perioden",
        "grain.day": "dag",
        "grain.week": "vecka",
        "grain.month": "månad",
        "grain.quarter": "kvartal",
        # dashboard
        "dash.trend": "Försäljning per {noun}",
        "dash.top_products": "Topp 10 produkter",
        "dash.by_region": "Försäljning per region",
        "dash.movers_up": "Största uppgångar",
        "dash.movers_down": "Största tapp",
        "dash.delta_label": "vs föregående period",
        "dash.moving_average": "Glidande medel ({window} perioder)",
        "dash.movers_caveat": (
            "Rangordnat efter förändring i {currency}. Välj Tabell för den procentuella "
            "förändringen - en stor procentrörelse kan komma från en liten utgångsnivå."),
        "dash.campaign_markers": (
            "Streckade linjer markerar perioder med kampanj - handlaren rabatterar tungt då."),
        "dash.error": "Kunde inte hämta dashboarddata: {error}",
        "dash.movers_error": "Kunde inte hämta produktrörelser: {error}",
        # KPI tiles
        "kpi.net_sales": "Försäljning",
        "kpi.category_share": "Andel av kategori",
        "kpi.units": "Sålda enheter",
        "kpi.avg_price": "Snittpris",
        "kpi.rank": "#{rank} av {total} varumärken i {subcategory}",
        # render.py
        "card.fallback_title": "Resultat",
        "card.market_share": "Marknadsandel",
        "card.sales": "Försäljning",
        "card.title_per": "{head} per {dimensions}",
        "card.and": " och ",
        "card.chart_override_kpi": (
            "Resultatet är ett enda tal - den föreslagna vyn passade inte datan."),
        "card.chart_override": "Visar som {chart} - den föreslagna vyn passade inte datan.",
        "chart.line": "linjediagram",
        "chart.bar": "stapeldiagram",
        "chart.stacked_bar": "staplat stapeldiagram",
        "chart.area": "ytdiagram",
        "chart.pie": "cirkeldiagram",
        "chart.table": "tabell",
        "chart.generic": "diagram",
        # auth and the reset mail
        "auth.user_gone": "Användaren finns inte längre",
        "auth.wrong_current_password": "Nuvarande lösenord stämmer inte",
        "auth.reset_invalid": "Länken är ogiltig eller har redan använts. Begär en ny.",
        "auth.reset_sent": ("Om adressen hör till ett konto har vi skickat en "
                            "återställningslänk."),
        "mail.reset_subject": "Återställ ditt lösenord - Solvigo Insights",
        "mail.reset_body": (
            "Hej {name},\n\n"
            "Någon har begärt ett nytt lösenord för ditt Solvigo Insights-konto. Öppna "
            "länken nedan för att välja ett:\n\n"
            "{link}\n\n"
            "Länken gäller i {minutes} minuter och kan bara användas en gång.\n\n"
            "Var det inte du behöver du inte göra något - ditt nuvarande lösenord "
            "fortsätter att gälla.\n"),
        # misc
        # Abbreviated month names, for the period labels the server writes onto a card's
        # legend. Comma-separated because it is one string to translate, not twelve.
        "months.short": "jan,feb,mar,apr,maj,jun,jul,aug,sep,okt,nov,dec",
        "unknown.source": "okänd",
        "unknown.scope": "okänt",
        "unknown.supplier": "okänd leverantör",
    },
    "en": {
        "period.last_7_days": "Last 7 days",
        "period.last_30_days": "Last 30 days",
        "period.last_90_days": "Last quarter",
        "period.last_month": "Last month",
        "period.ytd": "Year to date",
        "period.last_12_months": "Last 12 months",
        "period.all_time": "All time",
        "grain.day": "day",
        "grain.week": "week",
        "grain.month": "month",
        "grain.quarter": "quarter",
        "dash.trend": "Sales per {noun}",
        "dash.top_products": "Top 10 products",
        "dash.by_region": "Sales by region",
        "dash.movers_up": "Biggest risers",
        "dash.movers_down": "Biggest fallers",
        "dash.delta_label": "vs previous period",
        "dash.moving_average": "Moving average ({window} periods)",
        "dash.movers_caveat": (
            "Ranked by change in {currency}. Switch to Table for the percentage change - a "
            "large percentage move can come from a small base."),
        "dash.campaign_markers": (
            "Dashed lines mark campaign periods - the retailer discounts heavily then."),
        "dash.error": "Could not load dashboard data: {error}",
        "dash.movers_error": "Could not load product movements: {error}",
        "kpi.net_sales": "Sales",
        "kpi.category_share": "Category share",
        "kpi.units": "Units sold",
        "kpi.avg_price": "Average price",
        "kpi.rank": "#{rank} of {total} brands in {subcategory}",
        "card.fallback_title": "Result",
        "card.market_share": "Market share",
        "card.sales": "Sales",
        "card.title_per": "{head} by {dimensions}",
        "card.and": " and ",
        "card.chart_override_kpi": (
            "The result is a single figure - the proposed view did not fit the data."),
        "card.chart_override": "Shown as a {chart} - the proposed view did not fit the data.",
        "chart.line": "line chart",
        "chart.bar": "bar chart",
        "chart.stacked_bar": "stacked bar chart",
        "chart.area": "area chart",
        "chart.pie": "pie chart",
        "chart.table": "table",
        "chart.generic": "chart",
        "auth.user_gone": "That user no longer exists",
        "auth.wrong_current_password": "Your current password is not correct",
        "auth.reset_invalid": "This link is invalid or has already been used. Request a new one.",
        "auth.reset_sent": "If that address belongs to an account, we have sent a reset link.",
        "mail.reset_subject": "Reset your password - Solvigo Insights",
        "mail.reset_body": (
            "Hi {name},\n\n"
            "Someone asked for a new password for your Solvigo Insights account. Open the "
            "link below to choose one:\n\n"
            "{link}\n\n"
            "The link is valid for {minutes} minutes and can only be used once.\n\n"
            "If this was not you, there is nothing to do - your current password keeps "
            "working.\n"),
        "months.short": "Jan,Feb,Mar,Apr,May,Jun,Jul,Aug,Sep,Oct,Nov,Dec",
        "unknown.source": "unknown",
        "unknown.scope": "unknown",
        "unknown.supplier": "unknown supplier",
    },
}
