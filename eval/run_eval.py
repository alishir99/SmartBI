"""The eval driver — HTTP, and nothing else."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cases  # noqa: E402
import grade  # noqa: E402
from grade import FAMILIES, CaseResult, Observed, family_of, family_rates  # noqa: E402

DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_EMAIL = "anna@nordstromaudio.se"
DEFAULT_PASSWORD = "demo1234"

# One agent turn is several LLM round-trips plus a database query.
DEFAULT_CONCURRENCY = 4

# Generous, because the cap exists to stop a hung stream from wedging the run, not to measure
# latency.
DEFAULT_TIMEOUT_SECONDS = 120.0

# /api/result pages at 1000 by default and caps at 5000.
RESULT_PAGE_LIMIT = 5000


class SetupError(RuntimeError):
    """The run could not start. Distinct from any case failing."""


# ------------------------------------------------------------------------------ styling

@dataclass(frozen=True)
class Style:
    """ANSI only when stdout is a terminal, and ASCII markers regardless."""

    enabled: bool

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def ok(self, text: str) -> str:
        return self._wrap("32", text)

    def bad(self, text: str) -> str:
        return self._wrap("31", text)

    def alarm(self, text: str) -> str:
        return self._wrap("1;31", text)

    def dim(self, text: str) -> str:
        return self._wrap("2", text)

    def bold(self, text: str) -> str:
        return self._wrap("1", text)


# -------------------------------------------------------------------------- transport

@dataclass
class Session:
    client: httpx.AsyncClient
    base_url: str
    token: str
    user: dict[str, Any] = field(default_factory=dict)

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


async def login(client: httpx.AsyncClient, base_url: str, email: str,
                password: str) -> Session:
    try:
        response = await client.post(f"{base_url}/api/auth/login",
                                     json={"email": email, "password": password})
    except httpx.RequestError as exc:
        raise SetupError(
            f"could not reach the API at {base_url} ({exc.__class__.__name__}).\n"
            f"Start the stack first:  docker compose up -d\n"
            f"Then wait for  GET {base_url}/health  to answer."
        ) from exc

    if response.status_code == 401:
        raise SetupError(f"login refused for {email}. The demo account is "
                         f"{DEFAULT_EMAIL} / {DEFAULT_PASSWORD}; override with "
                         f"--email/--password.")
    if response.status_code >= 400:
        raise SetupError(f"login to {base_url} failed with HTTP {response.status_code}: "
                         f"{response.text[:200]}")

    payload = response.json()
    return Session(client=client, base_url=base_url, token=payload["access_token"],
                   user=payload.get("user") or {})


async def ask(session: Session, question: str, timeout: float,
              history: list[dict[str, str]] | None = None) -> Observed:
    """One chat turn, consumed incrementally off the SSE stream."""
    observed = Observed()
    started = time.monotonic()

    try:
        async with asyncio.timeout(timeout):
            async with session.client.stream(
                "POST", f"{session.base_url}/api/chat",
                json={"question": question, "history": history or []},
                headers={**session.headers, "Accept": "text/event-stream"},
                timeout=httpx.Timeout(timeout, read=timeout),
            ) as response:
                if response.status_code >= 400:
                    await response.aread()
                    observed.error = (f"POST /api/chat returned HTTP "
                                      f"{response.status_code}: {response.text[:200]}")
                    return observed

                # Line by line rather than `await response.aread()`: the stream is the product
                # surface, and buffering it here would hide a server that only flushes at the
                # end.
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    _absorb(observed, line[len("data:"):].strip())
    except TimeoutError:
        observed.error = f"timed out after {timeout:g}s waiting for the card"
    except httpx.RequestError as exc:
        observed.error = f"transport error: {exc.__class__.__name__}: {exc}"
    finally:
        observed.latency_ms = int((time.monotonic() - started) * 1000)

    return observed


def _absorb(observed: Observed, raw: str) -> None:
    """Fold one SSE payload into the observation. Unknown event types are ignored."""
    if not raw:
        return
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        observed.error = f"unparseable SSE payload: {raw[:120]}"
        return

    match event.get("type"):
        case "tool_call":
            observed.tool_calls.append({"tool": event.get("tool"),
                                        "args": event.get("args") or {}})
        case "card":
            observed.card = event.get("card")
        case "error":
            observed.error = str(event.get("message"))
        case _:
            pass  # status, token and tool_result carry nothing an assertion reads


async def fetch_rows(session: Session, query_id: str, timeout: float) -> None | dict:
    """The grounded result set — the rows the chart is drawn from, not the prose."""
    response = await session.client.get(
        f"{session.base_url}/api/result/{query_id}",
        params={"limit": RESULT_PAGE_LIMIT},
        headers=session.headers,
        timeout=timeout,
    )
    if response.status_code != 200:
        return None
    return response.json()


async def establish_history(session: Session, case: dict,
                            timeout: float) -> tuple[list[dict[str, str]], Observed | None]:
    """Replay a case's prior turns, returning the history its question is then asked against."""
    history: list[dict[str, str]] = []
    for prior in case.get("history") or []:
        observed = await ask(session, str(prior), timeout, history)
        if not observed.card or not observed.narrative.strip():
            reason = observed.error or "the turn produced no narrative to carry forward"
            return history, Observed(
                error=f"set-up turn {prior!r} never answered ({reason}), so the follow-up "
                      f"was never asked",
                latency_ms=observed.latency_ms)
        history += [{"role": "user", "content": str(prior)},
                    {"role": "assistant", "content": observed.narrative}]
    return history, None


async def run_case(session: Session, case: dict, suite: str, timeout: float,
                   semaphore: asyncio.Semaphore) -> CaseResult:
    async with semaphore:
        # The semaphore is held across the whole conversation on purpose: a follow-up must see
        # its own prelude, not interleave with three other cases' turns.
        history, broken = await establish_history(session, case, timeout)
        if broken is not None:
            return grade.grade(case, broken, suite)

        # Latency is the graded turn's alone.
        observed = await ask(session, str(case["question"]), timeout, history)

        if observed.card and observed.card.get("query_id"):
            try:
                page = await fetch_rows(session, observed.card["query_id"], timeout)
            except httpx.RequestError as exc:
                page = None
                observed.error = observed.error or f"GET /api/result failed: {exc}"
            if page:
                observed.rows = page.get("rows") or []
                observed.columns = page.get("columns") or []

        return grade.grade(case, observed, suite)


# ---------------------------------------------------------------------------- reporting

def print_case(result: CaseResult, style: Style, verbose: bool) -> None:
    guarantee = result.suite == "adversarial"
    if result.passed:
        marker = style.ok("PASS ")
    elif guarantee:
        # A failing adversarial case is a broken guarantee, not a drifted number.
        marker = style.alarm("FAIL!")
    else:
        marker = style.bad("FAIL ")

    seconds = result.latency_ms / 1000.0
    question = " ".join(result.question.split())
    if len(question) > 68:
        question = question[:65] + "..."
    print(f"{marker} {result.suite[:4]:<4} {result.case_id:<38} "
          f"{seconds:5.1f}s  {style.dim(question)}")

    for failure in result.failures:
        text = f"        - {failure.check}: {failure.message}"
        print(style.alarm(text) if guarantee else style.bad(text))

    if verbose:
        print(style.dim(f"        status={result.status!r} tools={result.tools_called} "
                        f"query_id={result.query_id!r} rows={result.row_count}"))


_FAMILY_BLURB = {
    "grounded": "rows from the result cache — the architecture",
    "prose":    "the narrative — the model",
    "routing":  "tools, dimensions, chart and status — the plan",
    "transport": "the turn never arrived — infrastructure, not an answer",
}


def print_family_rates(results: list[CaseResult], style: Style) -> None:
    """Pass rates per check family, which is the resolution the case-level score destroys."""
    rates = family_rates(results)
    if not rates:
        return
    print()
    print("pass rate by check family:")
    for name in FAMILIES:
        if name not in rates:
            continue
        passed, total = rates[name]
        rate = 100.0 * passed / total
        line = (f"  {name:<10} {passed:>4}/{total:<4} checks  ({rate:5.1f}%)   "
                f"{_FAMILY_BLURB[name]}")
        print(style.ok(line) if passed == total else style.dim(line))

    grounded, prose = rates.get("grounded"), rates.get("prose")
    if grounded and prose:
        print(style.bold(
            # ASCII arrow deliberately: this line is the one a reader quotes, and a plain cp1252
            # console (the Windows default) cannot encode a real arrow at all.
            f"  -> grounded {100.0 * grounded[0] / grounded[1]:.0f} % vs prose "
            f"{100.0 * prose[0] / prose[1]:.0f} % — the gap is the model, "
            f"the floor is the architecture"))


def print_summary(results: list[CaseResult], style: Style) -> None:
    print()
    print("-" * 78)

    for suite in ("golden", "adversarial"):
        subset = [r for r in results if r.suite == suite]
        if not subset:
            continue
        passed = sum(1 for r in subset if r.passed)
        rate = 100.0 * passed / len(subset)
        line = f"{suite:<12} {passed:>3}/{len(subset):<3} passed  ({rate:5.1f}%)"
        print(style.ok(line) if passed == len(subset) else style.bad(line))

    passed = sum(1 for r in results if r.passed)
    rate = 100.0 * passed / len(results) if results else 0.0
    print(style.bold(f"{'overall':<12} {passed:>3}/{len(results):<3} passed  "
                     f"({rate:5.1f}%)"))

    latencies = [r.latency_ms / 1000.0 for r in results]
    if latencies:
        ordered = sorted(latencies)
        p95 = ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]
        print(f"{'latency':<12} mean {statistics.mean(latencies):.1f}s   "
              f"median {statistics.median(latencies):.1f}s   p95 {p95:.1f}s")

    print_family_rates(results, style)

    categories = Counter(failure.check for r in results for failure in r.failures)
    if categories:
        print()
        print("failures by check:")
        for check, count in categories.most_common():
            print(f"  {check:<26} {count}  [{family_of(check)}]")

    breaches = [r for r in results if r.suite == "adversarial" and not r.passed]
    if breaches:
        print()
        print(style.alarm("BROKEN GUARANTEES — these are safety failures, not accuracy "
                          "failures:"))
        for result in breaches:
            checks = ", ".join(sorted({f.check for f in result.failures}))
            print(style.alarm(f"  {result.case_id} ({result.category or 'uncategorised'}): "
                              f"{checks}"))


def write_json(path: Path, results: list[CaseResult], session: Session,
               base_url: str, started_at: float) -> None:
    record = {
        "started_at": started_at,
        "finished_at": time.time(),
        "base_url": base_url,
        "user": {"email": session.user.get("email"),
                 "supplier_name": session.user.get("supplier_name")},
        "totals": {
            "cases": len(results),
            "passed": sum(1 for r in results if r.passed),
            "failed": sum(1 for r in results if not r.passed),
        },
        # Per-check rather than per-case: the conjunctive score above cannot distinguish a wrong
        # chart type from a fabricated total, and these two families measure two different
        # systems (the architecture and the model).
        "families": {name: {"passed": passed, "total": total,
                            "rate_pct": round(100.0 * passed / total, 1)}
                     for name, (passed, total) in family_rates(results).items()},
        "cases": [r.to_dict() for r in results],
    }
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------------- cli

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_eval.py",
        description="Run the golden and/or adversarial suites against a live API.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exit code 0 only when every case passed; 1 on failures; 2 when the run "
               "could not start (API down, bad credentials, malformed suite).",
    )
    parser.add_argument("--adversarial", action="store_true",
                        help="run the adversarial suite instead of the golden one")
    parser.add_argument("--all", action="store_true", help="run both suites")
    parser.add_argument("--base-url", default=os.environ.get("SOLVIGO_API_URL",
                                                             DEFAULT_BASE_URL),
                        help=f"API root (env SOLVIGO_API_URL, default {DEFAULT_BASE_URL})")
    parser.add_argument("--email", default=DEFAULT_EMAIL, help="demo account e-mail")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="demo account password")
    parser.add_argument("--case", action="append", dest="case_ids", metavar="ID",
                        help="run only this case id; repeatable")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY,
                        metavar="N", help=f"parallel turns (default {DEFAULT_CONCURRENCY})")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS,
                        metavar="SECONDS", help="per-case timeout "
                                                f"(default {DEFAULT_TIMEOUT_SECONDS:g})")
    parser.add_argument("--json", dest="json_path", type=Path, metavar="PATH",
                        help="write the machine-readable run record here")
    parser.add_argument("--no-color", action="store_true", help="never emit ANSI codes")
    parser.add_argument("--verbose", action="store_true",
                        help="print status, tools and query_id under every case")
    return parser


def select_suites(args: argparse.Namespace) -> list[str]:
    if args.all:
        return ["golden", "adversarial"]
    return ["adversarial"] if args.adversarial else ["golden"]


def load_cases(suites: list[str], case_ids: list[str] | None) -> list[tuple[str, dict]]:
    wanted = set(case_ids or [])
    selected: list[tuple[str, dict]] = []
    for suite in suites:
        loaded = cases.load(suite)
        for case in loaded.cases:
            if not wanted or case["id"] in wanted:
                selected.append((suite, case))

    if wanted:
        missing = wanted - {case["id"] for _, case in selected}
        if missing:
            raise SetupError(f"no such case id(s) in {suites}: {sorted(missing)}")
    if not selected:
        raise SetupError(f"no cases selected from {suites}")
    return selected


def assert_vocabulary_is_graded() -> None:
    """Refuse to run if a suite key has no grader."""
    vocabulary = cases.GOLDEN_EXPECT_KEYS | cases.ADVERSARIAL_EXPECT_KEYS
    ungraded = vocabulary - grade.GRADED_KEYS
    if ungraded:
        raise SetupError(f"grade.py implements no check for {sorted(ungraded)} — those "
                         f"expectations would silently pass. Refusing to run.")

    # Same argument one level down.
    unclassified = grade.GRADED_KEYS - set(grade.CHECK_FAMILIES)
    if unclassified:
        raise SetupError(f"grade.py grades {sorted(unclassified)} but assigns them no check "
                         f"family — they would be reported under 'routing' by default. "
                         f"Refusing to run.")


async def run(args: argparse.Namespace, selected: list[tuple[str, dict]],
              style: Style) -> int:
    started_at = time.time()
    limits = httpx.Limits(max_connections=max(args.concurrency * 2, 8))

    async with httpx.AsyncClient(timeout=args.timeout, limits=limits,
                                 follow_redirects=True) as client:
        session = await login(client, args.base_url, args.email, args.password)
        print(f"{args.base_url}  as {session.user.get('email')} "
              f"({session.user.get('supplier_name')})")
        print(f"{len(selected)} case(s), concurrency {args.concurrency}, "
              f"timeout {args.timeout:g}s")
        print()

        semaphore = asyncio.Semaphore(max(1, args.concurrency))
        tasks = [asyncio.create_task(run_case(session, case, suite, args.timeout, semaphore))
                 for suite, case in selected]

        results: list[CaseResult] = []
        for task in asyncio.as_completed(tasks):
            result = await task
            results.append(result)
            print_case(result, style, args.verbose)

    # Report in suite order regardless of the order they finished in, so two runs of the same
    # selection produce comparable output.
    order = {case["id"]: index for index, (_, case) in enumerate(selected)}
    results.sort(key=lambda r: order.get(r.case_id, 0))

    print_summary(results, style)
    if args.json_path:
        write_json(args.json_path, results, session, args.base_url, started_at)
        print(f"\nrun record written to {args.json_path}")

    return 0 if all(r.passed for r in results) else 1


def main(argv: list[str] | None = None) -> int:
    # Windows consoles still default to cp1252, which cannot encode "ö" — and every question in
    # the suites is Swedish.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args(argv)
    style = Style(enabled=not args.no_color and sys.stdout.isatty()
                  and os.environ.get("NO_COLOR") is None)

    try:
        assert_vocabulary_is_graded()
        selected = load_cases(select_suites(args), args.case_ids)
        return asyncio.run(run(args, selected, style))
    except cases.CaseError as exc:
        print(f"suite is malformed:\n{exc}", file=sys.stderr)
        return 2
    except SetupError as exc:
        print(f"cannot run: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
