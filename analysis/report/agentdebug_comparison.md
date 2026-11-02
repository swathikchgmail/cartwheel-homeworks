# AgentDebug comparison

I mapped my 8 error modes (analysis/state/patterns.json) against the agent failure taxonomy from Zhu et al. ("Where LLM Agents Fail and How They Can Learn From Failures," arXiv:2509.25370, Table 2). The framework categorizes failures across five core agent modules: memory, reflection, planning, action, and system.

## Mapping

| My mode | Closest AgentDebug type |
|---|---|
| `fact_not_supported_by_source` | Memory: Hallucination (false memory); Reflection: Outcome Misinterpretation |
| `unconfirmed_outcome_promised` | Reflection: Progress Misassessment (too optimistic) |
| `bad_search_false_claim` | Action: Parameter Error |
| `results_truncated_silently` | Reflection: Outcome Misinterpretation |
| `wrong_governing_policy` | Planning: Constraint Ignorance |
| `invalid_data_not_flagged` | Reflection: Outcome Misinterpretation (the bad record itself is a System: Environment Error) |
| `question_not_answered` | Planning: Planning-Action Disconnect (support-0212 offered to search and never did) |
| `policy_not_cited` | None |

`policy_not_cited` has no counterpart because AgentDebug measures task failure, while RESP-1 is a product response rule: the answer can be right and still fail the requirement.

## Possible omission: retrieval failure

AgentDebug's Memory: Retrieval Failure ("relevant info exists but is not retrieved when needed") matches three of my traces: support-0179 asked for a delivery date it had just looked up, support-0007 repeated a question the user had answered, and support-0127 asked when the order should have arrived. In my taxonomy these sit inside `question_not_answered`. I did not add a mode: the product fix is the same (use what is already in the conversation and tool results, then answer), and my annotations do not show these needing a different change.

## Unclear name

`question_not_answered` covers asking for unneeded information, repeating a question, offering to act without acting, and escalating something the help center answers. AgentDebug names each failure by what went wrong, which makes mine look vague. A name such as `answer_deflected` would say more; I kept the current name for now.

## Not seen in my traces

System types (step limit, tool execution error, LLM limit) did not appear: the one tool error I saw (support-0140, `permission_denied`) was handled correctly. I added no modes from AgentDebug.
