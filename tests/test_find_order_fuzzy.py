"""find_order matches product names when the query adds store names or typos.

The agent often sends queries such as "socket set copperline" that combine
the product with the store. find_order must still match the product, keep
newest-first order, and must not match products that share only one word.
"""

from __future__ import annotations

from agent import tools
from agent.auth import AuthContext


def _order_ids(ctx: AuthContext, query: str) -> list[int]:
    result = tools.find_order(ctx, query)
    assert result["ok"] is True
    return [order["order_id"] for order in result["orders"]]


def test_find_order_matches_product_when_query_adds_store_name(world) -> None:
    shopper = AuthContext(user_id=212, role="shopper")
    assert 161 in _order_ids(shopper, "socket set copperline")


def test_find_order_matches_corrected_product_not_earlier_one(world) -> None:
    shopper = AuthContext(user_id=71, role="shopper")
    ids = _order_ids(shopper, "puzzle Wooden Whale Workshop")
    assert 9720 in ids
    assert 129 not in ids


def test_find_order_tolerates_a_typo_in_a_long_word(world) -> None:
    shopper = AuthContext(user_id=71, role="shopper")
    assert 9720 in _order_ids(shopper, "puzzel")


def test_find_order_rejects_products_sharing_one_word(world) -> None:
    shopper = AuthContext(user_id=283, role="shopper")
    ids = _order_ids(shopper, "woven desk lamp")
    assert 517 not in ids  # Woven Card Game shares only "woven"
    assert 1023 not in ids  # Classic Headlamp is not a desk lamp
