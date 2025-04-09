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

    def adjust_price(self, price, offset):
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
            return any(order.get('side', '').lower() == side.lower() and order.get('status', '').lower() == 'open' for order in orders)
        except Exception as e:
            logger.error(f"Error checking pending orders: {e}")
            return False

    def place_limit_order(self, symbol, side, entry_price):
        try:
            return self.order_manager.place_order(symbol, side, 1, entry_price, params={"time_in_force": "gtc"})
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
            return self.order_manager.attach_bracket_to_order(order_id, 27, symbol, bracket_params)
        except Exception as e:
            logger.error(f"Bracket attachment failed: {e}")
            return None

    def handle_take_profit(self, symbol):
        try:
            positions = self.order_manager.client.fetch_positions()
            for pos in positions:
                pos_symbol = pos.get('info', {}).get('product_symbol') or pos.get('symbol')
                if not pos_symbol or symbol not in pos_symbol:
                    continue

                size = float(pos.get('size') or pos.get('contracts') or 0)
                if size == 0:
                    continue

                entry = float(pos.get('entryPrice') or pos.get('entry_price') or pos.get('info', {}).get('entry_price'))
                live_price = self.order_manager.client.exchange.fetch_ticker(symbol)['last']

                profit_pct = ((live_price - entry) / entry) if size > 0 else ((entry - live_price) / entry)
                profit_pct *= 100

                if profit_pct > 0:
                    stop_lock_price = entry + ((live_price - entry) * 0.5) if size > 0 else entry - ((entry - live_price) * 0.5)
                    bracket_params = {
                        "bracket_stop_loss_limit_price": str(stop_lock_price),
                        "bracket_stop_loss_price": str(stop_lock_price),
                        "bracket_stop_trigger_method": "last_traded_price"
                    }
                    self.order_manager.attach_bracket_to_order(pos.get('id'), 27, symbol, bracket_params)
                    logger.info(f"Profit > 0: Locking 50%% of profit with SL at {stop_lock_price}")
                else:
                    logger.info("Profit < 0: Closing position due to take profit in loss.")
                    side = "sell" if size > 0 else "buy"
                    self.trade_manager.place_market_order(symbol, side, abs(size), params={"time_in_force": "ioc"})

        except Exception as e:
            logger.error(f"Position closing error during take profit: {e}")

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


if __name__ == '__main__':
    om = OrderManager()
    try:
        limit_order = om.place_order("BTCUSD", "buy", 1, 45000)
        print("Limit order placed:", limit_order)

        bracket_params = {
            "bracket_stop_loss_limit_price": "50000",
            "bracket_stop_loss_price": "50000",
            "bracket_take_profit_limit_price": "55000",
            "bracket_take_profit_price": "55000",
            "bracket_stop_trigger_method": "last_traded_price"
        }

        updated_order = om.attach_bracket_to_order(
            order_id=limit_order['id'],
            product_id=27,
            product_symbol="BTCUSD",
            bracket_params=bracket_params
        )
        print("Bracket attached, updated order:", updated_order)

    except Exception as e:
        print("Operation failed:", e)
        exit(1)