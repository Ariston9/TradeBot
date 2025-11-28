# import socketio
# import asyncio

# from .config import PO_SESSION_TOKEN

# PO_WS_URL = "wss://quotes-gw.pocketoption.com/realtime"

# CURRENT_PO_PRICE = {}  # { "EURUSD": {"mid":..., "bid":..., "ask":...}, ... }

# PO_ASSETS = [
#     "EURUSD","GBPUSD","USDJPY","USDCAD","AUDUSD","NZDUSD",
#     "EURJPY","GBPJPY","CADJPY",
#     "OTC_EURUSD","OTC_GBPUSD","OTC_USDCAD","OTC_USDJPY"
# ]

# sio = socketio.AsyncClient(
#     reconnection=True,
#     reconnection_attempts=999999,
#     reconnection_delay=3,
#     logger=False,
#     engineio_logger=False
# )


# def po_key(pair: str) -> str:
#     p = pair.replace(" ", "").replace("/", "")
#     if p.startswith("OTC") and not p.startswith("OTC_"):
#         p = p.replace("OTC", "OTC_", 1)
#     return p


# @sio.event
# async def connect():
#     print("⚡ Connected to PocketOption WS")
#     sub_msg = ["subscribe", {"assets": PO_ASSETS}]
#     await sio.emit("message", sub_msg)
#     print("📡 Subscribed:", PO_ASSETS)


# @sio.event
# async def disconnect():
#     print("❌ Disconnected from PocketOption")


# @sio.on("message")
# async def on_message(data):
#     global CURRENT_PO_PRICE
#     try:
#         if isinstance(data, list) and data[0] == "tick":
#             payload = data[1]
#             asset = payload.get("asset")
#             price = payload.get("price")
#             bid = payload.get("bid", price)
#             ask = payload.get("ask", price)
#             if asset and price:
#                 CURRENT_PO_PRICE[asset] = {
#                     "mid": float(price),
#                     "bid": float(bid) if bid is not None else float(price),
#                     "ask": float(ask) if ask is not None else float(price),
#                 }
#     except Exception as e:
#         print("⚠️ WS parse error:", e)


# async def pocketoption_price_feed():
#     headers = {
#         "User-Agent": "Mozilla/5.0",
#         "Cookie": f"session={PO_SESSION_TOKEN}"
#     }
#     while True:
#         try:
#             await sio.connect(PO_WS_URL, headers=headers)
#             await sio.wait()
#         except Exception as e:
#             print("❌ WS error:", e)
#             print("⏳ Reconnecting in 3s...")
#             await asyncio.sleep(3)
