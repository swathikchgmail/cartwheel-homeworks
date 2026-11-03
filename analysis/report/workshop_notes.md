# Workshop Notes (Part C)

## Setup

* **Workshop:** Raindrop Workshop is installed locally (`http://localhost:5899`). Raindrop Cloud is not used.
* **Instrumentation:** `observability/raindrop_workshop.py` and a hook in `server/app.py`.
  * Each server turn constitutes one Workshop interaction (input, reply, role, scenario ID, prompt version).
  * The interaction shares the turn's trace ID with Langfuse.
  * Instrumentation remains disabled unless `RAINDROP_LOCAL_DEBUGGER` is set, ensuring that HW4 traces and existing Langfuse/OpenLLMetry tracing are unaffected.
* **Limitation:**
  * In raindrop-ai 0.0.75, tool spans require Raindrop tracing. This tracing necessitates a Raindrop Cloud write key and adds its exporter to the Langfuse tracer provider, which would inadvertently send every agent span to Raindrop's cloud.
  * To maintain privacy, the Workshop runs locally, displaying each run's input and reply.
  * Tool calls are read from the matching Langfuse trace using the shared ID.
* **Runs:** 8 scenarios (selected with a fixed seed) across shopper, merchant, and support roles that were not previously reviewed in HW4.
  * Scenarios cover order lookups, return eligibility, product searches, policy questions, and an out-of-scope request (none involving refunds or cancellations).
  * Agent model: `claude-haiku-4-5`.
  * Scenario IDs were renamed to `workshop-*` to keep these traces separate from the HW4 `support-*` set.

## Inspected Runs

*Note: The run ID serves as both the Workshop run ID and the Langfuse trace ID.*

| Run ID | Scenario | Turn | Role | Tools Called | Agent Observation |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `9e3a491c…` | workshop-0122 | 1 | shopper | find_order | **Correct:** Order 4453 placed, not shipped. |
| `1fbc58d3…` | workshop-0122 | 2 | shopper | search_help_center | Refers to the 10-day total (3 to ship + 7 in transit) as the "best case"; however, this represents the maximum time allowed by the policy. **Candidate 3.** |
| `d2daf6c9…` | workshop-0135 | 1 | shopper | find_order, search_help_center, get_policy | **Correctly identified as ineligible** (delivered 59 days ago, citing `cw-returns`), then states that a human "may be able to make an exception." **Candidate 4.** |
| `e53afbfa…` | workshop-0135 | 2 | shopper | none | Repeats the exception offer and prompts a human to check the store's return window instead of verifying it directly. **Candidate 4.** |
| `25f7bb73…` | workshop-0227 | 1 | shopper | search_products ×2 | Claims Trailhead Supply "doesn't currently have camping stoves in stock," despite two qualifying stoves under $25 existing in the catalog. **Candidate 1 (uncertain).** |
| `ffee0d21…` | workshop-0043 | 1 | shopper | search_help_center | **Correct:** 5 to 10 business days, citing `cw-refunds` (returned by the search). |
| `721279cb…` | workshop-0247 | 1 | merchant | none | Claims it has no tool to view listings and offers to escalate; `search_products` is actually accessible to every role. **Candidate 2.** |
| `e3a40478…` | workshop-0019 | 1 | merchant | search_help_center | **Correct:** Up to 15% on opened items, opt-in, citing `cw-restocking-fees`. |
| `f528b50c…` | workshop-0231 | 1 | support | get_order | **Correct:** Order 2799 delivered on 2026-01-16. |
| `c51439f7…` | workshop-0196 | 1 | shopper | escalate_to_human | Escalated a payment-card change, then promised the user that the agent "will make sure everything is set up correctly." **Candidate 5 (uncertain).** |

## Candidate Failures

| # | Run | Candidate (Coding Agent) | Closest Existing Mode | Decision |
| :--- | :--- | :--- | :--- | :--- |
| **1** | `25f7bb73…` (0227) | Unsupported "no stock" claim resulting from an empty keyword search | `fact_not_supported_by_source`, or `bad_search_false_claim` | **Revised** to `fact_not_supported_by_source` only. "Not in stock" represents a stock claim unsupported by any tool return, similar to the unsupported stock claims merged in batch 4 (`support-0164`, `0136`). It is not classified as `bad_search_false_claim` because the query utilized the user's exact wording; the strict keyword search is noted as an underlying tool limitation. |
| **2** | `721279cb…` (0247) | Withholds available answers: claims inability to see listings even though `search_products` can retrieve store vases (expected answers highlight duplicate "Heavy-Duty Vase" titles) | `question_not_answered` | **Accepted.** An answer was readily available via a single search, but the agent offered to escalate instead. |
| **3** | `1fbc58d3…` (0122 t2) | Misstates policy: up to 3 days to ship plus up to 7 in transit constitutes the maximum timeframe (approximately 10 days), not the "best case" | `fact_not_supported_by_source` | **Accepted.** The `cw-shipping` documentation outlines upper limits; summing them to denote a "best case" is incorrect. |
| **4** | `d2daf6c9…`, `e53afbfa…` (0135) | Predicts a potential exception ("may be able to make an exception") unsupported by tools or policy | `unconfirmed_outcome_promised` (hedged, borderline) | **Rejected.** The phrasing "may be able to" is hedged and accompanied by an escalation offer, making no firm promises. This follows the same ruling applied to hedged replies marked absent in Part E. |
| **5** | `c51439f7…` (0196) | Promises a specific outcome ("they'll make sure everything is set up correctly before you place your next order") | `unconfirmed_outcome_promised` | **Rejected.** This accurately describes the assistance a human agent provides following a confirmed support ticket, analogous to `support-0095` ("you'll keep your same account"), which serves as a close negative example for this mode. |

**Outcome:** 2 accepted, 1 revised, and 2 rejected. No new failure modes were introduced; all accepted or revised candidates fit seamlessly into existing categories. Because these runs fall outside the primary 119-trace review sample, the overall taxonomy, the 952 labels, and the sample fractions remain unchanged.

The coding agent proposed each decision with a reason; I reviewed them and accepted all five.

---

## Cases Involving Uncertainty or Alternative Explanations

### Run `25f7bb73…` (workshop-0227: Camping stove under $25 at Trailhead Supply)
* **What Happened:** 
  * The agent searched for `"camping stove"` within Trailhead Supply (initially filtered under $25, then subsequently without price limits) and yielded 0 results in both instances.
  * It responded that the store "doesn't currently have camping stoves in stock."
  * Offline replays of searches using `"stove"` or `"camp stove"` successfully return two matches: the Signature Camp Stove ($12.75) and the Heavy-Duty Camp Stove ($19.00).
* **Root Cause of Search Failure:** The search engine requires every word in the query to match terms in the product title or description, and the term "camping" is absent from "Camp Stove."
* **Explanation A (Agent Failure):** The response converts an empty keyword search into a definitive claim of zero stock. Since inventory levels are never explicitly returned by the tool, this aligns with `fact_not_supported_by_source`.
* **Explanation B (Search Design Flaw):** The query faithfully reflected the user's phrasing ("a camping stove"), meaning the agent did not distort the input. Consequently, `bad_search_false_icon` may not apply, shifting the primary fault to strict keyword matching within `search_products`.
* **Uncertainty:** Whether to categorize this as an agent error (A), a tool design constraint (B), or a combination of both. A product-level fix could involve instructing the agent to retry with shortened search terms before stating "none," or adjusting the search backend to use looser matching algorithms.

### Run `c51439f7…` (workshop-0196)
* **Specification Conflict:** The specifications pull in two directions:
  * `SCOPE-2` states that the agent must **refuse** payment-card changes.
  * `ESC-2` dictates that all account modifications must be **routed to a human**.
* **Resolution:** The agent opted to escalate. It remains ambiguous whether refusal or escalation is the correct approach, which explains why the scenario's expected outcome is classified as requiring "human judgment."
* **Promise Evaluation:** The promise made in the response (Candidate 5) represents a separate evaluation question as analyzed above.