# Autonomous Multi-Agent Disruption Resolution in Aviation Operations

## Executive Summary

The transition from human-centric, voice-reliant air traffic management (ATM) to autonomous, digitally negotiated operations represents a critical evolution in aviation safety and efficiency. As airspace capacity reaches physical limits and staffing shortages persist, the latency inherent in manual disruption coordination leads to compounding systemic failures, excessive carbon emissions, and severe financial penalties for operators. Based on an exhaustive analysis of current air traffic control (ATC) workflows, international regulatory frameworks, and prior research spanning NASA demonstrations to European Union Aviation Safety Agency (EASA) concept papers, this report presents the foundational architecture and operational requirements for building a Multi-Agent Communication Framework capable of resolving flight disruptions autonomously.

Five primary findings dictate the optimal approach for the system build:

1. **The Communication Bottleneck as the Primary Vector of Delay:** Current disruption resolution relies on sequential, siloed voice communications and manual data entry across Terminal Radar Approach Control (TRACON), Traffic Management Units (TMU), Airline Operations Centers (AOC), and Ramp Control. This sequential process inherently propagates downstream delays, costing U.S. airlines $98.41 per block minute in 2025 [1]. Parallel, machine-to-machine negotiation can recapture these lost minutes by instantly harmonizing airside and landside constraints.
2. **The 3-Turn Convergence Constraint Requires Mediation:** Standard multi-agent negotiation models (such as Contract Net Protocols or Monotonic Concessions) require extensive messaging iterations and are highly susceptible to infinite loops when self-interested agents refuse to concede. To mathematically guarantee consensus in under three turns, a Single-Text Mediated Protocol (STMP) is strictly required. A central orchestrator must maintain a single evolving solution that domain agents iteratively constrain and validate.
3. **Hybrid Determinism Supersedes Pure AI:** Aviation regulatory bodies, specifically EASA in its AI Roadmap 2.0 and Concept Paper for Level 1/2 Machine Learning, mandate absolute trustworthiness, determinism, and traceability for safety-critical applications [2]. Large Language Models (LLMs) must act strictly as semantic reasoning and translation layers. All safety margins, including FAA RECAT wake turbulence separation and 14 CFR Part 117 duty limits, must be exclusively validated by deterministic, hard-coded programmatic solvers that the LLMs query.
4. **Defensible Data Imputation is Viable:** The provided U.S. DOT 2015 dataset lacks critical operational fields necessary for localized negotiation. However, deterministically mapping the provided tail numbers (N-numbers) to the FAA Aircraft Registry allows the accurate derivation of aircraft types and FAA RECAT weight classes. Combined with baseline performance metrics from the Aviation System Performance Metrics (ASPM) and the Bureau of Transportation Statistics (BTS), these data gaps can be bridged robustly without requiring live API calls during system execution.
5. **Traceability as a Non-Negotiable Metric:** Hackathon evaluations heavily weight "Honest Evaluation" and "Trust and Traceability," which account for 40% of the judging rubric [5]. The system's consensus log cannot merely record the final decision; it must explicitly log the exact regulatory constraint (e.g., 14 CFR 117.19) and the deterministic function outcome that influenced each agent's concession. Failure to provide this level of auditability renders any AI solution non-certifiable under emerging FAA and EASA standards.

**Recommended Architecture:** The framework must employ a **Mediated Hybrid Architecture**. An LLM-based Orchestrator Agent ingests the disruption parameters (e.g., weather delay exceeding 15 minutes) and generates an initial multi-dimensional flight plan revision encompassing Arrival Time, Gate Assignment, and Speed/Holding Profiles. This proposal is broadcast via a strictly validated JSON schema to three independent LLM domain agents (ATC, Pilot, Ground). These agents are structurally prohibited from communicating directly with one another. Instead, they parse the proposal, query localized, hard-coded deterministic constraint solvers (e.g., a Python module validating JO 7110.126B wake separation), and return a localized approval or a mathematically bounded counter-proposal to the Orchestrator. If all three deterministic checks pass simultaneously, consensus is achieved. If consensus is not reached by the conclusion of Turn 3, the Orchestrator autonomously executes a deterministic non-AI fallback protocol, such as a First-Come-First-Served (FCFS) holding pattern assignment.

---

## 1. Current-State Workflow

The current operational workflow for managing real-time aviation disruptions, such as unexpected convective weather at a destination airport, a late inbound aircraft, or an occupied gate, is highly fragmented. It relies on sequential human-in-the-loop (HITL) coordination that spans multiple disparate organizations, utilizing tools that rarely communicate natively.

When weather degrades terminal airspace capacity, the initial detection typically occurs via Terminal Radar Approach Control (TRACON) or the local tower observing diminished Arrival Acceptance Rates (AAR). The TRACON notifies the regional Air Route Traffic Control Center (ARTCC) Traffic Management Unit (TMU). If the disruption is severe, the TMU coordinates with the Air Traffic Control System Command Center (ATCSCC) to implement a Traffic Management Initiative (TMI), such as a Ground Delay Program (GDP) or an Airspace Flow Program (AFP) [6]. The ATCSCC calculates and issues Expected Departure Clearance Times (EDCT) for inbound flights to manage the flow into the degraded sector.

Simultaneously, the Airline Operations Center (AOC) dispatcher monitors the FAA's Traffic Flow Management System (TFMS) or Collaborative Decision Making (CDM) feeds. Upon seeing an EDCT or an airborne holding assignment populating in the system, the dispatcher must manually intervene. The dispatcher analyzes the downstream effects on crew flight duty periods (FDP), aircraft fuel states, and passenger connections. They then initiate a voice call (via VHF/UHF radio) or send an ACARS text message to the flight crew [6].

The flight crew, upon receiving the delay notification, must consult their Flight Management System (FMS) to calculate holding fuel, endurance, and diversion parameters. The pilot then negotiates a revised clearance with the en-route sector controller via VHF radio. Meanwhile, the AOC contacts local ramp control via phone or internal airline dispatch software to update gate assignments. Because ramp control systems are often isolated from en-route ATC systems, this leads to cascading delays: ground crew and baggage handlers are left idle waiting for an aircraft that is holding 200 miles away, or they are reassigned, leaving the aircraft waiting on the taxiway upon its eventual arrival.

The primary time losses occur in the latency of human context-switching, the manual data entry required to transpose EDCTs into airline dispatch software, and the sequential nature of voice communications. A single runway closure can require five to ten distinct voice calls across different radio frequencies and phone lines just to manage a single aircraft. During high-workload irregular operations (IROPS), task saturation delays these communications, causing aircraft to burn contingency fuel unnecessarily while waiting for revised clearances or gate availability.

### Implications for our build

- The architecture must replace the sequential voice and ACARS relay with parallel, synchronous data exchange between the ATC, Pilot, and Ground agents, reflecting a leap over current manual processes.
- The simulation must model the baseline latency of human coordination. Assuming a conservative 5 to 15-minute communication lag in the non-AI baseline will accurately demonstrate the financial and operational impact of sub-second AI negotiation.
- The Ground Agent must automatically receive the revised Estimated Time of Arrival (ETA) directly from the negotiation consensus, thereby eliminating the chronic AOC-to-Ramp communication blind spot.

---

## 2. Existing Systems and Prior Art

The aviation industry has spent decades attempting to solve the disruption coordination problem, predominantly through centralized, deterministic scheduling tools and regional data-sharing platforms. While these systems provide vast amounts of data, they generally lack the autonomous negotiation capabilities required for rapid, decentralized disruption resolution.

The FAA's Collaborative Decision Making (CDM) and Europe's Airport CDM (A-CDM) established the foundation for shared situational awareness. A-CDM relies heavily on milestone-driven Target Off-Block Times (TOBT) and Target Start-Up Approval Times (TSAT) to optimize departure sequencing. Eurocontrol data confirms that A-CDM has successfully reduced average Air Traffic Flow Management (ATFM) delays by 1.67 to 3 minutes per flight in regulated scenarios [8]. By sharing accurate departure planning information, A-CDM replaces the "first come, first served" model with a "best planned, best served" principle, dramatically improving take-off predictability [8]. Furthermore, Time-Based Flow Management (TBFM) and Arrival/Departure Managers (AMAN/DMAN) optimize runway throughput by assigning precise metering times to aircraft.

More recently, the NASA Airspace Technology Demonstration 2 (ATD-2) introduced the Integrated Arrival, Departure, and Surface (IADS) system. ATD-2 digitized the Approval Request (APREQ) negotiation process between tower controllers and en-route centers, transitioning it from cumbersome voice calls to electronic Trajectory Option Sets (TOS) [12]. ATD-2 field evaluations at Charlotte (CLT) and Dallas-Fort Worth (DFW) demonstrated massive operational benefits: 837 hours of flight delay were eliminated, and over 1 million gallons of jet fuel were saved, translating to substantial reductions in CO2 emissions and crew costs [14].

In the European context, the SESAR Total Airport Management (TAM) project (PJ04) extends collaborative decision making by bridging airside and landside operations, allowing for proactive management of airport crises [16]. In the commercial sector, disruption management suites like Lufthansa Systems' NetLine/Ops ++, Amadeus's Altéa, and Accelya FLX Recover focus heavily on airline schedule recovery. Academic systems like MASDIMA (Multi-Agent System for Disruption Management), developed by Castro et al., successfully proved that autonomous agents representing aircraft, crew, and passengers could negotiate operational recovery using distributed artificial intelligence [18].

**The Remaining Gap:** Existing tools are largely advisory, human-in-the-loop, and structurally siloed. A-CDM and ATD-2 optimize ATC and ground flow but do not autonomously negotiate with the pilot's highly localized constraints (e.g., specific fuel margins, ride quality preferences, or passenger connections). Conversely, commercial airline tools optimize fleet and crew but remain ignorant of real-time ATC sector throughput constraints. The critical gap is a decentralized, cross-organizational negotiation layer capable of reasoning through uncodified, dynamic constraints: a gap perfectly suited for an LLM-based multi-agent framework bounded by deterministic safety rules.

### Implications for our build

- Do not attempt to rebuild a traditional schedule optimizer; instead, leverage the concept of Trajectory Option Sets (TOS) where the agents evaluate a discrete menu of options (e.g., Option A: Hold 15 mins; Option B: Divert; Option C: Slow down 0.05 Mach).
- Utilize A-CDM concepts like TOBT and TSAT as the primary variables negotiated by the Ground Agent to ground the project in established operational reality.
- Position the AI solution as the connective tissue that bridges the existing gap between FAA TBFM systems (ATC) and airline recovery tools (Pilot/Ground), rather than attempting to replace either.

---

## 3. Multi-Agent Negotiation Methods

Achieving consensus among self-interested agents representing different domains requires a highly robust negotiation protocol. In decentralized environments, agents must balance local utility (e.g., an airline maximizing profit) with global constraints (e.g., ATC maintaining safety).

Common multi-agent protocols include the Contract Net Protocol (CNP), Monotonic Concession, and Auction mechanisms. CNP involves a manager broadcasting a task, agents bidding, and the manager awarding the contract based on the best bid [20]. While effective for static resource allocation, CNP typically requires multiple bidding phases and prolonged message passing, risking violation of the hackathon's strict 3-turn limit constraint. Monotonic Concession requires agents to progressively lower their utility demands until an intersection is found. However, in safety-critical aviation, constraints (like minimum fuel reserves or duty time limits) are binary and non-concessional; an aircraft cannot safely compromise on a statutory 45-minute legal fuel reserve to reach an agreement.

The optimal approach for this specific challenge is a **Single-Text Mediated Protocol (STMP)**. Originally derived from international diplomacy and increasingly applied in advanced multi-agent systems for air traffic management [21], STMP utilizes a neutral mediator (an Orchestrator Agent) that maintains a single, evolving proposed resolution document.

The process operates as follows:

1. **Turn 1:** The Orchestrator ingests the disruption and generates a baseline proposal (e.g., "Delay arrival by 20 minutes, assign Gate 4").
2. **Turn 2:** The ATC, Pilot, and Ground agents critique the proposal simultaneously. The agents do not talk to each other. The Pilot agent queries its deterministic fuel solver and returns: "Reject: 20-minute delay violates 45-min fuel reserve; can only accept 12 minutes max." The Ground agent returns: "Reject: Gate 4 occupied until 14:15Z; Gate 6 available immediately."
3. **Turn 3:** The Orchestrator processes the constraint gradients provided by the agents and issues a final, mathematically viable proposal (e.g., "Delay arrival by 12 minutes, prioritize ATC sequencing via speed reduction, assign Gate 6"). The agents validate against their deterministic rule engines and accept.

By utilizing LLMs to parse the semantic nuance of the disruption and strictly formatting the communication via JSON schemas, the agents can evaluate constraints efficiently without falling into infinite, unconstrained conversational loops. Studies from TU Delft and the MASDIMA project at the University of Porto have successfully utilized similar cooperative negotiation mechanisms to integrate aircraft, crew, and passenger recovery [18].

### Implications for our build

- Implement a four-node architecture: one central Orchestrator (Mediator) and three localized Domain Agents (ATC, Pilot, Ground).
- Avoid agent-to-agent direct messaging; all communications must route through the Orchestrator to prevent infinite LLM loops and guarantee convergence within the 3-turn limit.
- Enforce a deterministic fallback mechanism: if any agent rejects the Turn 3 proposal due to a hard constraint violation, the system automatically defaults to a non-AI rule (e.g., Standard Airborne Holding until fuel bingo, followed by an automatic diversion).

---

## 4. Hard Constraints as Rules

To satisfy the stringent requirement that AI agents cannot accept solutions violating safety margins, the LLM reasoning must be strictly decoupled from legal validation. LLMs are probabilistic and prone to hallucination; therefore, each agent must query a deterministic solver (e.g., a Python rules engine) before responding to a proposal.

### ATC Agent Constraints

- **Wake Turbulence Separation:** This is strictly governed by FAA Order JO 7110.126B (Consolidated Wake Turbulence / RECAT). Aircraft are classified into Categories A through I based on maximum takeoff weight (MTOW) and wingspan [23]. For distance-based radar separation on approach, the matrix dictates specific nautical mile (NM) minima. For example, a Category B aircraft (Pairwise Upper Heavy) following a Category A aircraft (A388/A225) requires 5 NM of separation; a Category H aircraft (Upper Small) following a Category A requires 8 NM [24]. For time-based separation on the same runway, Categories B through I following a Category A require 3 minutes of separation [23].
- **Runway Occupancy Time (ROT):** Governed by FAA Order JO 7110.65. Average ROT for certain parallel approaches and high-throughput operations must be documented at 50 seconds or less to maintain specific capacity thresholds [26].

### Pilot Agent Constraints

- **Minimum Fuel Reserves:** Governed by 14 CFR 121.639. Domestic operations require enough fuel to fly to the destination, fly to the most distant alternate (if required by weather), and fly for 45 minutes thereafter at normal cruising fuel consumption.
- **Flight Duty Period (FDP) Limits:** Governed by 14 CFR 117. Table B establishes maximum FDPs ranging from 9 to 14 hours based on the pilot's start time and the number of flight segments [28]. Under 14 CFR 117.19, the Pilot-in-Command and the airline may extend the FDP by up to 2 hours to mitigate unforeseen operational disruptions, provided the extension occurs after takeoff or is strictly documented [29]. Any extension exceeding 30 minutes requires mandatory reporting to the FAA within 10 days, making such extensions highly undesirable for routine delays [31].

### Ground Agent Constraints

- **Gate Utilization & Turnaround:** Hard physical constraints dictate gate compatibility (e.g., a widebody Boeing 777 cannot park at a gate designed for a narrowbody Embraer 175). Minimum turnaround times vary strictly by fleet (e.g., approximately 35 minutes for a B737, extending to 90 minutes for a widebody international arrival).
- **Ground Crew Overtime:** Labor regulations and specific union contracts limit unexpected shift extensions, requiring rigorous monitoring to prevent systemic overtime costs.

### Implications for our build

- Build standalone, deterministic Python functions for each domain (e.g., `check_fuel_legality(proposed_delay_mins, current_fuel_lbs)`) that the LLM agents must invoke via structured tool-calling.
- If the LLM suggests a solution that returns `False` from the deterministic solver, the agent must be hard-coded to reject the proposal and pass the solver's precise error message back to the Orchestrator for revision.
- Utilize FAA RECAT rules explicitly for the ATC agent's logic to demonstrate deep domain expertise and technical soundness to the judging panel.

---

## 5. Filling the Data Gaps Credibly

The provided US DOT 2015 dataset is limited primarily to delay minutes and scheduled versus actual block times. To enable multi-agent negotiation, missing fields must be synthesized or imputed using defensible proxies that can be logically coded within a 24-hour hackathon environment.

1. **Aircraft Type and Wake Class:** The dataset provides the tail number (`TAIL_NUM`).
   - **Method:** Download the public FAA Aircraft Registry database (available as a bulk CSV). Merge the dataset's `TAIL_NUM` with the registry to retrieve the exact aircraft make and model. Map the make/model to the FAA RECAT categories (e.g., Boeing 737-800 maps to Category F; Airbus A380 maps to Category A).
   - **Effort:** Low.
2. **Fuel on Board:** Not publicly available per flight due to proprietary airline dispatch logic.
   - **Method:** Calculate the great-circle distance between the Origin and Destination airports. Use standard fuel burn rates (e.g., a B737 burns roughly 5,000 lbs/hour). Calculate trip fuel plus the statutory 45-minute reserve (14 CFR 121.639). To simulate real-world conditions, add a randomized contingency fuel margin representing between 15 and 30 minutes of extra flight time.
   - **Effort:** Medium.
3. **Runway Configuration & AAR:**
   - **Method:** Utilize the FAA Aviation System Performance Metrics (ASPM) database [32], which tracks Arrival Acceptance Rates (AAR) by 15-minute intervals for 75 major airports, differentiated by Visual Meteorological Conditions (VMC) versus Instrument Meteorological Conditions (IMC). If a dataset row shows `WEATHER_DELAY > 15`, programmatically apply the lower IMC AAR for that airport.
   - **Effort:** Medium.
4. **Connecting Passengers:**
   - **Method:** Utilize the Bureau of Transportation Statistics (BTS) T-100 Domestic Segment data to find average load factors for the specific airline and route in 2015. Assume a standard hub-and-spoke connection rate (e.g., 40% of passengers at a legacy carrier hub are connecting).
   - **Effort:** Low (if utilizing static historical averages).
5. **Crew Duty Start:**
   - **Method:** Synthesize deterministically. Assume the crew's FDP started exactly 1 hour prior to their first flight of the day in the dataset (using the linking of `TAIL_NUM` to trace the aircraft's daily routing).
   - **Effort:** High (requires pre-processing and sorting the entire dataset by date and tail number to trace daily schedules).

### Implications for our build

- Pre-process the dataset before the hackathon clock starts. Merge the FAA registry data and pre-calculate the RECAT wake classes and estimated fuel burns to create an enriched "Hackathon-Ready" dataset.
- Clearly state in the final pitch exactly which data points were imputed and explicitly cite the regulatory logic (e.g., 14 CFR 121.639) used to estimate them. This directly satisfies the "Trust and Traceability" judging rubric.

---

## 6. Evaluation Design

To secure maximum points in the "Honest Evaluation" (20%) category, the system must be rigorously benchmarked against a non-coordinated baseline, and failure cases must be explicitly and honestly demonstrated.

### Baselines

1. **First-Come-First-Served (FCFS) Uncoordinated:** Representing the current state, where aircraft enter holding patterns based purely on arrival time, burning standard fuel rates until terminal capacity opens or dwindling fuel margins force a diversion.
2. **Dataset Actuals:** The actual delay minutes recorded in the 2015 DOT dataset for that specific flight leg.

### Metrics

- **Delay Minutes Saved:** Total reduction in airborne holding and taxi time versus the FCFS baseline.
- **Cost Savings ($):** Evaluated at the 2025 A4A rate of $98.41 per block minute.
- **Convergence Rate:** Percentage of test cases where agents successfully reached consensus in ≤ 3 turns.
- **Constraint Violations:** Must strictly be 0%. Any violation indicates a systemic failure of the deterministic solver integration.
- **Fallback Rate:** Percentage of cases that triggered the non-AI deterministic fallback.

### Sample Size and Testing

Run a batch evaluation of 100 randomly selected rows from the dataset that meet the core criteria (`WEATHER_DELAY > 15` or `LATE_AIRCRAFT_DELAY > 20`). Record the outputs in a structured CSV log that captures the baseline delay versus the AI-negotiated delay.

### Showing Failure Cases Honestly

The rubric explicitly demands at least one visible failure case. Design a specific, labeled test row where a flight is injected into the simulation with only 46 minutes of fuel remaining upon reaching the terminal area, while the ATC Agent requires a 30-minute delay due to convective weather. The Pilot Agent's deterministic solver will immediately flag a violation of the 45-minute reserve (46 − 30 = 16 mins remaining < 45). The LLMs will fail to find a viable compromise within the 3-turn limit. The system must gracefully exit to the deterministic fallback, outputting:

> "Consensus Failed: Hard Constraint Violation (14 CFR 121.639). Executing Fallback: Immediate Diversion to Alternate."

### Implications for our build

- Build an automated evaluation script (e.g., a Python testing harness) that runs the 100 rows, calculates the aforementioned metrics, and outputs a dashboard-ready JSON file.
- During the 3-minute pitch, allocate exactly 20 seconds to explicitly highlighting the failure case. Judges evaluating AI safety are highly receptive to teams that understand and codify the limitations of LLMs in safety-critical environments.

---

## 7. Quantifying Impact

A successful hackathon pitch relies on translating highly technical multi-agent achievements into tangible operational and financial impact. The framework's value proposition rests on reducing airborne holding, mitigating downstream delay propagation, and averting diversions through preemptive negotiation.

| Metric | Value / Standard | Source |
| --- | --- | --- |
| Cost of Aircraft Delay | $98.41 per block minute (2025 data). Includes Labor ($37.01) and Fuel ($29.34). | Airlines for America (A4A) [1] |
| Value of Digital Coordination | 837 hours of flight delay eliminated; over 1 million gallons of jet fuel saved; $1.2M in crew costs saved (NASA ATD-2 Field Demos at CLT/DFW). | NASA NTRS [14] |
| A-CDM Delay Reduction | Average ATFM delays reduced by 1.67 to 3 minutes per regulated flight. | EUROCONTROL [8] |
| A-CDM Taxi Reductions | Engine running times reduced by 0.25 to 3 minutes per departure. | EUROCONTROL [8] |

Furthermore, the environmental impact is highly quantifiable. Jet fuel produces approximately 21.1 lbs (9.57 kg) of CO2 per gallon. Reducing holding time directly curbs fuel burn, contributing to industry-wide decarbonization mandates. Delay propagation is also severely mitigated; studies by the Bureau of Transportation Statistics indicate that downstream departure delays are directly correlated to late gate arrivals [33]. By negotiating gate availability prior to landing, the Ground Agent prevents the cascading multiplier effect of late aircraft.

### Implications for our build

- Integrate a real-time "Cost Saved" ticker directly into the UI dashboard that multiplies the minutes of delay averted by the A4A standard of $98.41.
- Display the estimated CO2 reduction dynamically based on the specific aircraft's fuel burn profile.
- Anchor the pitch narrative around these figures: "By saving just 3 minutes per disrupted flight using autonomous negotiation, we return approximately $300 to the airline's bottom line per flight, scaling to hundreds of millions annually across the NAS."

---

## 8. Stakeholder Pain Points with Evidence

Understanding the precise, lived frustrations of human operators validates the "Problem Realism" (20%) aspect of the judging rubric, moving the pitch beyond abstract computer science into authentic aviation operations.

- **Air Traffic Controllers (ATC):** The U.S. controller workforce is severely strained. With roughly 11,000 certified controllers currently operating against a target of 12,563 in 2026, the FAA had to mandate 2.2 million overtime hours in 2024 [5]. Controllers face exceptional cognitive loads during weather events, where managing voice traffic for holding patterns degrades overall sector throughput. The specific pain point is frequency congestion and the mental arithmetic required for calculating pairwise RECAT wake separation under pressure.
- **Pilots:** The Air Line Pilots Association (ALPA) continually highlights the insidious risks of fatigue during irregular operations. When disruptions occur, pilots must manage complex FMS reroutes, monitor deteriorating weather, and constantly calculate 14 CFR 117 FDP limits. The stress of negotiating duty extensions (up to 2 hours) [29] while airborne or during protracted ground delays is a significant human factors hazard.
- **Airline Operations Centers (AOC) / Ground Operations:** Dispatchers and ramp managers suffer chronically from information asymmetry. Ground handlers are often the absolute last to know that an inbound flight has been assigned a 45-minute airborne hold. This leads to ground crews standing idle at the gate, which incurs unrecoverable overtime costs and disrupts the turnaround sequencing for subsequent flights.

### Implications for our build

- Design the user interface (UI) to reflect a "Management by Exception" paradigm. Human stakeholders do not want to read a raw chat log of AI agents negotiating; they only need to see the final proposed resolution, the delta in time/cost, and the deterministic rules applied.
- Use specific operational terminology in the pitch (e.g., "reducing frequency congestion," "mitigating Part 117 fatigue risks," "eliminating information asymmetry") to demonstrate deep domain empathy to the judges.

---

## 9. Trust, Safety and Human-in-the-Loop

Integrating AI into safety-critical aviation environments is subject to intense, highly structured regulatory scrutiny. The European Union Aviation Safety Agency (EASA) AI Roadmap 2.0 and the subsequent Concept Paper for Level 1 and 2 Machine Learning Applications define the explicit path to certification for AI tools [2].

EASA categorizes AI into levels of operational autonomy. Level 1 involves AI assisting humans (e.g., pure decision support), while Level 2 encompasses Human-AI Teaming, where AI can autonomously select and execute actions, but the human retains continuous override authority [2]. Crucially, EASA mandates a W-shaped learning assurance process [4], which runs parallel to the traditional V-model of systems engineering. This process requires rigorous, end-to-end traceability of the AI's decision-making logic, ensuring that machine learning generalizability and robustness are mathematically proven and auditable [35].

Furthermore, the FAA's emerging AI/ML Certification Framework (which builds upon existing guidelines like DO-178C and AC 20-170B for Integrated Modular Avionics) emphasizes that while AI may propose complex solutions, the ultimate safety validation must rely on deterministic systems [37]. ICAO Doc 10144 also strongly emphasizes safety risk management principles when handling systemic disruptions [40].

To satisfy regulators, a multi-agent system cannot rely on the opaque, probabilistic weights of an LLM. It must generate an audit trail / consensus log that records the exact deterministic constraint invoked, the regulatory source, the data inputs, and the precise timestamps of the evaluation.

### Implications for our build

- Frame the architecture as strictly representing EASA Level 2 autonomy. The AI agents negotiate a solution, but a human dispatcher or controller must physically click "Approve" (Human-in-the-loop override) to enact it in the real world.
- The consensus log must be a strict JSON output that references specific regulations (e.g., `"Constraint: Wake_Separation; Source: JO_7110.126B; Value: 5NM; Status: Passed"`).
- Explicitly mention EASA's W-shaped learning assurance and the FAA's AI Certification Framework in the pitch to dominate the "Trust and Traceability" rubric.

---

## 10. Hackathon Precedents

Analyzing recent aviation hackathon winners provides a definitive blueprint for success in the Autonomous SG 2026 Airbus track. In the 2023 FAA Data Challenge, the overall winner (Jeffrey Pattison, Georgia Tech) utilized a machine-learning data fusion approach to calculate UAS risk in urban areas [42]. The 2024 FAA Data Challenge was won by a University of North Dakota team that developed an AI-powered method to analyze ATC/pilot communication keywords for sentiment and risk patterns [43].

Winning projects in these highly technical domains share specific architectural traits:

1. **Strict Constraint Awareness:** They do not treat aviation as a generic traveling salesperson optimization problem. They anchor their AI logic in specific, cited FAA orders and regulations.
2. **Visual Proof of Concept:** They provide a clean, operational dashboard that a real controller or dispatcher could plausibly use, rather than a dense terminal output.
3. **Honest Boundaries:** They clearly demarcate what the AI can do (semantic negotiation, rapid proposal generation) from what it cannot do (safety-critical separation calculations), relying on deterministic solvers for the latter.

### Implications for our build

- Do not present a command-line interface. Build a simple web dashboard (e.g., using Streamlit, React, or Vue) that visually graphs the 3-turn negotiation process and clearly presents the final outcome.
- Emulate the UND team's success by heavily focusing on the structure, clarity, and auditability of the communication between the agents [43], proving that the system is deterministic and safe.

---

## Technical Outputs for the Build

### Table 1: Codeable Constraints

| Constraint / Rule | Value / Logic | Applies to Agent | Source / Regulation |
| --- | --- | --- | --- |
| Wake Separation (Distance) | E.g., Cat B behind Cat A = 5 NM; Cat H behind Cat A = 8 NM | ATC | FAA Order JO 7110.126B [23] |
| Wake Separation (Time) | Cat B–I behind Cat A = 3 mins (same runway) | ATC | FAA Order JO 7110.126B [23] |
| Runway Occupancy Time | 50 seconds average for high-density | ATC | FAA Order JO 7110.65 [26] |
| Minimum Fuel Reserve | Trip Fuel + 45 minutes at cruise burn | Pilot | 14 CFR 121.639 |
| Max Flight Duty Period | 9–13 hours (dependent on start time) | Pilot | 14 CFR 117 Table B [28] |
| FDP Extension Limit | Max 2 hours with PIC concurrence | Pilot | 14 CFR 117.19 [29] |
| Min Turnaround Time | Narrowbody: 35m; Widebody: 90m | Ground | General Airline Ops Specs |

### Table 2: Data-Gap Fills

| Missing Field | Source or Method | Effort | Caveat |
| --- | --- | --- | --- |
| Aircraft Type / Wake Class | Cross-reference `TAIL_NUM` with FAA Aircraft Registry to get ICAO type; map to RECAT | Low | Registry data is static; tail numbers may have been reassigned since 2015. |
| Fuel on Board | Distance × standard burn rate + 45 min reserve + random 15–30m contingency | Med | Approximates weight/winds; assumes standard passenger load. |
| Runway AAR | FAA ASPM database; apply IMC rates based on `WEATHER_DELAY` flag | Med | Requires downloading secondary FAA datasets [32]. |
| Connecting Passengers | BTS T-100 average load factors × 40% hub connection proxy | Low | Generalized proxy; lacks granular, real-time itinerary data. |
| Crew Duty Start | −1 hour prior to first flight of day linked by `TAIL_NUM` | High | Assumes aircraft and crew stay together (often false in hub-and-spoke operations). |

### Recommended Message Schema (JSON)

To guarantee technical soundness, prevent unconstrained LLM loops, and provide a traceable consensus log for regulators, all agent communication must strictly adhere to a validated JSON schema.

```json
{
  "proposal_id": "P-104A",
  "turn_number": 2,
  "initiator": "Orchestrator",
  "proposed_resolution": {
    "revised_eta": "14:45Z",
    "assigned_gate": "D14",
    "speed_adjustment": "Mach 0.74"
  },
  "agent_responses": {
    "atc_agent": {
      "status": "APPROVED",
      "constraint_checks": [
        {"rule": "JO_7110.126B_Wake", "status": "PASS", "value": "5NM separation maintained"}
      ]
    },
    "pilot_agent": {
      "status": "REJECTED",
      "constraint_checks": [
        {"rule": "14_CFR_121.639_Fuel", "status": "FAIL", "value": "Revised ETA results in 38 mins reserve; minimum is 45 mins"}
      ],
      "counter_proposal": "Request revised_eta <= 14:38Z"
    },
    "ground_agent": {
      "status": "APPROVED",
      "constraint_checks": [
        {"rule": "Min_Turnaround", "status": "PASS", "value": "42 mins available"}
      ]
    }
  },
  "consensus_status": "PENDING_TURN_3"
}
```

---

## Risks and Limitations

The primary risk in this architecture is the non-deterministic nature of LLMs, which can hallucinate constraints, invent false regulatory parameters, or fail to adhere strictly to the JSON schema, thereby breaking the automated parsing logic. This is mitigated structurally by restricting the LLMs exclusively to natural language processing and semantic negotiation, while strictly enforcing all safety parameters through the deterministic Python constraint solvers. For example, if the LLM hallucinates an acceptance of a 20-minute fuel reserve, the hard-coded `check_fuel()` function overrides it to "FAIL", ensuring the system remains legally bound.

A secondary operational risk is the rigid 3-turn limit imposed by the hackathon requirements. While necessary to prevent computational gridlock and latency, a strict 3-turn cutoff may force the system into the non-AI fallback protocol more frequently than a human negotiator (who might iterate five or six times) would give up. This underscores the absolute necessity of the Single-Text Mediated Protocol, which forces rapid convergence by maintaining a single state and applying parallel constraint gradients, rather than allowing agents to bid sequentially.

Future iterations of this concept seeking actual EASA Level 2 certification would require extensive simulation across varied disruption scenarios to validate the optimal turn-limit threshold, ensuring a balance between processing speed and the rate of successful consensus.

---

## Works Cited

1. U.S. Passenger Carrier Delay Costs | Airlines For America — <https://www.airlines.org/dataset/u-s-passenger-carrier-delay-costs/>
2. Toward a Regulatory Framework to Certify Artificial Intelligence — <https://www.dglr.de/publikationen/2023/610347.pdf>
3. EASA Artificial Intelligence Concept Paper Issue 2 — European Union — <https://www.easa.europa.eu/en/document-library/general-publications/easa-artificial-intelligence-concept-paper-issue-2>
4. Formulating an Engineering Framework for Future AI Certification in — <https://www.mdpi.com/2226-4310/12/6/482>
5. Autonomous_SG_2026_Airbus_Track.md
6. (PDF) A Multi-Agent Simulation of Collaborative Air Traffic Flow — <https://www.researchgate.net/publication/288316284_A_Multi-Agent_Simulation_of_Collaborative_Air_Traffic_Flow_Management>
7. A Multi-Agent Simulation of Collaborative Air Traffic Flow Management — <https://www.researchgate.net/publication/314422813_A_Multi-Agent_Simulation_of_Collaborative_Air_Traffic_Flow_Management>
8. A-CDM Impact Assessment — Eurocontrol — <https://www.eurocontrol.int/sites/default/files/2019-04/a-cdm-impact-assessment-2016.pdf>
9. Performance Review Report 2025 — Eurocontrol — <https://www.eurocontrol.int/sites/default/files/2026-03/eurocontrol-performance-review-report-2025.pdf>
10. Airport collaborative decision-making (A-CDM) — Eurocontrol — <https://www.eurocontrol.int/concept/airport-collaborative-decision-making>
11. What is A-CDM — ICAO — <https://www.icao.int/sites/default/files/APAC/Meetings/2025/2025%20Capacity%20Assessment%20WS/Day%201/SP-04-What-is-A-CDM-by-EUROCONTROL.pdf>
12. Electronic Departure Approval Requests in ATD-2 Daily Operations — <https://ntrs.nasa.gov/api/citations/20190027034/downloads/20190027034.pdf>
13. NASA ATD-2 Trajectory Option Set Prototype Capability For — <https://ntrs.nasa.gov/api/citations/20205004243/downloads/DASC2020_Chevalley_final.pdf>
14. NASA Testing Saves Airlines One Million Gallons of Jet Fuel — <https://www.nasa.gov/centers-and-facilities/ames/nasa-testing-saves-airlines-one-million-gallons-of-jet-fuel/>
15. Mosaic ATM Case Study | ATD-2 — <https://mosaicatm.com/2021/04/09/atd-2/>
16. Total airport management (TAM) | EUROCONTROL — <https://www.eurocontrol.int/project/total-airport-management>
17. Total airport management (PJ.04 – W2) — SESAR Joint Undertaking — <https://www.sesarju.eu/news/total-airport-management-pj04-w2>
18. (PDF) Managing Disruptions with a Multi-Agent System for Airline Operations Control — <https://www.researchgate.net/publication/318145043_Managing_Disruptions_with_a_Multi-Agent_System_for_Airline_Operations_Control>
19. Disruption Management in Airline Operations Control — An Intelligent Agent-Based Approach — <https://www.researchgate.net/publication/221907694_Disruption_Management_in_Airline_Operations_Control_-_An_Intelligent_Agent-Based_Approach>
20. (PDF) Negotiation in Multi-Agent Systems — ResearchGate — <https://www.researchgate.net/publication/2805325_Negotiation_in_Multi-Agent_Systems>
21. Disruption Management in Airline Operations: A Solver-based — <https://arxiv.org/pdf/2510.26831>
22. A Multi-Agent Approach for Designing Next Generation of Air Traffic — <https://www.intechopen.com/chapters/38070>
23. RECAT Cheatsheet — ZTL ARTCC — <https://www.ztlartcc.org/asset/RECAT>
24. JO 7110.126B Consolidated Wake Turbulence — FAA — <https://www.faa.gov/documentLibrary/media/Order/2021-11-08_JO_7110.126B_Consolidated_Wake_Turbulence__FINAL.pdf>
25. Wake turbulence category — Grokipedia — <https://grokipedia.com/page/Wake_turbulence_category>
26. CHANGE — Federal Aviation Administration — <https://www.faa.gov/documentLibrary/media/Order/7110.65Rchg3.pdf>
27. Chapter 5. Radar — FAA — <https://www.faa.gov/air_traffic/publications/atpubs/atc_html/chap5_section_5.html>
28. Flight Crew Member Hours of Work and Rest Periods — <https://gazette.gc.ca/rp-pr/p1/2017/2017-07-01/html/reg2-eng.html>
29. 14 CFR 117.19 — Flight duty period extensions — eCFR — <https://www.ecfr.gov/current/title-14/chapter-I/subchapter-G/part-117/section-117.19>
30. FAQ – Flight Duty Time Extensions — Understanding FAR 117 — <https://far117understanding.com/faq-frequently-asked-questions-concerning-far-117/faq-flight-duty-time-extensions/>
31. Flightcrew Member Duty and Rest Requirements; Correction — <https://www.federalregister.gov/documents/2012/05/16/2012-11592/flightcrew-member-duty-and-rest-requirements-correction>
32. Aviation System Performance Metrics (Complete) — ASPM.faa.gov — <https://www.aspm.faa.gov/information.asp>
33. Evaluation of Airport Size and Delay Causal Factor … — VTechWorks — <https://vtechworks.lib.vt.edu/bitstreams/4f69b956-5193-4943-aa9c-cc47acd606b5/download>
34. How Europe Plans to Make Aviation AI Trustworthy — <https://mefby.vercel.app/essays/easa-ai-concept-paper/>
35. Formulating a Learning Assurance-Based Framework for AI … — MDPI — <https://www.mdpi.com/2226-4310/13/2/200>
36. Machine Learning Application Approval — MLEAP — EASA — <https://www.easa.europa.eu/en/research-projects/machine-learning-application-approval>
37. AI/ML Certification Framework — FAA — <https://www.faa.gov/about/office_org/headquarters_offices/ang/redac/REDAC_508.05_Fall_2024_NAS_Ops_Briefing_AIML_Cert_Framework-v3>
38. AI Regulations for Aviation: FAA, EASA, and ICAO — Phos AI Labs — <https://phosailabs.com/blog/ai-regulations-for-aviation-faa-easa-icao>
39. What it will take to certify AI for commercial aviation — <https://www.militaryaerospace.com/commercial-aerospace/news/55391814/what-it-will-take-to-certify-ai-for-commercial-aviation>
40. Doc 10144 ICAO Handbook for CAAs on the Management of Aviation Safety Risks — <https://www.icao.int/filebrowser/download/89674?fid=89674>
41. ICAO Handbook for CAAs on the Management of Aviation Safety — <https://www.icao.int/safety-management/SMI/COVID-19>
42. AE Student Wins First Place in the FAA Data Challenge — <https://ae.gatech.edu/news/2023/07/ae-student-wins-first-place-faa-data-challenge>
43. UND team takes first place at 2024 FAA Data Challenge — <https://blogs.und.edu/und-today/2025/03/und-team-takes-first-place-at-2024-faa-data-challenge/>
44. FAA Selects University Team Finalists of 2024 Data Challenge — <https://www.faa.gov/newsroom/faa-selects-university-team-finalists-2024-data-challenge>