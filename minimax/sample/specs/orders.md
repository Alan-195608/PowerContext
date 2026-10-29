# 订单列表规格 v1

## ORD-001 status 筛选
list_orders(orders, status=None) 在 status=None 时返回所有订单。
status 为 pending、paid、cancelled 之一时，只返回状态相等的订单。
空字符串、其他字符串和非字符串非 None 值抛出 ValueError；错误文本包含 status。

## ORD-002 兼容性
筛选和不筛选都必须保留输入顺序、返回新的列表和浅拷贝的字典，不修改调用方数据。
空订单列表仍校验 status；有效筛选作用于空列表时返回 []。
订单中缺少 status 的记录在不筛选时保留，在有效 status 筛选时排除。
