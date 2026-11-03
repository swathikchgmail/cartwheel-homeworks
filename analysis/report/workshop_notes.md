# Workshop notes (Part C)

> DRAFT written by the coding agent. The accept / revise / reject decisions are mine to make. Reword before submitting.

## Setup

- **Workshop:** I installed Raindrop Workshop locally (`http://localhost:5899`). Raindrop Cloud is not used.
- **Instrumentation:** `observability/raindrop_workshop.py` and a hook in `server/app.py`.
  - Each server turn becomes one Workshop interaction (input, reply, role, scenario id, prompt version).
  - The interaction shares the turn's trace id with Langfuse.
  - It is off unless `RAINDROP_LOCAL_DEBUGGER` is set, so the HW4 traces and the existing Langfuse/OpenLLMetry tracing are unchanged.
- **Limitation:**
  - In raindrop-ai 0.0.75, tool spans need Raindrop tracing. That tracing needs a Raindrop Cloud write key and adds its exporter to the Langfuse tracer provider, which would send every agent span to Raindrop's cloud.
  - I kept Workshop local, so it shows each run's input and reply.
  - I read the tool calls from the matching Langfuse trace (same id).
- **Runs:** 8 scenarios I had not reviewed in HW4 (fixed seed), across shopper, merchant and support roles.
  - They cover order lookups, return eligibility, product search, policy questions and an out-of-scope request. None refunds or cancels.
  - Agent model: claude-haiku-4-5.
  - Scenario ids were renamed `workshop-*`, so these traces stay out of the HW4 `support-*` set.

## Inspected runs

The run id is both the Workshop run id and the Langfuse trace id.

| Run id | Scenario | Turn | Role | Tools called | What the coding agent saw |
|---|---|---|---|---|---|
| `9e3a491c…` | workshop-0122 | 1 | shopper | find_order | Correct: order 4453 placed, not shipped. |
| `1fbc58d3…` | workshop-0122 | 2 | shopper | search_help_center | Calls the 10-day total (3 to ship + 7 in transit) the "best case"; it is the longest the policy allows. **Candidate 3.** |
| `d2daf6c9…` | workshop-0135 | 1 | shopper | find_order, search_help_center, get_policy | Correctly not eligible (delivered 59 days ago, cw-returns cited), then says a human "may be able to make an exception". **Candidate 4.** |
| `e53afbfa…` | workshop-0135 | 2 | shopper | none | Repeats the exception offer, and asks a human to check the store's window instead of checking it. **Candidate 4.** |
| `25f7bb73…` | workshop-0227 | 1 | shopper | search_products ×2 | Says Trailhead Supply "doesn't currently have camping stoves in stock"; two stoves under $25 exist. **Candidate 1 (uncertain).** |
| `ffee0d21…` | workshop-0043 | 1 | shopper | search_help_center | Correct: 5 to 10 business days, cw-refunds (returned by the search). |
| `721279cb…` | workshop-0247 | 1 | merchant | none | Says it has no tool to see listings and offers to escalate; `search_products` is open to every role. **Candidate 2.** |
| `e3a40478…` | workshop-0019 | 1 | merchant | search_help_center | Correct: up to 15% on opened items, opt-in, cw-restocking-fees cited. |
| `f528b50c…` | workshop-0231 | 1 | support | get_order | Correct: order 2799 delivered 2026-01-16. |
| `c51439f7…` | workshop-0196 | 1 | shopper | escalate_to_human | Escalated a payment-card change, then promised the agent "will make sure everything is set up correctly". **Candidate 5 (uncertain).** |

## Candidate failures

| # | Run | Candidate (coding agent) | Closest existing mode | My decision |
|---|---|---|---|---|
| 1 | `25f7bb73…` (0227) | Unsupported "no stock" claim from an empty keyword search (details below) | `fact_not_supported_by_source`, or `bad_search_false_claim` | **Revised** to `fact_not_supported_by_source` only. "Not in stock" is a stock claim no tool returned, like the unsupported stock claims merged in batch 4 (support-0164, 0136). Not `bad_search_false_claim`: the query used the user's own words. The strict keyword search is noted as a tool issue. |
| 2 | `721279cb…` (0247) | Withholds an available answer: claims it cannot see listings, although `search_products` can list the store's vases (the expected answer flags duplicate "Heavy-Duty Vase" titles) | `question_not_answered` | **Accepted.** An answer was one search away; the agent offered to escalate instead. |
| 3 | `1fbc58d3…` (0122 t2) | Misstates the policy: up to 3 days to ship + up to 7 in transit is the maximum (about 10 days), not the "best case" | `fact_not_supported_by_source` | **Accepted.** cw-shipping gives upper limits; calling their sum the best case is wrong. |
| 4 | `d2daf6c9…`, `e53afbfa…` (0135) | Predicts a possible exception ("may be able to make an exception") that no tool or policy supports | `unconfirmed_outcome_promised` (hedged, borderline) | **Rejected.** "May be able to" is hedged and paired with an offer to escalate; it promises nothing. Same rule as the hedged replies I labeled absent in Part E. |
| 5 | `c51439f7…` (0196) | Promises an outcome ("they'll make sure everything is set up correctly before you place your next order") | `unconfirmed_outcome_promised` | **Rejected.** It describes what the human agent will help with after a confirmed ticket, like support-0095 ("you'll keep your same account"), which I chose as a close negative for this mode. |

**Outcome:** 2 accepted, 1 revised, 2 rejected. There are no new modes: every accepted or revised candidate fits an existing mode. These runs are outside my 119-trace review sample, so the taxonomy, the 952 labels and the sample fractions are unchanged.

## Case with uncertainty or an alternative explanation

**Run `25f7bb73…` (workshop-0227, camping stove under $25 at Trailhead Supply)**

- **What happened:**
  - The agent searched `"camping stove"` in Trailhead Supply (under $25, then with no price limit) and got 0 results both times.
  - It replied that the store "doesn't currently have camping stoves in stock".
  - Replaying the search offline, `"stove"` or `"camp stove"` returns 2 matches: Signature Camp Stove ($12.75) and Heavy-Duty Camp Stove ($19.00).
- **Why the search failed:** search requires every word of the query to appear in the title or description, and "camping" is not in "Camp Stove".
- **Explanation A (agent failure):** the reply turns an empty keyword search into a definite "not in stock" claim. The stock level is never returned by the tool. That fits `fact_not_supported_by_source`.
- **Explanation B (search design):** the query used the user's own words ("a camping stove"), so the agent did not distort the request. `bad_search_false_claim` requires a distorted input, so it may not apply. The deeper cause is the strict keyword matching in `search_products`, a tool design issue rather than an agent mistake.
- **Uncertain:** whether to label this as an agent failure (A), a tool limitation (B), or both. A product fix could go either way: teach the agent to retry with a shorter query before saying "none", or loosen the search matching.

**Second uncertain case, run `c51439f7…` (workshop-0196).**
- The SPEC pulls two ways:
  - SCOPE-2 says the agent **refuses** payment-card changes.
  - ESC-2 says account changes of any kind **go to a human**.
- The agent escalated. It is unclear whether refusing or escalating is correct, which is why the scenario's expected outcome is "human judgment".
- The promise in the reply (candidate 5) is a separate question.
