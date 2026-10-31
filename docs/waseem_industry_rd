# Challenge #2 Stakeholder & Dataset Brief

Oct 31, 2026 · @Jayson

## TL;DR

Three findings should shape the build.

1. **Controllers lack people to do the coordinating.** The FAA has about 11,000 certified controllers, below its own reduced target of 12,563. In 2024 they logged 2.2 million overtime hours. An agent that takes phone-call coordination off their plate addresses their biggest bottleneck. Anything that adds to their workload will be rejected.
2. **Pilots' constraints are hard numbers, not preferences.** These include the 45-minute fuel reserve (14 CFR 121.639) and duty limits (Part 117: 9–14 hour duty periods). The Pilot agent should hold these as rules a solver checks, not leave them to LLM judgement.
3. **The dataset is a cascade dataset, not a weather dataset.** All 358,774 rows already meet the brief's filter. Late-aircraft delay accounts for 72.9% of delay minutes, against 9.8% for weather. 144,744 legs can be linked to the same aircraft's next flight. In 78% of those, the plane landed after its next departure was due to leave. This is the data hook for the Ground agent.

## Air traffic controllers

**Who they are.** TRACON (approach) and tower controllers own runway sequencing and separation. Their Traffic Management Unit sets arrival rates and ground delay programs. In a disruption they are the party that has to say yes.

**What they need:** safe separation at all times, maximum runway and sector throughput, and fewer manual coordination tasks during peaks.

| Bottleneck | Evidence | What the ATC agent must do |
| --- | --- | --- |
| Chronic understaffing | About 11,000 certified controllers vs a new target of 12,563, cut from 14,633 in May 2026 ([Spokesman-Review](https://www.spokesman.com/stories/2026/may/15/faa-cuts-target-for-air-traffic-control-staffing/)). About 280 of 300 facilities are below proper staffing ([Avionics International](https://www.aviationtoday.com/2025/07/25/americas-atc-meltdown-why-the-skies-are-short-staffed-and-the-remedies-that-are-needed)) | Cut coordination steps; never add a new screen to watch |
| Overtime and fatigue | 2.2M overtime hours in 2024, about $200M. About 41% of controllers work 60-hour weeks | Present one agreed plan for approval, not a stream of options |
| Delays even in clear weather | United says 68% of its 2024 clear-weather delays came from ATC staffing limits | Show throughput regained, measured in arrivals per hour |
| Fragile equipment | Newark controllers lost radar and radio for about 90 seconds several times in 2025; United cut about 10% of its Newark schedule ([One Mile at a Time](https://onemileatatime.com/news/newark-atc-radar-radio-outages-chaos/)) | Deterministic fallback when the AI layer or its inputs fail |
| Voice-channel congestion | Frequency changes are the largest share of transmissions and of readback errors ([DOT Volpe study](https://rosap.ntl.bts.gov/view/dot/12501)) | Exchange structured messages, not free text |

**Hard rules the ATC agent enforces** (a rules engine, not the LLM):

- Wake separation, e.g. 5 nm for a Large behind a Heavy, 7 nm for a Large behind a Super, 6 nm at the threshold for a Small behind a Heavy ([AIM 7-4-9](https://www.angleofattack.com/aim/chapter-7/7-4-9/)). Tighter wake standards (RECAT) gave Memphis about 15% more capacity, or 9 more flights an hour ([AIN](https://backend.ainonline.com/aviation-news/air-transport/2013-02-04/new-wake-separation-standards-boost-capacity-memphis)). Spacing is exactly the lever the ATC agent trades.
- Runway arrival slots per hour (the airport acceptance rate) and taxiway blockages.

## Pilots

**Who they are.** The captain and first officer of an inbound flight, working with the airline dispatcher, who shares legal responsibility for fuel and duty decisions. In a disruption they absorb the cost: holding, re-planning and a tighter workload in descent.

**What they need:** a revised arrival time they can plan fuel against, early notice of holding or reroutes, and protected margins for safety, fuel, duty time and passenger connections.

| Bottleneck | Evidence | What the Pilot agent must do |
| --- | --- | --- |
| Fuel is fixed once airborne | Part 121 domestic fuel = destination + most distant alternate + 45 min at cruise burn. The 45-minute reserve cannot be spent on expected holding; delay cover comes from discretionary contingency fuel ([14 CFR 121.639 summary](https://open-exam-prep.com/study-guides/faa-aircraft-dispatcher/part-121-fuel-planning-rerelease/part-121-domestic-fuel-requirements)) | Reject any plan whose holding time exceeds contingency fuel; trigger divert below it |
| Duty-time cliffs | Flight duty period limits of 9–14 h depending on report time and legs, max 8–9 h flight time, 10 h rest. A pre-takeoff extension is capped at 2 h ([Part 117 summary](https://open-exam-prep.com/study-guides/faa-adx/flight-duty-rest-regulations/ch4-s2-flightcrew-flight-duty-rest-part-117)) | Flag when a delay would time out the crew on the next leg |
| Every minute costs money | $98.41 per block minute for US airlines in 2025: $37.01 crew, $29.34 fuel ([Airlines for America](https://airlines.org/dataset/u-s-passenger-carrier-delay-costs/)) | Score options in dollars as well as minutes |
| Late, vague information by voice | Frequency changes drive most readback errors; step-on and blocked transmissions rise with congestion ([DOT Volpe study](https://rosap.ntl.bts.gov/view/dot/12501)) | Return one structured, timestamped clearance proposal |
| Missed connections | Passengers on late inbounds miss onward flights; the airline pays to re-book | Weight arrival slots by connecting load (simulated, see feature map) |

**Hard rules the Pilot agent enforces:** fuel at landing ≥ alternate + 45-min reserve; crew duty period within its Part 117 limit; and no acceptance of a slot that breaks either, regardless of what the LLM proposes.

## Ground operations (brief)

Airlines, not ATC, assign their own gates and staff the ramp crews. A late arrival therefore blocks a gate that the next flight was counting on. Planes wait after landing for three main reasons: the gate is occupied, the ground crew isn't in position, or the ramp is congested ([Cleveland Hopkins Airport](https://www.clevelandairport.com/about-cle/news-press/why-you-sometimes-wait-plane-after-landing-cle)). The Ground agent's job is to keep a gate and a crew ready for the revised arrival time, and to warn when the aircraft's next departure can't make it.

## What we were given

The flights file covers 358,774 US domestic flights from 2015 and is already filtered to the brief's rule. Every row has WEATHER\_DELAY > 15 or LATE\_AIRCRAFT\_DELAY > 20, so any row is a valid input.

| File | Rows | What it holds |
| --- | --- | --- |
| flights.csv | 358,774 × 31 cols | One delayed flight per row: schedule vs actual times, taxi times, distance, five delay-cause minutes |
| airlines.csv | 14 | IATA code → airline name |
| airports.csv | 322 | IATA code → name, city, state, lat/long (ECP, PBG, UST have no coordinates) |

What the profile shows:

- **Coverage:** 11 months; **October is missing**, and so are cancelled and diverted flights (0 rows of each). The CANCELLATION\_REASON column is entirely empty.
- **Every row is late:** arrival delay is at least 16 min, with a median of 61 min and a maximum of 1,598 min. The five cause columns add up exactly to ARRIVAL\_DELAY on 100% of rows.
- **Delay minutes by cause:** late aircraft 72.9%, weather 9.8%, airline 9.4%, air system (ATC/NAS) 7.8%, security about 0%.
- **Filter split:** 326,249 rows pass the late-aircraft test and 42,012 pass the weather test. 9,487 pass both.
- **Busiest origins:** ORD 25,274; ATL 17,606; DFW 17,484; DEN 15,480; LAX 14,854. Weather rows also concentrate at ORD (6,367), ATL and DFW.
- **Ground congestion signal:** median taxi-out is 19 min on weather rows vs 14 min on the rest. It reaches 27–28 min at LGA and JFK. 51.7% of weather rows also carry air-system delay.
- **Peak:** scheduled departures pile up 17:00–19:59, when delays have compounded through the day.
- **Bias to flag:** this is a sample of delayed flights only. Hourly counts are delayed-flight counts, not airport traffic.

## Feature map

Each agent gets real columns for timing and cause. Fuel, gates, wake class and connections are not in the data, so they must be derived or simulated, and labelled as such.

| Agent | Real columns to pass in | Derived features (computed by us) | Missing, so simulate and label |
| --- | --- | --- | --- |
| ATC | DESTINATION\_AIRPORT, SCHEDULED\_ARRIVAL, ARRIVAL\_TIME, AIR\_SYSTEM\_DELAY, WEATHER\_DELAY, TAXI\_IN, TAXI\_OUT | Delayed-arrival load per destination per hour; taxi-out vs that airport's median as a congestion index | Runway config and acceptance rate; aircraft wake class (no aircraft type column, so infer from airline + distance or a tail lookup) |
| Pilot | AIRLINE, FLIGHT\_NUMBER, TAIL\_NUMBER, AIR\_TIME, ELAPSED\_TIME, SCHEDULED\_TIME, DISTANCE | Airborne excess = ELAPSED − SCHEDULED (over 15 min on 27.7% of weather rows, a holding proxy); great-circle distance to an alternate from airports.csv lat/long | Fuel on board, contingency fuel, crew duty start, connecting passengers |
| Ground | TAIL\_NUMBER, MONTH, DAY, DESTINATION\_AIRPORT, ARRIVAL\_TIME, TAXI\_IN, LATE\_AIRCRAFT\_DELAY | **Turnaround buffer** = the same tail's next scheduled departure − actual arrival (144,744 linked legs; median −22 min; 96.5% under 30 min) | Gate inventory and occupancy, ramp crew shift ends |
| All (scenario) | WEATHER\_DELAY > 15 or LATE\_AIRCRAFT\_DELAY > 20 picks the disruption type | Cost of the delay at $98.41 per block minute | None |

Times are local hhmm integers; convert to minutes after midnight and watch for flights that cross midnight. A run with simulated inputs should print which fields were synthetic, because the rubric marks down unlabelled synthetic data.

## Implications and demo row

Candidate demo row: **UA1198 LGA→ORD, 3 Feb 2015**, tail N27724. It was scheduled to arrive at 07:37 but arrived at 13:40, with 363 min of weather delay. The same aircraft's next leg, UA1237 back to LGA, was scheduled to leave 40 min before it landed. That one row gives each agent something real to negotiate:

- **ATC:** an ORD arrival slot during a weather day with elevated taxi times.
- **Pilot:** a revised arrival time, plus a fuel and duty check on the long day.
- **Ground:** a gate for the arrival and a decision on UA1237: swap the aircraft or delay it.

What this means for the build:

- Pitch the user as a **TRACON / tower supervisor at a hub such as ORD**, not "aviation" in general, because the rubric scores a named user.
- Lead with the cascade, since 73% of delay minutes are late-aircraft. A weather-only demo misses where most of the cost sits.
- Evaluate across many rows. For example, run 500 random qualifying rows through a first-come-first-served baseline vs the negotiated plan. Report minutes and dollars saved, plus the share of runs that fell back to the deterministic solver.

## Sources

- [Spokesman-Review: FAA cuts target for air traffic control staffing (May 2026)](https://www.spokesman.com/stories/2026/may/15/faa-cuts-target-for-air-traffic-control-staffing/)
- [Avionics International: America's ATC meltdown (Jul 2025)](https://www.aviationtoday.com/2025/07/25/americas-atc-meltdown-why-the-skies-are-short-staffed-and-the-remedies-that-are-needed)
- [One Mile at a Time: Newark radar and radio outages (May 2025)](https://onemileatatime.com/news/newark-atc-radar-radio-outages-chaos/)
- [DOT Volpe: Controller–pilot voice communications, Kansas City ARTCC](https://rosap.ntl.bts.gov/view/dot/12501)
- [AIM 7-4-9: Wake turbulence separation](https://www.angleofattack.com/aim/chapter-7/7-4-9/)
- [AIN: RECAT boosts capacity at Memphis](https://backend.ainonline.com/aviation-news/air-transport/2013-02-04/new-wake-separation-standards-boost-capacity-memphis)
- [Part 121 domestic fuel requirements (study guide)](https://open-exam-prep.com/study-guides/faa-aircraft-dispatcher/part-121-fuel-planning-rerelease/part-121-domestic-fuel-requirements)
- [Part 117 flight duty and rest (study guide)](https://open-exam-prep.com/study-guides/faa-adx/flight-duty-rest-regulations/ch4-s2-flightcrew-flight-duty-rest-part-117)
- [Airlines for America: U.S. passenger carrier delay costs](https://airlines.org/dataset/u-s-passenger-carrier-delay-costs/)
- [Cleveland Hopkins: Why you sometimes wait for a gate](https://www.clevelandairport.com/about-cle/news-press/why-you-sometimes-wait-plane-after-landing-cle)
- Dataset: flights.csv, airlines.csv, airports.csv (US DOT 2015), and the Autonomous SG 2026 Airbus track brief
