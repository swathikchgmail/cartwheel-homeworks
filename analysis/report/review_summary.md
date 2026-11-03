# HW4 review summary

<!-- # Module 1 Trace Review Summary -->

## Reviewed Sample
A total of **119 traces across 78 conversations** from the Module 1 trace store (snapshot: 250 support conversations, 397 traces) were reviewed. Every turn of each selected conversation was evaluated, meaning batches are measured by traces rather than conversations. The distribution across batches (recorded in `analysis/state/sample_manifest.json`) is as follows:

| Batch | Sampling Method | Conversations | Traces | Conversations with Failures |
| :--- | :--- | :---: | :---: | :---: |
| **Batch 1** | Uniform random selection (15+ traces via seeded shuffle), followed by 15+ traces from 10 k-means clusters based on conversation shape | 20 | 33 | 16 |
| **Batch 2** | Role-based distribution (10+ traces per role across shopper, merchant, and support), with seeded shuffling within each role | 22 | 30 | 14 |
| **Batch 3** | Depth searches focused on tool activity and intent rather than outcomes (e.g., searches hitting limits, store-override return questions, bad tool data). Round 2 repeated the store-policy search using a revised definition. | 15 | 25 | 9 |
| **Batch 4** | Final check: Uniform selection of 15+ traces from conversations excluded from all previous batches | 11 | 15 | 9 |
| **Batch 5** | Additional final check using the same methodology to verify patterns surfaced in Batch 4 | 10 | 16 | 6 |
| **Total** | | **78** | **119** | **54** |

### Sample Breakdown
* **Roles:** 57 shopper, 14 merchant, and 7 support conversations. The role dimension was established prior to reviewing outcomes, and Batch 2 spreads the sample across roles.
* **Conversation Length:** 55 single-turn conversations and 23 multi-turn conversations (ranging from 2 to 6 turns).
* **Notes & Open Codes:** Each conversation contains one live note, resulting in 54 open codes (focusing solely on the first failure) and 24 "no failure" notes.
  * 16 open codes originated independently.
  * 38 open codes were accepted AI suggestions reviewed within the application.
  * 8 AI suggestions were rejected with documented rationale (`analysis/state/suggestions.json`).
  * Superseded notes are archived rather than deleted.

---

## Final Taxonomy
The final taxonomy consists of eight modes (`analysis/state/patterns.json`). Each mode includes a binary definition, a boundary distinguishing it from its nearest neighbor, 3 to 4 close negatives, and a documented requirement source.

| Mode | Open Codes | Evaluator | Requirement Source |
| :--- | :---: | :---: | :--- |
| `fact_not_supported_by_source` | 11 | Judge | RESP-3, `facts.yaml` |
| `wrong_governing_policy` | 9 | Judge | `cw-store-overrides`, `store_overrides.precedence`, `cw-disputes`, ESC-3, RESP-1 |
| `policy_not_cited` | 8 | Judge | RESP-1 |
| `question_not_answered` | 8 | Judge | ESC-1 through ESC-4, SCOPE-2, RESP-5 |
| `invalid_data_not_flagged` | 6 | Judge | RESP-3, ESC-4 |
| `unconfirmed_outcome_promised` | 5 | Judge | RESP-2, ESC-1, `facts.yaml` (`refund_method`) |
| `bad_search_false_claim` | 4 | Judge | TOOL-3 contract, RESP-3 |
| `results_truncated_silently` | 3 | Code | RESP-3 |

> **Example Rule Mapping:** `policy_not_cited` maps directly to **RESP-1**, which mandates citing the governing policy ID behind any policy statement. A response can be factually correct yet still fail this requirement—for instance, telling a user *"yes, you can return it"* without citing `cw-returns`.

No revisions were made to `SPEC.md`.

---

## Final Check & Emerging Patterns in Late Batches
* **Batch 4 (Planned Final Check):** Out of 15 traces (spanning 11 conversations), 7 traces revealed consequential patterns not yet covered by existing definitions:
  * Disputes processed incorrectly as standard refunds (`support-0220`, `0250`, `0179`).
  * Unsupported stock claims (`support-0164`, `0136`).
  * *Resolution:* Rather than creating new modes (as a single product fix resolves each pattern alongside an existing mode), two existing modes were broadened accordingly.
* **Batch 5 (Extra Verification):** Following the patterns discovered in Batch 4, a secondary review of 16 traces yielded zero previously unseen modes, indicating that the taxonomy is reasonably stable.

---

## Taxonomy Revisions

### 1. `store_policy_ignored` $\rightarrow$ `wrong_governing_policy` (Batch 4)
* **Rationale:** The original mode only flagged replies that applied the platform return window instead of a store-specific window. In Batch 4, multiple users requested charge disputes, but the agent responded using the refund window policy instead of `cw-disputes` (which mandates human escalation under ESC-3). 
* **Fix:** Because both errors stem from failing to determine the governing policy prior to answering, the modes were merged, renamed, and redefined. Historical definitions and reasons have been preserved.

### 2. Splitting `incomplete_or_invalid_results_shown` (Batch 2)
* **Rationale:** This initial category was rejected and split into `results_truncated_silently` and `invalid_data_not_flagged`. 
* **Fix:** Truncated lists require the agent to explicitly state that additional results exist, whereas bad records require explicit data flagging. Because these require distinct fixes, they were separated.

---

## Rejected Search Suggestion
During Batch 3, a store-policy search flagged `support-0080` because a Saltbox Pantry order (governed by a 7-day store window) appeared in the user's order list. However, because the user's query concerned shipping duration—which was answered correctly using `cw-shipping` without invoking return windows—the suggestion was rejected. This clarification helped refine the rule boundary: the mode applies exclusively to the specific order referenced by the user, not extraneous override-store orders present in the list.

---

## Part E: Labels and Sample Fractions
Every final mode was applied across all 119 reviewed traces, generating **952 present/absent judgments** ($8 \times 119$). Each judgment is recorded in Langfuse as a numeric score (where $1 = \text{failure present}$) and backed up in `analysis/state/labels/<mode>.jsonl`. A verification check confirmed that all 952 scores match Langfuse records.

### Label Generation Methodology
* **406 pairs** derived directly from manual review notes (a "no failure" note marks all modes absent; a linked open code marks that mode present). Turns preceding the first failure are marked absent for all modes.
* **All 952 pairs** were initially drafted by a model (`claude-haiku-5-5`, costing $0.11; drafts located in `analysis/state/label_drafts.json`).
* **82 drafts were reviewed:** the coding agent proposed Y/N with a reason for each, and I accepted them all (46 present, 36 absent).

* **464 passing drafts** were accepted as-is.

### Strict Application Rules
* Each defect is mapped to exactly one mode.
* Distinct defects within the same reply are counted under separate modes.
* Close negatives remain marked as absent.

| Mode | Failures | Passes | Sample Fraction |
| :--- | :---: | :---: | :---: |
| `fact_not_supported_by_source` | 17 | 102 | 14.3% |
| `policy_not_cited` | 13 | 106 | 10.9% |
| `question_not_answered` | 11 | 108 | 9.2% |
| `wrong_governing_policy` | 9 | 110 | 7.6% |
| `unconfirmed_outcome_promised` | 8 | 111 | 6.7% |
| `invalid_data_not_flagged` | 7 | 112 | 5.9% |
| `results_truncated_silently` | 7 | 112 | 5.9% |
| `bad_search_false_claim` | 3 | 116 | 2.5% |

Overall, **67 of the 119 traces** contain at least one failure. 

> **Important Note:** These metrics represent **sample fractions rather than true prevalence estimates**. Clustering, role distribution, and targeted depth searches intentionally altered sample composition. Homework 5 will calculate true prevalence across the full Module 1 trace store.

---

## Preparation for Homework 5
Homework 5 requires a minimum threshold of 30 "Pass" and 30 "Fail" labels per mode. While all modes currently exceed the threshold for passing labels (at least 102 each), **none currently meet the 30-failure requirement**. 

To bridge this gap, synthetic scenarios targeting specific failure modes will be utilized:

| Mode | Current Failures | Additional Fails Needed |
| :--- | :---: | :---: |
| `fact_not_supported_by_source` | 17 | 13 |
| `policy_not_cited` | 13 | 17 |
| `question_not_answered` | 11 | 19 |
| `wrong_governing_policy` | 9 | 21 |
| `unconfirmed_outcome_promised` | 8 | 22 |
| `invalid_data_not_flagged` | 7 | 23 |
| `results_truncated_silently` | 7 | 23 |
| `bad_search_false_claim` | 3 | 27 |

---

## Part C: Raindrop Workshop
- **Runs:** I ran 8 scenarios that are not in the review sample (10 turns: shopper, merchant and support roles, no refunds or cancellations) with local Raindrop Workshop instrumentation, and inspected each run.
- **Setup:** Workshop showed each run's input and reply. The tool calls came from the matching Langfuse trace (same trace id), because Raindrop tool spans need a cloud write key and would export every agent span to Raindrop's cloud.
- **Results:**
  - The coding agent proposed 5 candidate failures: 2 accepted, 1 revised, 2 rejected.
  - No new modes appeared. These runs are outside the 119-trace sample, so the taxonomy, labels and sample fractions above are unchanged.
- **Example suggestion:** support-0227 said a store "doesn't have camping stoves in stock" after a keyword search for "camping stove" returned nothing; two "Camp Stove" products under $25 exist. I revised the suggestion from `bad_search_false_claim` to `fact_not_supported_by_source` (the query used the user's own words; the stock claim had no source). I noted the strict keyword matching as a tool issue.
- Details are in `analysis/report/workshop_notes.md`.