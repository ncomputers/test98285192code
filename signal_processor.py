import time
import logging
import json
from order_manager import OrderManager
from trade_manager import TradeManager
from firebase_client import stream_signal
import config

logger = logging.getLogger(__name__)

class OrderHandler:
    def __init__(self, order_manager, trade_manager):
        self.order_manager = order_manager
        self.trade_manager = trade_manager

    @staticmethod
    def adjust_price(price, offset):
        try:
            return float(price) + offset
        except Exception:
            return price

    def cancel_conflicting_orders(self, symbol, new_side):
        try:
            orders = self.order_manager.client.exchange.fetch_open_orders(symbol)
            for order in orders:
                if order.get('status', '').lower() != 'open':
                    continue
                order_side = order.get('side', '').lower()
                if new_side == "" or order_side != new_side.lower():
                    self._cancel_order(order['id'], symbol)
        except Exception as e:
            logger.error(f"Error canceling conflicting orders: {e}")

    def cancel_same_side_orders(self, symbol, side):
        try:
            orders = self.order_manager.client.exchange.fetch_open_orders(symbol)
            for order in orders:
                if order.get('side', '').lower() == side.lower():
                    self._cancel_order(order['id'], symbol)
        except Exception as e:
            logger.error(f"Error canceling same-side orders: {e}")

    def _cancel_order(self, order_id, symbol):
        try:
            self.order_manager.client.cancel_order(order_id, symbol)
            logger.info(f"Canceled order: {order_id}")
        except Exception as e:
            logger.error(f"Error canceling order {order_id}: {e}")

    def pending_order_exists(self, symbol, side):
        try:
            orders = self.order_manager.client.exchange.fetch_open_orders(symbol)
            return any(order.get('side', '').lower() == side.lower() 
                      and order.get('status', '').lower() == 'open' for order in orders)
        except Exception as e:
            logger.error(f"Error checking pending orders: {e}")
            return False

    def place_limit_order(self, symbol, side, entry_price):
        try:
            return self.order_manager.place_order(
                symbol, side, 1, entry_price, params={"time_in_force": "gtc"}
            )
        except Exception as e:
            logger.error(f"Limit order failed: {e}")
            return None

    def attach_bracket(self, order_id, symbol, sl_price, tp_price):
        bracket_params = {
            "bracket_stop_loss_limit_price": str(sl_price),
            "bracket_stop_loss_price": str(sl_price),
            "bracket_take_profit_limit_price": str(tp_price),
            "bracket_take_profit_price": str(tp_price),
            "bracket_stop_trigger_method": "last_traded_price"
        }
        try:
            return self.order_manager.attach_bracket_to_order(
                order_id, 27, symbol, bracket_params
            )
        except Exception as e:
            logger.error(f"Bracket attachment failed: {e}")
            return None

    def close_positions(self, symbol):
        try:
            positions = self.order_manager.client.fetch_positions()
            for pos in positions:
                self._close_position(pos, symbol)
        except Exception as e:
            logger.error(f"Position closing error: {e}")

    def _close_position(self, pos, symbol):
        pos_symbol = pos.get('info', {}).get('product_symbol') or pos.get('symbol')
        if not pos_symbol or symbol not in pos_symbol:
            return

        pos_size = pos.get('size') or pos.get('contracts') or "0"
        try:
            pos_amount = float(pos_size)
        except ValueError:
            return

        if pos_amount == 0:
            return

        side = "buy" if pos_amount < 0 else "sell"
        qty = abs(pos_amount)
        logger.info(f"Closing {side} position of size {qty}")
        self.trade_manager.place_market_order(
            symbol, side, qty, params={"time_in_force": "ioc"}
        )

    def has_open_position(self, symbol, side):
        try:
            positions = self.order_manager.client.fetch_positions()
            for pos in positions:
                symbol_match = (pos.get('info', {}).get('product_symbol') or pos.get('symbol')) == symbol
                size = float(pos.get('size') or pos.get('contracts') or 0)
                if not symbol_match or size == 0:
                    continue
                return (side == "buy" and size > 0) or (side == "sell" and size < 0)
        except Exception as e:
            logger.error("Error checking open position: %s", e)
        return False


class SignalProcessor:
    def __init__(self, symbol="BTCUSD"):
        self.symbol = symbol
        self.last_signal = None
        self.order_handler = OrderHandler(OrderManager(), TradeManager())

    def process(self, signal_data):
        if not self._validate_signal(signal_data):
            return

        signal_type = self._get_signal_type(signal_data)
        if signal_type == "tp":
            self._process_tp_signal()
            return

        if signal_type not in ("buy", "sell"):
            logger.warning(f"Invalid signal: {signal_data.get('text', '')}")
            return

        self._process_trade_signal(signal_data, signal_type)

    def _process_tp_signal(self):
        logger.info("Processing take profit signal")
        self.order_handler.close_positions(self.symbol)

    def _process_trade_signal(self, signal_data, side):
        opposite_side = "sell" if side == "buy" else "buy"
        self.order_handler.close_positions(self.symbol)  # always close before new

        self._cancel_existing_orders(side)
        time.sleep(2)

        if self.order_handler.pending_order_exists(self.symbol, side):
            logger.info(f"Existing {side} order present")
            return

        prices = self._calculate_prices(signal_data, side)
        self._place_order_with_bracket(side, prices)

    def _calculate_prices(self, signal_data, side):
        raw_price = signal_data["last_signal"].get("price")
        try:
            raw_price = float(raw_price)
        except (ValueError, TypeError):
            logger.warning("Invalid or missing price. Using fallback from Binance.")
            from binance_ws import current_price as fallback_price
            raw_price = fallback_price

        offset = config.FIXED_OFFSET

        supply = signal_data.get("supply_zone", {}).get("min")
        demand = signal_data.get("demand_zone", {}).get("min")

        if side == "sell":
            entry = raw_price + 50 if raw_price else 0
            sl = raw_price + 3000 if raw_price else 0
            tp = raw_price - 500 if raw_price else 0
        else:
            entry = raw_price - 50 if raw_price else 0
            sl = raw_price - 500 if raw_price else 0
            tp = raw_price + 3000 if raw_price else 0

        try:
            if supply and demand:
                supply = float(supply)
                demand = float(demand)
                if side == "sell":
                    entry = self.order_handler.adjust_price(raw_price, offset)
                    sl = self.order_handler.adjust_price(supply, offset)
                    tp = self.order_handler.adjust_price(demand, offset)
                else:
                    entry = self.order_handler.adjust_price(raw_price, -offset)
                    sl = self.order_handler.adjust_price(demand, -offset)
                    tp = self.order_handler.adjust_price(supply, -offset)
        except Exception:
            logger.warning("Zone fallback in effect due to invalid zone data.")

        return entry, sl, tp

    def _place_order_with_bracket(self, side, prices):
        entry_price, sl_price, tp_price = prices
        order = self.order_handler.place_limit_order(self.symbol, side, entry_price)
        if order:
            self.order_handler.attach_bracket(order['id'], self.symbol, sl_price, tp_price)

    def _cancel_existing_orders(self, side):
        self.order_handler.cancel_conflicting_orders(self.symbol, side)
        self.order_handler.cancel_same_side_orders(self.symbol, side)

    def _get_signal_type(self, signal_data):
        text = signal_data["last_signal"].get("text", "").lower()
        if "tp" in text or "take profit" in text:
            return "tp"
        return "buy" if "buy" in text else "sell" if "short" in text else None

    def _validate_signal(self, signal_data):
        if not signal_data:
            return False

        if not self._is_new_signal(signal_data):
            logger.debug("Duplicate signal")
            return False

        self.last_signal = signal_data
        return "last_signal" in signal_data and "text" in signal_data["last_signal"]

    def _is_new_signal(self, signal_data):
        return self.last_signal is None or \
            signal_data["last_signal"].get("text") != self.last_signal["last_signal"].get("text")


class TradingBot:
    def __init__(self):
        self.signal_processor = SignalProcessor()

    def start(self):
        logger.info("Starting signal listener")
        stream_signal("MAIN", self._firebase_callback)

    def _firebase_callback(self, message):
        print("\n[FIREBASE] Update Event:")
        print(json.dumps(message, indent=2))

        if message["event"] in ("put", "patch"):
            signal_data = message.get("data")
            print("[FIREBASE] Signal data extracted:")
            print(json.dumps(signal_data, indent=2))
            self.signal_processor.process(signal_data)


if __name__ == '__main__':
    TradingBot().start()
