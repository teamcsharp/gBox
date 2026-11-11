"""Scope map orders to the floor they were clicked on.

A click on floor 11 wrote an order for (40, 130); after warping to Cave3 the bot was still walking toward those coordinates, which mean nothing in a
different area. Orders now carry the floor they were issued on, and the bot ignores an order whose floor is not the floor it is standing on - an
order is a place in an area, not a universal coordinate.
"""
import pathlib

# 1. the minimap records the floor with the order
mm = pathlib.Path(r"C:\_tools\gBox\.tmp\minimap_live.py")
text = mm.read_text(encoding="utf-8")
old = '''                order = {"x": float(query["x"][0]), "z": float(query["z"][0]), "t": round(time.time(), 2)}'''
new = '''                try:
                    order_floor = int(query.get("floor", ["0"])[0])
                except Exception:                                 # noqa: BLE001
                    order_floor = 0
                order = {"x": float(query["x"][0]), "z": float(query["z"][0]),
                         "floor": order_floor, "t": round(time.time(), 2)}'''
if text.count(old) == 1:
    text = text.replace(old, new)
    mm.write_text(text, encoding="utf-8")
    print("minimap: orders now carry their floor")

old_click = '''"    await fetch(`/api/order?x=${wx.toFixed(1)}&z=${wz.toFixed(1)}`,{method:'POST'});"'''
new_click = '''"    await fetch(`/api/order?x=${wx.toFixed(1)}&z=${wz.toFixed(1)}&floor=${st.floor}`,{method:'POST'});"'''
if text.count(old_click) == 1:
    text = text.replace(old_click, new_click)
    mm.write_text(text, encoding="utf-8")
    print("minimap: click sends the floor with the order")

# 2. self-play ignores an order from another floor
sp = pathlib.Path(r"C:\_tools\gBox\.tmp\selfplay2.py")
stext = sp.read_text(encoding="utf-8")
old_take = '''    if payload.get("t", 0) <= _last_order[0]:
        return None
    _last_order[0] = payload.get("t", 0)
    return {"x": payload["x"], "z": payload["z"]}'''
new_take = '''    if payload.get("t", 0) <= _last_order[0]:
        return None
    _last_order[0] = payload.get("t", 0)
    order_floor = payload.get("floor")
    if order_floor is not None and int(order_floor) != floor():
        log(f"ignoring an order for floor {order_floor} while on floor {floor()}")
        return None
    return {"x": payload["x"], "z": payload["z"]}'''
if stext.count(old_take) != 1:
    raise SystemExit(f"take_order pattern count {stext.count(old_take)}")
stext = stext.replace(old_take, new_take)
sp.write_text(stext, encoding="utf-8")
print("self-play: orders are ignored on the wrong floor")
