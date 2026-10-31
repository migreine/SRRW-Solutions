# Evaluation summary

Generated 2026-10-31T15:28:53.877942+08:00 | git 4909dba | modes none, haiku | seed 42 | sample n=200 (eval\sample_ids.csv)

Modelled delays are model estimates of the delay the recommendation would induce; actual delays are what happened (data). They are not the same quantity.

| mode | metric | value | unit | n | note |
|---|---|---|---|---|---|
| data | actual_delay_mean | 104.67 | min | 200 | data |
| data | actual_delay_median | 80.5 | min | 200 | data |
| data | actual_chain_mean | 71.835 | min | 200 | data, partial: only delayed downstream legs exist in the extract |
| none | n_rows | 200 | rows | 200 |  |
| none | n_completed | 200 | rows | 200 |  |
| none | n_guard_stopped | 0 | rows | 200 |  |
| none | n_errors | 0 | rows | 200 |  |
| none | reviewer_APPROVE_rate | 0.81 | ratio | 200 |  |
| none | reviewer_REJECT_rate | 0.145 | ratio | 200 |  |
| none | reviewer_MODIFY_rate | 0.045 | ratio | 200 |  |
| none | reviewer_engine_disagreement_rate | 0.00909091 | ratio | 2200 | checked = re-derived by the reviewer and checked by the engine on R-FUEL/R-DUTY/R-WAKE |
| none | latency_s_mean | 0.0636935 | s | 200 |  |
| none | latency_s_p95 | 0.0785 | s | 200 |  |
| none | cost_usd_mean | 0 | usd | 200 |  |
| none | cost_usd_total | 0 | usd | 200 |  |
| none | tokens_total | 0 | tokens | 200 |  |
| none | human_decision | pending |  | 200 | eval never acts; a human approves |
| none | fallback_rate_solver_only | 0.855 | ratio | 200 |  |
| none | fallback_rate_reviewer_reject | 0.145 | ratio | 200 |  |
| none | modelled_delay_solver_mean | -13.9404 | min | 200 | model estimate; not comparable like-for-like with actual |
| none | modelled_delay_solver_median | -15 | min | 200 | model estimate; not comparable like-for-like with actual |
| haiku | n_rows | 200 | rows | 200 |  |
| haiku | n_completed | 200 | rows | 200 |  |
| haiku | n_guard_stopped | 0 | rows | 200 |  |
| haiku | n_errors | 0 | rows | 200 |  |
| haiku | reviewer_APPROVE_rate | 0.66 | ratio | 200 |  |
| haiku | reviewer_REJECT_rate | 0.145 | ratio | 200 |  |
| haiku | reviewer_MODIFY_rate | 0.195 | ratio | 200 |  |
| haiku | reviewer_engine_disagreement_rate | 0.00909091 | ratio | 2200 | checked = re-derived by the reviewer and checked by the engine on R-FUEL/R-DUTY/R-WAKE |
| haiku | latency_s_mean | 32.5958 | s | 200 |  |
| haiku | latency_s_p95 | 58.2406 | s | 200 |  |
| haiku | cost_usd_mean | 0.00455049 | usd | 200 |  |
| haiku | cost_usd_total | 0.910099 | usd | 200 |  |
| haiku | tokens_total | 2.63195e+06 | tokens | 200 |  |
| haiku | human_decision | pending |  | 200 | eval never acts; a human approves |
| haiku | consensus_rate | 0.81 | ratio | 200 |  |
| haiku | consensus_round1_rate | 0.805 | ratio | 200 |  |
| haiku | consensus_round2_rate | 0.005 | ratio | 200 |  |
| haiku | mean_rounds | 1.155 | rounds | 200 |  |
| haiku | fallback_rate_no_consensus | 0.015 | ratio | 200 |  |
| haiku | fallback_rate_invalid_message | 0.03 | ratio | 200 |  |
| haiku | fallback_rate_monotonic_violation | 0 | ratio | 200 |  |
| haiku | fallback_rate_forced_deadlock | 0 | ratio | 200 | forced runs are never counted |
| haiku | fallback_rate_reviewer_reject | 0.145 | ratio | 200 |  |
| haiku | agent_top_pick_rule_fail_rate | 0.578947 | ratio | 684 | violations caught by the rules engine |
| haiku | agent_top_pick_rule_fail_rate_ATC | 0.469565 | ratio | 230 |  |
| haiku | agent_top_pick_rule_fail_rate_PILOT | 0.685841 | ratio | 226 |  |
| haiku | agent_top_pick_rule_fail_rate_GROUND | 0.583333 | ratio | 228 |  |
| haiku | consensus_excluded_by_rules_rate | 0.155 | ratio | 200 |  |
| haiku | cited_value_mismatch_rate | 0.00943009 | ratio | 9756 |  |
| haiku | schema_invalid_rate | 0.012987 | ratio | 693 |  |
| haiku | modelled_delay_agents_mean | -9.49591 | min | 200 | model estimate; not comparable like-for-like with actual |
| haiku | modelled_delay_agents_median | -15 | min | 200 | model estimate; not comparable like-for-like with actual |
| haiku | modelled_saving_vs_actual_mean | 97.8877 | min | 171 | estimate: model estimate; not comparable like-for-like with actual |
| haiku | agents_vs_solver_same_pick_rate | 0.745 | ratio | 200 | the like-for-like comparison |
