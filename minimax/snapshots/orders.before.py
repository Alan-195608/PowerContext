"""Small order listing service; input order and caller data are preserved."""


def list_orders(orders, status=None):
    """Return independent order dictionaries in their original order."""
    return [dict(order) for order in orders]
