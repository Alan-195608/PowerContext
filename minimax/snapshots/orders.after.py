"""Small order listing service; input order and caller data are preserved."""


_VALID_STATUSES = ("pending", "paid", "cancelled")


def list_orders(orders, status=None):
    """Return independent order dictionaries, optionally filtered by status."""
    if status is not None and (
        not isinstance(status, str) or status not in _VALID_STATUSES
    ):
        raise ValueError("status must be one of: pending, paid, cancelled")

    if status is None:
        return [dict(order) for order in orders]

    return [dict(order) for order in orders if order.get("status") == status]
