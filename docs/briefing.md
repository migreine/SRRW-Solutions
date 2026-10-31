# Project briefing: Autonomous SG 2026 Hackathon, Airbus Track, Challenge #2

Context for anyone (human or Claude) working on this repo. The official track brief and rubric are in
`problem statement/Autonomous SG 2026_Airbus Track.pdf` and win if anything here conflicts.

---

## 0. Team, schedule and current status

- **Team:** 4 people. 3 technical, 1 non-technical. Each has US$50 of Claude API credits (US$200 total).
- **Tooling:** every member has Claude Code. Most of the code will be written by Claude Code, with
  humans directing, reviewing and testing, so the plan should be built around parallel Claude Code
  sessions, not hand-written code.
- **Event day (31 Oct 2026, Singapore time):**

| Time | Event |
|---|---|
| 9:00 – 9:30 | Registration |
| 9:30 – 9:45 | Welcome address |
| 9:45 – 10:05 | Keynote |
| 10:05 – 10:10 | Sponsor's speech |
| 10:10 – 10:15 | Problem statements released |
| 10:15 – 16:15 | Continuous hacking sprint |
| **16:15** | **Submissions close** |
| 16:15 – 16:30 | Projects allotted to judges |
| 16:30 – 17:30 | Judging (3 judges per project, 3-minute presentation) |
| 17:30 – 18:00 | Awards and closing |

- **Status at 11:27:**
  - Challenge #2 chosen.
  - GitHub repo `migreine/SRRW-Solutions` (private) is set up with the data, the PDF, `.gitignore` and `.env.example`.
  - The data was profiled and its key claims were checked (section 4.5).
  - No application code yet.
  - Python 3.14.7 and `anthropic` SDK 1.2.0 are installed on one machine.
  - About **4 h 48 min of build time remain**.

---

## 1. Event and constraints

- **Event:** Autonomous SG 2026, Acacia Hackathon Society, National University of Singapore, 31 October 2026 (one day).
- **Track:** AI & Aerospace (Airbus).
- **Chosen challenge:** #2, Multi-Agent Air Traffic Negotiation. We compared it against #1 (satellite collision risk) and #5 (weather → airport capacity) and picked #2 because it has the highest score ceiling against the rubric.
- **Final presentation:** 3 minutes. Submission time is recorded, and earlier valid submission scores slightly better.
- **Team stance:** We're fine with difficulty. We want to win the track, not just submit.

---

## 2. The challenge brief (verbatim requirements)

**Question:** "How might AI help air traffic controllers, pilots and ground operations staff make faster and better decisions?"

**Context from the brief:** When a runway closes, weather delays occur or ground equipment fails, coordination today relies on human phone calls and manual software updates. That leads to cascading delays, excessive holding patterns and excessive fuel burn.

**Want to see:** A multi-agent communication framework in which ATC, Pilot and Ground Ops AI agents negotiate resolutions to real-time disruptions without human intervention until consensus is reached.

| Agent | Responsibilities (from the brief) |
|---|---|
| **ATC agent** | Runway wake separation, taxiway blockage, maximise sector throughput |
| **Pilot agent** | Preserve fuel reserves, ensure flight safety, minimise turbulence, protect passengers' connections |
| **Ground agent** | Optimise gate utilisation, avoid ground-crew overtime, minimise turnaround delays |

The three agents must exchange **structured data**, evaluate **cross-domain constraints**, and **converge on an agreed solution**. Required elements:
- structured messages
- explicit constraint checking
- a traceable consensus log
- a deterministic, non-AI fallback

**Must demonstrate:** agents negotiating a revised arrival time, gate assignment or flight plan adjustment **in under 3 turns**.

**Explicitly to avoid:**
1. Combining the three roles into a single prompt call.
2. LLM agents talking in endless, unconstrained loops with no convergence logic or turn limits.
3. Disregarding safety margins. Agents must not be allowed to accept solutions that ignore operational constraints.

**Data instruction:** use the US DOT 2015 flight delays data. Pick any row with `WEATHER_DELAY > 15` or `LATE_AIRCRAFT_DELAY > 20` and pass that row's parameters into the three agents. (We go further: one showcase row for the demo, plus hundreds of rows for evaluation.)

---

## 3. Judging rubric (drives every design decision)

Each criterion is scored 1–5 by each of 3 judges, then weighted. Judges are told to "reward sound restraint, not presentation polish" and to ask: **"Where does this fail, and how would your user know?"**

| Criterion | Weight | Strong | Weak |
|---|---|---|---|
| **Technical soundness** | 25% | Works end to end on input beyond the demo script. LLMs handle reading, retrieval, explanation and interaction. Solvers, rules and statistics handle optimisation, compliance logic and detection. Clear LLM / non-LLM split. | An LLM doing arithmetic, scheduling or legality checks, or a polished UI over a hard-coded scenario |
| **Problem realism** | 20% | A named user, what they do today without the tool, a believable cost in time, money or risk. A narrow workflow. | "An AI assistant for aviation" |
| **Honest evaluation** | 20% | Stated metrics, test data and results. Synthetic data labelled with its limits. At least one visible case where the system is wrong, uncertain or declines, with why and what would fix it. | Only success stories, untested accuracy claims |
| **Trust & traceability** | 20% | A qualified person can verify the output before acting. Claims trace to a rule, data field or timestamped signal. Missing evidence handled. The human stays in control. | Confident unsourced answers, replacing expert judgement |
| **Impact** | 10% | A credible before/after measure against a stated baseline. Measured improvement kept separate from estimates. | Large claims with no baseline |
| **Time discipline** | 5% | Earlier valid submission, focused pitch within 3 minutes | Late, rushed or over-time pitch |

**Implications:**
- An LLM never decides whether a proposal is legal or safe. Deterministic code does.
- An LLM never does the arithmetic (separation, fuel, duty-time, delay). It calls tools or reads results.
- Evaluation runs over many real rows, not one scripted scenario.
- Every recommendation shows which rule, data field and timestamp it rests on.
- The output is a **recommendation for a human to approve**, never an autonomous action.

---

## 4. Data

### 4.1 `data/flights.csv` (US DOT 2015, pre-filtered extract, ~38 MB)
- **358,774 rows, 31 columns:** `YEAR, MONTH, DAY, DAY_OF_WEEK, AIRLINE, FLIGHT_NUMBER, TAIL_NUMBER, ORIGIN_AIRPORT, DESTINATION_AIRPORT, SCHEDULED_DEPARTURE, DEPARTURE_TIME, DEPARTURE_DELAY, TAXI_OUT, WHEELS_OFF, SCHEDULED_TIME, ELAPSED_TIME, AIR_TIME, DISTANCE, WHEELS_ON, TAXI_IN, SCHEDULED_ARRIVAL, ARRIVAL_TIME, ARRIVAL_DELAY, DIVERTED, CANCELLED, CANCELLATION_REASON, AIR_SYSTEM_DELAY, SECURITY_DELAY, AIRLINE_DELAY, LATE_AIRCRAFT_DELAY, WEATHER_DELAY`.
- Times are local `hhmm` integers (e.g. `1305`; `2400` and midnight wrap-around occur). Delays are in minutes.
- **Every row already satisfies the brief's filter:**
  - 42,012 rows have a weather delay over 15 minutes.
  - 326,249 rows have a late-aircraft delay over 20 minutes.
- 11 months present; October missing. All airport codes are 3-letter IATA codes matching `airports.csv`.
- `TAIL_NUMBER` is present on every row. No cancelled or diverted flights.
- Busiest destinations: ORD 21,584, ATL 18,504, DFW 17,310, DEN 14,316, LAX 13,863, SFO 10,970, LAS 9,659, IAH 9,654.

**Limitations (must be stated in pitch and README):**
1. **Only delayed flights (~6% of 2015 traffic).** Flights per airport-hour measure *disruption intensity*, not runway demand or gate occupancy.
2. **Aircraft rotations are partial.** On-time legs are missing, so the Ground agent only sees delayed downstream legs.
3. **No cancellations or diversions** to benchmark against. We can compare against real `ARRIVAL_DELAY`.
4. **No aircraft type, gates, fuel, crew duty, passengers or connections.** These are estimated or synthetic and labelled.

### 4.2 `data/airports.csv`
- 322 rows: `IATA_CODE, AIRPORT, CITY, STATE, COUNTRY, LATITUDE, LONGITUDE`.
- **ECP, PBG and UST have no coordinates** (verified). Fill by hand or exclude.

### 4.3 `data/airlines.csv`
- 14 rows: `IATA_CODE, AIRLINE`.

### 4.4 Optional external data
- **FAA Aircraft Registry:** tail number → aircraft model → wake category. Some tails won't match, so use a conservative default and log it.

### 4.5 Verified facts and corrections (checked against the files on 31 Oct)
- 358,774 rows × 31 columns, months 1–9 and 11–12, zero cancellations or diversions.
- ECP, PBG and UST have no coordinates.
- **Showcase tail N469AA on 24 Apr 2015 (correction).** An earlier draft mixed departure and arrival delays. The actual values:

| Leg | Sched dep | Sched arr | Dep delay | Arr delay | Weather | Late aircraft |
|---|---|---|---|---|---|---|
| AA334 MFE→DFW | 11:16 | 12:55 | +114 | **+101** | 58 | 43 |
| AA1389 DFW→MEM | 13:48 | 15:22 | +111 | +102 | 0 | 85 |
| AA1389 MEM→DFW | 16:02 | 17:48 | +249 | +264 | 147 | 102 |
| AA1274 DFW→BWI | 18:35 | 22:45 | +288 | +256 | 23 | 233 |

  Use one metric consistently in the pitch: arrival 101 → 256, or departure 114 → 288.

---

## 5. Real vs. estimated

| Agent need | Source | Status |
|---|---|---|
| Disrupted flight: times, delays by cause, taxi times, distance, tail | `flights.csv` row | **Real** |
| Destination disruption intensity (delayed arrivals per hour) | Count of rows per destination-hour | **Real**, but a proxy, not demand |
| Taxiway congestion | `TAXI_OUT` / `TAXI_IN` vs airport median | **Real** proxy |
| Turnaround / knock-on chain | Same tail's later legs that day | **Real**, partial |
| Diversion alternates and distances | `airports.csv` coordinates | Real geometry |
| Wake category | FAA registry on tail, or airline-fleet default | Real if looked up, else assumed |
| Nominal arrival rate per airport | Published FAA airport rates | **Assumed, labelled** |
| Gate availability | Synthetic gate model per airport | **Synthetic, labelled** |
| Fuel on board / burn | Distance and air time × typical burn rate | **Estimated, labelled** |
| Crew duty state | Synthetic, constrained by regulation | **Synthetic, labelled** |
| Passenger connections | Same-airline departures 45–180 min after arrival at the hub | Estimated, partial |

Every synthetic value carries a `source: "synthetic" | "estimated" | "assumed" | "data"` tag that flows into the consensus log and the UI.

---

## 6. Architecture

**Principle: "LLMs negotiate and explain; deterministic code decides."**

1. **Scenario builder (deterministic).** A `flights.csv` row becomes a scenario object: the flight, destination disruption intensity, the tail's downstream chain, nearest alternates, and synthetic or estimated state with source tags.
2. **Three independent agents.** Each is a separate LLM call with its own system prompt and only its own domain's data. They rank and veto options in a strict JSON schema (Pydantic). They never compute legality.
3. **Fixed option menu (deterministic).** A bounded set of candidates:
   - a revised arrival slot ±N minutes
   - hold vs divert to alternate X
   - a gate swap
   - a speed adjustment or ground hold at origin
   - a swap of the next leg's aircraft
4. **Rules engine (deterministic, no LLM).** Every pass or fail cites a rule ID and source. Checks:
   - wake separation
   - minimum fuel reserve
   - gate conflicts
   - crew duty limits
   - turnaround minimum
   - arrival-rate cap during disruption
5. **Mediator with a hard turn cap.** Uses a Monotonic Concession Protocol: agents may only concede, so the negotiation must converge. "Under 3 turns" is read strictly as at most 2 negotiation rounds; the fallback owns turn 3. Consensus means all three accept a candidate that passed the rules engine.
6. **Adversarial safety reviewer.** Independently re-derives the chosen solution's constraint maths and returns APPROVE / REJECT / MODIFY.
7. **Deterministic fallback.** Fires on no consensus, a malformed message or a deadlock. It picks the best rule-compliant option (minimise weighted delay subject to constraints; greedy or small MILP). The log records that it fired, and why.
8. **Consensus log.** Append-only, timestamped JSONL. Exportable and shown in the UI.
9. **Human approval step.** The UI shows the recommendation with its evidence. A human approves or rejects; the tool never executes.
10. **Optional LLM explanation layer.** Turns the log into a plain-English briefing citing rule IDs and data fields.

**Known pitfall:** a stateless gate service re-assigns gates on every restart. Lock assignments once valid, and seed all randomness.

---

## 7. Evaluation plan

- **Showcase scenario:** DFW on 24 Apr 2015, the worst weather day in the file. It had 79 weather-delayed arrivals, peaking 11:00–13:00 and 19:00–20:00. The flight is AA334 / N469AA (section 4.5).
- **Test set:** 200–500 rows with `WEATHER_DELAY > 15` across ORD, ATL, DFW and DEN, plus some late-aircraft rows. Fixed seed, sample IDs saved.
- **Three-way comparison:** what actually happened vs. the deterministic solver alone vs. agents plus solver.
- **Metrics:**
  - consensus rate within the turn cap
  - mean turns to consensus
  - fallback rate
  - agent-proposed violations caught by the rules engine and reviewer (should be > 0)
  - estimated delay and knock-on minutes vs the real outcome
  - schema-invalid message rate
  - latency and cost per scenario
- **Failure case to show live:** a deadlock or a reserve-violating hold that the reviewer rejects, after which the fallback takes over.
- **Honesty notes:** savings are model estimates; the data contains only delayed flights; gates, crew and fuel are synthetic.

---

## 8. Research to build on

- **ATC Guardian** (Band of Agents Hackathon, 2026). An adversarial Safety Reviewer re-derives separation maths and returns APPROVE / REJECT / MODIFY before the human sees anything. There is a JSON-exportable audit log.
- **BandOps** (same hackathon). An FAA compliance agent acts as adversarial auditor, and a commander agent writes one recommendation for a human to approve.
- **SkyLink Navigator.** A single LLM loop; it is the anti-pattern the brief warns against.
- **Bouarfa et al.** (TU Delft). Mediator agent plus deadline protocol for airline ops control. It beat industry strategies.
- **Pattanayak** (SSRN 2026). Gate-exchange negotiation calibrated on BTS data, evaluated against two baselines.
- **Nakatsu** (arXiv). Names the failure modes of negotiating LLM agents (polite loops, malformed outputs, deadlocks). Counters them with schema gates and deterministic deadlock recovery.
- **Jarvis et al.** (NASA Ames, AAAI 2010). Peer-to-peer negotiation didn't scale. They moved to a centralised mediator plus an LP solver. This is our "why this structure" answer.
- **Andriuškevičius & Sun** (TU Delft). LLM ATC agents evaluated on 120 conflict scenarios. This is the template for many-row evaluation.
- **Wollkind** (Texas A&M). The Monotonic Concession Protocol guarantees convergence.

---

## 9. Regulatory values (VERIFY before citing; otherwise label "assumed")

- **Wake separation on final** (FAA JO 7110.65 para 5-5-4, legacy categories):
  - Heavy behind Heavy: 4 NM
  - Large behind Heavy: 5 NM
  - Small behind Heavy: 6 NM
  - More behind Super
  - Convert to time using approach speed.
- **Domestic fuel reserve** (14 CFR 121.639): destination + most distant alternate + 45 min at normal cruise.
- **Crew duty** (14 CFR Part 117): maximum flight duty period roughly 9–14 h by report time and segments; flight-time limit 8–9 h.
- **Minimum turnaround:** no regulation. Assumed per aircraft class.
- **Ground-crew overtime:** no regulation. Synthetic shift model.

---

## 10. Pitch framing (3 minutes)

- **User:** an airline operations-control duty manager coordinating with the TRACON traffic manager and the hub ramp/gate controller during irregular operations.
- **Status quo:** phone calls and manual updates across three organisations, with delays cascading through the aircraft's day. For N469AA on 24 Apr 2015, arrival delay went from +101 to +256.
- **Line:** "LLMs negotiate, code decides, every decision traces to a rule and a data field, and a human approves."
- **Show:**
  1. Live negotiation on AA334
  2. The consensus log
  3. The reviewer rejecting an unsafe proposal
  4. The fallback firing
  5. The evaluation table over hundreds of real rows
  6. The real vs synthetic data slide
- **Close:** limitations and what would fix them.

---

## 11. Engineering preferences

- Python. The deterministic core runs end to end with the agents stubbed, without any LLM.
- Agents are pluggable, with a stub/mock mode. Every LLM message is validated against a Pydantic schema. Invalid messages are rejected and logged, never silently repaired.
- Deterministic seeds everywhere. Save evaluation sample IDs and results to files.
- Simple Streamlit UI showing:
  - the scenario and the turns
  - rule checks, the reviewer verdict and the fallback status
  - the recommendation with approve/reject
  - the evaluation table
- Public repo with an MIT or Apache-2.0 license and a README covering how to run it, the architecture, data limits, synthetic labels and evaluation results.
- Finish a working, honest end-to-end slice early before broadening.

---

## 12. Open decisions

1. **The "under 3 turns" reading.** Proposed: at most 2 negotiation rounds, with the fallback on turn 3.
2. **Model choice and budget.** API credits are US$200 across 4 keys, shared between Claude Code building and the app's own calls. Proposed:
   - a cheap model (Sonnet 5.5 at $2/$10 or Haiku 5.5 at $0.10/$0.50 per M tokens) with prompt caching for the bulk evaluation
   - a stronger model for the live demo
   - measure the cost on ~10 rows before the full evaluation run
3. **Making the repo public** also publishes the organisers' PDF. Check whether that's allowed, or exclude the PDF.
4. **Python 3.14** may lack wheels for some libraries (e.g. OR-Tools). Fall back to PuLP or a greedy solver if needed.
