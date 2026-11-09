# HW5 failure definition: policy_not_cited

**Requirement:** RESP-1 in `SPEC.md`: "Cite the policy identifier for every claim derived from a policy document."

**Question:** Does every policy statement in the evaluated reply cite the identifier of the policy it came from (for example `cw-returns`)?

**Labels:** 1 = Pass (failure absent), 0 = Fail (failure present).

## Fail (0)

The reply states something that comes from a policy document (a window, a fee, an eligibility rule, a timeline, an escalation rule) and does not give that policy's identifier. This includes:

- **Partial citation:** the reply makes two or more policy statements, and at least one has no identifier.
- **Name without identifier:** the reply names the policy ("per our returns policy") but does not give its identifier (`cw-returns`).
- **Store window without identifier:** the reply states a store's own window or rule ("Northwind Books allows 45 days") without citing `cw-store-overrides`.
- **Timeline without identifier:** the reply states a policy timeline without its identifier, for example "arrives in 5 to 10 business days" (`cw-refunds`) or "a human will follow up within 24 hours" (`cw-escalations`).
- **Rule without a number:** a policy rule counts even when the reply gives no number, for example "since this is above our auto-approval threshold, a human will review it" (`cw-refunds`) or "the order has passed the standard refund window" (`cw-returns`).
- **Exception or eligibility rule:** the reply refers to an exception to a policy rule, or to the reason an order is or is not eligible, without the identifier, for example "a human will determine if an exception to our refund eligibility is appropriate", "it's outside our standard return window", or "since this is a damage issue rather than a standard return" (`cw-returns`, `cw-refunds`).
- **No carry-over:** an identifier cited in an earlier turn does not cover the evaluated reply. Each reply must cite the policy behind its own statements, for example a later "You've got 30 days from delivery" without `cw-returns`.
- **Made-up rule:** the reply states a rule as if it were Cartwheel or store policy, but no policy or tool result says it, for example "since your item arrived damaged and you've already received the refund approval, you don't need to send it back" or "they'll have the authority to approve the refund given that the product was defective". With no identifier, this is a Fail. (Whether the rule is true is `fact_not_supported_by_source`; a reply can fail both.)

## Pass (1)

- Every policy statement in the reply has its identifier (one citation covers every statement in the same reply that comes from that same policy, for example "30 days from delivery (`cw-returns`)" followed by "stores can override this window"), or
- The reply makes no policy statement, or
- The reply's facts come only from tool results (order status, dates, prices, product lists), which need no identifier.

**Tool result or policy?** A number counts as a tool fact when an action or lookup tool returned it in this or an earlier turn, for example the `issue_refund` note "refund goes back to the original payment method in 5 to 10 business days" or `escalate_to_human` returning `sla_hours: 24`. The same number taken from a `get_policy` or `search_help_center` result is a policy statement and needs the identifier.

## Not this mode

- The reply cites or applies the wrong policy: `wrong_governing_policy`.
- The reply states a fact that no tool result or policy supports: `fact_not_supported_by_source`.

A reply can fail one of these modes and still pass `policy_not_cited`.

## Evidence the judge needs

The user message, the evaluated reply, the earlier turns needed to understand it, and the `search_help_center` and `get_policy` results. These show which statements came from a policy document.
