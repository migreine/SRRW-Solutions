"""Decision-support UI. Owner: Reine (T2).

    streamlit run app/streamlit_app.py

Reads runs/*.json and eval/results/summary.csv. Panels:
1. Scenario card, source tags colour-coded (data / estimated / assumed / synthetic)
2. Turns table: each agent's acceptable set, vetoes, rationale; invalid-message count
3. Rule results, reviewer verdict, decided by (consensus / fallback)
4. Recommendation with Approve / Reject buttons that append to the consensus log
Later: evaluation panel and a failure-case preset button.
"""
