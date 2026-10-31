"""Decision-support UI. Owner: Reine (T2).

    streamlit run app/streamlit_app.py

Reads runs/*.json (+ runs/live/*.json) and eval/results/summary.csv + meta.json. Panels:
  Header  decided-by badge, reviewer verdict badge, red banner when the fallback fired
1. Scenario: flight card, every Tagged value with its source tag colour-coded
2. Negotiation: per round, ATC / PILOT / GROUND positions, invalid messages never hidden
3. Checks: rules-engine PASS/FAIL matrix, reviewer re-derivation, fallback block
4. Recommendation: chosen option or escalation, Approve / Reject -> human_decision log event
Evaluation tab (summary.csv long format) and Consensus-log tab. Sidebar presets: Showcase AA334
and Failure case. The tool recommends; the human decides. It never executes anything.

Environment overrides: RUN_DIRS (os.pathsep-separated), EVAL_RESULTS_DIR.
When no run files exist, the sample fixtures in tests/fixtures/sample_run/ are offered, clearly
labelled, and decisions on them are not written.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app import loaders as L  # noqa: E402

PANEL_ERRORS: list[str] = []


def panel(name: str):
    """Decorator: an exception inside a panel renders as a warning naming it, never a crash."""

    def wrap(fn):
        def inner(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - the UI must degrade, not crash
                PANEL_ERRORS.append(f"{name}: {exc}")
                st.warning(f"{name}: could not render ({type(exc).__name__}: {exc})")
        return inner

    return wrap


def run_dirs() -> tuple[str, ...]:
    env = os.getenv("RUN_DIRS")
    return tuple(d for d in env.split(os.pathsep) if d) if env else L.RUN_DIRS


@st.cache_data(show_spinner=False)
def cached_run(path: str, mtime: float) -> dict:  # mtime is part of the cache key
    return L.load_run(path)


def get_run(path: Path) -> dict:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {"_load_error": f"file not found: {path}"}
    return cached_run(str(path), mtime)


def chips(ids, colour: str) -> str:
    ids = list(ids or [])
    if not ids:
        return "_none_"
    return " ".join(f":{colour}-badge[{str(i).replace(']', '')}]" for i in ids)


def source_style(df: pd.DataFrame, col: str = "source"):
    def colour(v):
        return f"background-color: {L.source_colour(v)}; color: white; font-weight: 600"

    return df.style.map(colour, subset=[col])


def passfail_style(df: pd.DataFrame, chosen: str | None = None):
    def colour(v):
        if v == "PASS":
            return "background-color: #c8e6c9; color: #1b5e20"
        if v == "FAIL":
            return "background-color: #ffcdd2; color: #b71c1c; font-weight: 700"
        return ""

    sty = df.style.map(colour)
    if chosen is not None and chosen in df.index:
        sty = sty.apply(lambda row: ["outline: 2px solid #1565c0" if row.name == chosen else ""
                                     for _ in row], axis=1)
    return sty


def table(rows, **kwargs):
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, **kwargs)


# ---------------------------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------------------------


def sidebar() -> tuple[Path | None, bool]:
    """Returns (selected run path or None, failure preset active)."""
    st.sidebar.title("Disruption negotiation")
    st.sidebar.caption("LLMs negotiate, code decides, every decision traces to a rule and a "
                       "data field, and a human approves.")
    real = L.list_runs(run_dirs())
    show_samples = st.sidebar.checkbox("Include sample fixtures", value=not real,
                                       help="Hand-authored sample runs in tests/fixtures/"
                                            "sample_run/. Not produced by the CLI.")
    runs = real + (L.list_runs((str(L.SAMPLE_DIR),)) if show_samples else [])
    if not real:
        st.sidebar.info(f"No runs in {', '.join(run_dirs())}. Produce one with:\n\n"
                        f"`{L.CLI_HINT}`")
    if not runs:
        return None, False

    labels = [label for label, _ in runs]
    paths = {label: p for label, p in runs}
    by_path = {str(p): label for label, p in runs}
    st.session_state.setdefault("preset", None)
    if st.session_state.get("run_select") not in labels:
        st.session_state["run_select"] = labels[0]

    def go(path: Path | None, preset: str | None):
        if path is not None and str(path) in by_path:
            st.session_state["run_select"] = by_path[str(path)]
            st.session_state["preset"] = preset

    showcase = L.showcase_preset(runs)
    failure = L.failure_preset(runs)
    c1, c2 = st.sidebar.columns(2)
    c1.button("Showcase AA334", on_click=go, args=(showcase, "showcase"),
              disabled=showcase is None, width="stretch",
              help="First run whose file name contains AA334")
    c2.button("Failure case", on_click=go, args=(failure, "failure"),
              disabled=failure is None, width="stretch",
              help="runs/failure_showcase.json, else the forced-deadlock run, else the first "
                   "run where the fallback fired")
    st.sidebar.selectbox("Run (newest first)", labels, key="run_select",
                         on_change=lambda: st.session_state.update(preset=None))
    selected = paths.get(st.session_state["run_select"])
    return selected, st.session_state.get("preset") == "failure"


# ---------------------------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------------------------


@panel("Header")
def header(run: dict, path: Path):
    sid = L.safe_get(run, "meta.scenario_id") or L.safe_get(run, "scenario.scenario_id") or path.stem
    st.title(sid)
    meta = L.safe_get(run, "meta", {})
    bits = [f"agents: **{meta.get('agents', '—')}**", f"model: **{meta.get('model') or '—'}**",
            f"cost: **${float(meta.get('cost_usd') or 0):.4f}**",
            f"latency: **{meta.get('latency_s', '—')} s**", f"file: `{path.name}`"]
    st.markdown(" · ".join(bits))
    decided = L.safe_get(run, "recommendation.decided_by")
    rev = L.reviewer_info(run)
    verdict = rev.get("verdict")
    c1, c2, c3 = st.columns([1, 1, 3])
    with c1:
        st.badge(f"decided by: {decided or 'unknown'}",
                 color="green" if decided == "consensus" else "orange" if decided else "gray")
    with c2:
        st.badge(f"reviewer: {verdict}" if verdict else "reviewer not run",
                 color=L.verdict_colour(verdict))
    with c3:
        human = L.human_state(L.resolve_log_path(run, path))
        st.badge(f"human decision: {(human or {}).get('decision', 'pending')}", color="blue")
    if L.is_sample(path) or meta.get("sample_fixture"):
        st.warning("SAMPLE FIXTURE: hand-authored example in the documented run layout, not an "
                   "output of src/cli.py. Flight rows follow the data; every other number is "
                   "illustrative.")
    fb = L.fallback_info(run)
    if fb["fired"]:
        st.error(f"Deterministic fallback fired: **{fb.get('reason') or 'reason not recorded'}**"
                 f" — the recommendation was not decided by agent consensus.")
    if rev.get("placeholder"):
        st.caption("Reviewer output is a placeholder (reviewer not implemented in this run).")


# ---------------------------------------------------------------------------------------------
# Panel 1: Scenario
# ---------------------------------------------------------------------------------------------


@panel("Scenario")
def panel_scenario(run: dict):
    st.header("1 · Scenario")
    sc = L.safe_get(run, "scenario", {})
    f = L.safe_get(sc, "flight", {})
    g = lambda k: L.safe_get(f, k)  # noqa: E731
    c = st.columns(6)
    c[0].metric("Flight", f"{g('AIRLINE') or ''}{g('FLIGHT_NUMBER') or '—'}")
    c[1].metric("Tail", g("TAIL_NUMBER") or "—")
    c[2].metric("Route", f"{g('ORIGIN_AIRPORT') or '?'} → {g('DESTINATION_AIRPORT') or '?'}")
    c[3].metric("Sched dep / arr",
                f"{L.fmt_minutes(g('SCHEDULED_DEPARTURE'))} / {L.fmt_minutes(g('SCHEDULED_ARRIVAL'))}")
    c[4].metric("Departure delay", f"{L.fmt_value(g('DEPARTURE_DELAY'))} min")
    date = "-".join(str(g(k)) for k in ("YEAR", "MONTH", "DAY") if g(k) is not None)
    c[5].metric("Date", date or "—")
    causes = {k.replace("_DELAY", "").replace("_", " ").lower(): g(k) for k in
              ("WEATHER_DELAY", "LATE_AIRCRAFT_DELAY", "AIR_SYSTEM_DELAY", "AIRLINE_DELAY",
               "SECURITY_DELAY") if g(k)}
    if causes:
        st.caption("Delay causes (min, data): " +
                   ", ".join(f"{k} {L.fmt_value(v)}" for k, v in causes.items()))
    if g("ARRIVAL_DELAY") is not None:
        st.caption(f"Real outcome: arrival delay {L.fmt_value(g('ARRIVAL_DELAY'))} min. Not shown "
                   "to the agents; used only to compare in the evaluation. Times are minutes "
                   "since midnight, shown as HH:MM.")

    counts = L.source_counts(sc)
    m = st.columns(4)
    for col, tag in zip(m, L.SOURCE_TAGS):
        col.markdown(f"<span style='color:{L.source_colour(tag)};font-weight:700'>■ {tag}</span>",
                     unsafe_allow_html=True)
        col.metric(f"{tag} values", counts.get(tag, 0), label_visibility="collapsed")
    rows = L.tagged_rows(sc) + L.untagged_rows(sc)
    if rows:
        df = pd.DataFrame([(fld, L.fmt_value(v), src, note) for fld, v, src, note in rows],
                          columns=["field", "value", "source", "note"])
        st.dataframe(source_style(df), hide_index=True, width="stretch")
    else:
        st.info("No tagged values in this scenario.")

    cols = st.columns(2)
    with cols[0].expander(f"Downstream legs ({len(L.safe_get(sc, 'downstream_legs', []) or [])})"):
        legs = L.safe_get(sc, "downstream_legs", [])
        if legs:
            table(legs, width="stretch")
            st.caption("Same tail later that day (data, partial: only delayed legs exist).")
        else:
            st.write("No downstream legs listed for this tail.")
    with cols[1].expander(f"Alternates ({len(L.safe_get(sc, 'alternates', []) or [])})"):
        alts = L.safe_get(sc, "alternates", [])
        if alts:
            table(alts, width="stretch")
        else:
            st.write("No alternates listed.")
    cols = st.columns(2)
    with cols[0].expander("Gates (synthetic)"):
        st.json(L.safe_get(sc, "gates", {}) or {})
    with cols[1].expander(f"Connections (estimated, {len(L.safe_get(sc, 'connections', []) or [])})"):
        conns = L.safe_get(sc, "connections", [])
        if conns:
            table(conns, width="stretch")
        else:
            st.write("No connections listed.")


# ---------------------------------------------------------------------------------------------
# Panel 2: Negotiation
# ---------------------------------------------------------------------------------------------


def agent_column(msg: dict | None, role: str, invalid: list[dict]):
    st.subheader(role)
    if msg is None:
        if invalid:
            st.error(f"Invalid message ({', '.join(str(i.get('reason', '?')) for i in invalid)}): "
                     "rejected, not repaired. See below.")
        else:
            st.caption("No message from this agent in this round.")
        return
    st.markdown("**Acceptable** " + chips(L.safe_get(msg, "acceptable", []), "green"))
    vetoes = L.safe_get(msg, "vetoes", []) or []
    if vetoes:
        st.markdown("**Vetoes**")
        for v in vetoes:
            cited = L.safe_get(v, "cited_field")
            st.markdown(f":red-badge[{L.safe_get(v, 'candidate_id', '?')}] "
                        f"{L.safe_get(v, 'reason', '')}" + (f" (`{cited}`)" if cited else ""))
    else:
        st.markdown("**Vetoes** _none_")
    ranking = L.ranking_for(msg)
    st.markdown("**Top 3**")
    for r in ranking[:3]:
        try:
            score = min(1.0, max(0.0, float(r.get("score", 0))))
        except (TypeError, ValueError):
            score = 0.0
        st.progress(score, text=f"{r.get('candidate_id', '?')} — {score:.2f}")
        st.caption(str(r.get("rationale", "")))
        cited = r.get("cited_fields") or []
        if cited:
            st.markdown(" ".join(f"`{c}`" for c in cited))
    if len(ranking) > 3:
        with st.expander(f"All {len(ranking)} scores"):
            table([{"candidate_id": r.get("candidate_id"), "score": r.get("score"),
                    "rationale": r.get("rationale"),
                    "cited_fields": ", ".join(r.get("cited_fields") or [])} for r in ranking],
                  width="stretch")


@panel("Negotiation")
def panel_negotiation(run: dict):
    st.header("2 · Negotiation")
    turns = L.safe_get(run, "turns", []) or []
    explanation = L.round_explanation(run)
    if not turns:
        st.info(explanation)
        return
    passing = L.rules_pass_ids(L.safe_get(run, "rule_results", []))
    for t in turns:
        rnd = L.safe_get(t, "round", "?")
        st.subheader(f"Round {rnd}")
        msgs = {L.safe_get(m, "agent"): m for m in L.safe_get(t, "messages", []) or []}
        invalid = [i for i in L.safe_get(t, "invalid_messages", []) or [] if isinstance(i, dict)]
        cols = st.columns(3)
        for col, role in zip(cols, L.ROLES):
            with col:
                agent_column(msgs.get(role), role, [i for i in invalid if i.get("agent") == role])
        if invalid:
            st.markdown(f":red[**{len(invalid)} invalid message(s) in round {rnd}**] — logged "
                        "with raw text and error; never repaired.")
            with st.expander(f"Invalid messages, round {rnd}", expanded=True):
                for i in invalid:
                    st.markdown(f"**{i.get('agent', '?')}** · reason `{i.get('reason', '?')}`")
                    for k, v in i.items():
                        if k in ("agent", "reason", "raw_text", "error"):
                            continue
                        st.caption(f"{k}: {L.fmt_value(v)}")
                    st.markdown("raw text")
                    st.code(str(i.get("raw_text", "(not recorded)")), language="json",
                            wrap_lines=True)
                    st.markdown("error")
                    st.code(str(i.get("error", "(not recorded)")), language="text",
                            wrap_lines=True)
        else:
            st.caption(f"Invalid messages in round {rnd}: 0")
        inter = L.safe_get(t, "intersection", []) or []
        rp = [c for c in inter if c in passing]
        st.markdown(f"**Intersection of acceptable sets:** {chips(inter, 'blue')} · "
                    f"**of which pass every rule:** {chips(rp, 'green')}")
        st.divider()
    if explanation:
        st.info(explanation)


# ---------------------------------------------------------------------------------------------
# Panel 3: Checks
# ---------------------------------------------------------------------------------------------


@panel("Checks")
def panel_checks(run: dict, failure_preset: bool):
    st.header("3 · Checks")
    if failure_preset:
        st.error(L.how_user_knows(run))
    else:
        st.caption(L.how_user_knows(run))
    rules = L.safe_get(run, "rule_results", []) or []
    chosen = L.safe_get(run, "recommendation.chosen.candidate_id")
    st.subheader("Rules engine (deterministic)")
    if rules:
        mat = L.rule_matrix(rules)
        st.dataframe(passfail_style(mat, chosen), width="stretch")
        st.caption("One row per candidate, one column per rule ID. Outlined row = chosen. "
                   "The agents never see these results.")
        options = list(mat.index)
        default = options.index(chosen) if chosen in options else 0
        cid = st.selectbox("Rule detail for candidate", options, index=default)
        detail = L.rule_detail(rules, cid)
        if detail:
            df = pd.DataFrame(detail)
            df["passed"] = df["passed"].map({True: "PASS", False: "FAIL"}).fillna("?")
            for col in ("observed", "threshold"):
                df[col] = df[col].map(L.fmt_value)
            st.dataframe(source_style(df), hide_index=True, width="stretch")
    else:
        st.info("No rule results recorded in this run.")

    st.subheader("Independent safety reviewer")
    rev = L.reviewer_info(run)
    verdict = rev.get("verdict")
    colour = L.verdict_colour(verdict)
    st.markdown(f"Verdict: :{colour}-badge[{verdict or 'reviewer not run'}]")
    for h in rev.get("history") or []:
        st.markdown(f"- pass on **{L.safe_get(h, 'candidate_id', '?')}**: "
                    f":{L.verdict_colour(L.safe_get(h, 'verdict'))}-badge"
                    f"[{L.safe_get(h, 'verdict', '?')}]")
    notes = rev.get("notes") or L.safe_get(run, "recommendation.reviewer_notes", []) or []
    for n in notes:
        st.markdown(f"- {n}")
    for key, title in (("re_derived", "Re-derived checks"),
                       ("cited_mismatches", "Cited-value mismatches"),
                       ("engine_disagreements", "Engine vs reviewer disagreements")):
        rows = rev.get(key)
        if rows:
            st.markdown(f"**{title}**")
            table(rows, width="stretch")

    fb = L.fallback_info(run)
    label = (f"Deterministic fallback — FIRED ({fb.get('reason') or 'reason not recorded'})"
             if fb["fired"] else "Deterministic fallback — not fired")
    with st.expander(label, expanded=failure_preset or fb["fired"]):
        if not fb["fired"]:
            st.write("Agents reached consensus on a rule-passing option; the fallback was not "
                     "needed.")
        else:
            c = st.columns(4)
            c[0].metric("Reason", fb.get("reason") or "—")
            c[1].metric("Picked", fb.get("candidate_id") or chosen or "—")
            c[2].metric("Objective", L.fmt_value(fb.get("objective")))
            c[3].metric("Eligible options", L.fmt_value(fb.get("n_eligible")))
            if fb.get("weights"):
                st.caption(f"Weights: {L.fmt_value(fb['weights'])}")
            excluded = fb.get("excluded") or []
            if excluded:
                st.markdown("**Excluded**")
                if all(isinstance(e, dict) for e in excluded):
                    table(excluded, width="stretch")
                else:
                    st.write(", ".join(map(str, excluded)))


# ---------------------------------------------------------------------------------------------
# Panel 4: Recommendation
# ---------------------------------------------------------------------------------------------


@panel("Recommendation")
def panel_recommendation(run: dict, path: Path):
    st.header("4 · Recommendation")
    rec = L.safe_get(run, "recommendation", {}) or {}
    chosen = rec.get("chosen")
    verdict = L.reviewer_info(run).get("verdict")
    if not chosen:
        st.error("No option passes engine and reviewer — escalate to duty manager.")
    else:
        with st.container(border=True):
            st.subheader(f"{chosen.get('candidate_id', '?')}  ·  {chosen.get('kind', '?')}")
            c = st.columns(3)
            c[0].metric("Est. delay (model estimate)", f"{L.fmt_value(chosen.get('est_delay_min'))} min")
            c[1].metric("Est. knock-on (model estimate)",
                        f"{L.fmt_value(chosen.get('est_knock_on_min'))} min")
            c[2].metric("Rounds used", L.fmt_value(rec.get("rounds_used")))
            st.caption(f"params: {L.fmt_value(chosen.get('params'))} · decided by "
                       f"{rec.get('decided_by', 'unknown')} · reviewer {verdict or 'not run'}")
    st.markdown(L.rests_on_line(L.source_counts(L.safe_get(run, "scenario", {}))))

    log_path = L.resolve_log_path(run, path)
    state = L.human_state(log_path)
    if state is None:
        st.info("Human decision: **pending**. This tool recommends; it never executes.")
    elif state.get("decision") == "unknown":
        st.warning(f"Human decision: unknown (log unreadable: {state.get('error')}).")
    else:
        st.success(f"Human decision: **{state.get('decision')}** by {state.get('by', '?')} at "
                   f"{state.get('ts', '?')}" + (f" — “{state['note']}”" if state.get("note") else ""))

    sample = L.is_sample(path)  # read-only by location: never write into tests/fixtures/
    name = st.text_input("Your name", key=f"by_{path}")
    note = st.text_input("Note / justification", key=f"note_{path}")
    needs_note = verdict == "REJECT"
    if needs_note:
        st.warning("The reviewer REJECTED this recommendation. Approving it requires a written "
                   "justification.")
    approve_disabled = sample or not chosen or (needs_note and not note.strip())
    c1, c2, _ = st.columns([1, 1, 4])
    sid = rec.get("scenario_id") or L.safe_get(run, "meta.scenario_id") or path.stem
    if c1.button("Approve", type="primary", disabled=approve_disabled, key=f"approve_{path}"):
        decide(log_path, sid, "approved", name, note)
    if c2.button("Reject", disabled=sample, key=f"reject_{path}"):
        decide(log_path, sid, "rejected", name, note)
    if sample:
        st.caption("Sample fixture: decisions are not written (the fixture log stays unchanged).")
    else:
        st.caption(f"Decisions are appended to `{log_path}` as a human_decision event; the run "
                   "file is never modified.")


def decide(log_path, sid, decision, name, note):
    try:
        L.append_human_decision(log_path, sid, decision, name, note)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not write the decision: {exc}")
        return
    st.rerun()


# ---------------------------------------------------------------------------------------------
# Evaluation tab
# ---------------------------------------------------------------------------------------------


@panel("Evaluation")
def panel_evaluation():
    st.header("Evaluation")
    d = L.eval_dir()
    summary = L.load_summary(d / "summary.csv")
    meta = L.load_meta(d / "meta.json")
    if summary is None:
        st.info(f"Evaluation not run (no summary.csv in `{d}`). Run:\n\n`{L.EVAL_HINT}`")
        return
    if L.is_sample(d) or meta.get("sample_fixture"):
        st.warning("SAMPLE FIXTURE evaluation: illustrative numbers, not real results.")
    if meta.get("guard_stopped"):
        st.error(f"Evaluation stopped early by the cost/time guard: {meta.get('reason') or '?'} "
                 f"— {meta.get('n_completed', '?')} of {meta.get('n', '?')} rows completed.")
    st.caption(" · ".join(f"{k}: {meta[k]}" for k in ("model", "seed", "n", "n_completed",
                                                      "cost", "git_sha") if k in meta))
    cards = L.headline_metrics(summary)
    cols = st.columns(len(cards))
    for col, (metric, label, value) in zip(cols, cards):
        unit = L.safe_get(summary, f"{metric}.unit", "fraction" if metric.endswith("_rate")
                          or metric == "fallback_rate_total" else "")
        col.metric(label, L.fmt_metric(value, unit),
                   help=L.safe_get(summary, f"{metric}.definition") or
                   ("sum of all fallback_rate_* metrics" if metric == "fallback_rate_total"
                    else None))
    mva = L.modelled_vs_actual(summary)
    if mva:
        st.subheader("Modelled vs actual delay")
        st.caption("Modelled values are estimates of the delay the recommendation would induce; "
                   "actual values are what happened. They are not the same quantity.")
        for metric, r in mva:
            st.markdown(f"**{metric}**: {L.fmt_metric(r.get('value'), r.get('unit', ''))}"
                        + (f" (n={r['n']})" if r.get("n") is not None else ""))
            if r.get("note"):
                st.caption(r["note"])
    st.subheader("All metrics")
    df = pd.DataFrame([{"metric": k, **{c: r.get(c) for c in
                                        ("value", "unit", "n", "definition", "note")}}
                       for k, r in summary.items()])
    df["value"] = df["value"].map(L.fmt_value)
    df["n"] = df["n"].map(lambda v: "" if v is None else L.fmt_value(v))
    st.dataframe(df, hide_index=True, width="stretch")


# ---------------------------------------------------------------------------------------------
# Consensus-log tab
# ---------------------------------------------------------------------------------------------


@panel("Consensus log")
def panel_log(run: dict, path: Path):
    st.header("Consensus log")
    log_path = L.resolve_log_path(run, path)
    events, err = L.read_log(log_path)
    st.caption(f"`{log_path}` · append-only JSONL · {len(events)} events")
    if err:
        st.warning(err)
    if not events:
        st.info("No log events found for this run.")
        return
    kinds = sorted({str(e.get("event")) for e in events})
    default = [k for k in kinds if k != "rule_check"] or kinds
    chosen = st.multiselect("Events", kinds, default=default)
    rows = [{"ts": e.get("ts"), "event": e.get("event"),
             "details": L.fmt_value({k: v for k, v in e.items()
                                     if k not in ("ts", "event", "scenario_id")})}
            for e in events if str(e.get("event")) in chosen]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    try:
        raw = Path(log_path).read_bytes()
        st.download_button("Download log (.jsonl)", raw, file_name=Path(log_path).name,
                           mime="application/jsonl")
    except OSError:
        pass


# ---------------------------------------------------------------------------------------------


def main():
    st.set_page_config(page_title="Disruption negotiation — decision support", layout="wide")
    PANEL_ERRORS.clear()
    path, failure = sidebar()
    tab_run, tab_eval, tab_log = st.tabs(["Run", "Evaluation", "Consensus log"])
    with tab_eval:
        panel_evaluation()
    if path is None:
        with tab_run:
            st.title("Disruption negotiation — decision support")
            st.info(f"No run selected. Produce one with `{L.CLI_HINT}`, or tick "
                    "'Include sample fixtures' in the sidebar.")
        return
    run = get_run(path)
    if "_load_error" in run:
        with tab_run:
            st.error(f"Could not read `{path}`: {run['_load_error']}")
        return
    with tab_run:
        header(run, path)
        panel_scenario(run)
        panel_negotiation(run)
        panel_checks(run, failure)
        panel_recommendation(run, path)
    with tab_log:
        panel_log(run, path)


if __name__ == "__main__":
    main()
