import time
import logging
from exchange import DeltaExchangeClient
import config
import binance_ws
from trade_manager import TradeManager

logger = logging.getLogger(__name__)

class PositionTracker:
    def __init__(self, client):
        self.client = client

    def get_valid_positions(self):
        try:
            positions = self.client.fetch_positions()
            return [pos for pos in positions if self._is_valid_position(pos)]
        except Exception as e:
            logger.error("Position fetch error: %s", e)
            return []

    def _is_valid_position(self, position):
        size = self._get_position_size(position)
        if size == 0:
            return False
        symbol = position.get('info', {}).get('product_symbol') or position.get('symbol')
        return symbol and "BTCUSD" in symbol

    def _get_position_size(self, position):
        size_str = position.get('size') or position.get('contracts') or "0"
        try:
            return float(size_str)
        except ValueError:
            return 0.0

class ProfitCalculator:
    @staticmethod
    def calculate_profit(position, live_price):
        entry = ProfitCalculator._get_entry_price(position)
        size = ProfitCalculator._get_position_size(position)

        if entry is None or size == 0:
            return None

        return {
            'percentage': ProfitCalculator._profit_percentage(entry, size, live_price),
            'raw': ProfitCalculator._raw_profit(entry, size, live_price)
        }

    @staticmethod
    def _get_entry_price(position):
        entry = (position.get('entryPrice')
                 or position.get('entry_price')
                 or position.get('info', {}).get('entry_price'))
        try:
            return float(entry)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _get_position_size(position):
        size_str = position.get('size') or position.get('contracts') or "0"
        try:
            return float(size_str)
        except ValueError:
            return 0.0

    @staticmethod
    def _profit_percentage(entry, size, live_price):
        if size > 0:
            return (live_price - entry) / entry
        return (entry - live_price) / entry

    @staticmethod
    def _raw_profit(entry, size, live_price):
        if size > 0:
            return (live_price - entry) * size
        return (entry - live_price) * abs(size)

class ProfitTrailing:
    def __init__(self, check_interval):
        self.client = DeltaExchangeClient()
        self.tracker = PositionTracker(self.client)
        self.trade_manager = TradeManager()
        self.check_interval = check_interval
        self.position_trailing_stop = {}
        self.trailing_config = config.PROFIT_TRAILING_CONFIG

    def _get_trailing_rule(self, profit_pct):
        if profit_pct < self.trailing_config["start_trailing_profit_pct"]:
            return None
        return next((level for level in reversed(self.trailing_config["levels"])
                     if profit_pct >= level["min_profit_pct"]), None)

    def _calculate_trailing_stop(self, entry, size, profit_pct, rule):
        if not rule or profit_pct < self.trailing_config["start_trailing_profit_pct"]:
            return self._fixed_stop_price(entry, size)
        if rule["trailing_stop_offset"]:
            return self._dynamic_stop_price(entry, size, rule)
        return self._partial_booking_price(entry, profit_pct, rule, size)

    def _fixed_stop_price(self, entry, size):
        fixed_sl = self.trailing_config["fixed_stop_loss_pct"]
        return entry * (1 - fixed_sl) if size > 0 else entry * (1 + fixed_sl)

    def _dynamic_stop_price(self, entry, size, rule):
        offset = rule["trailing_stop_offset"]
        return entry * (1 + offset) if size > 0 else entry * (1 - offset)

    def _partial_booking_price(self, entry, profit_pct, rule, size):
        fraction = rule.get("book_fraction", 1.0)
        return entry * (1 + profit_pct * fraction) if size > 0 else entry * (1 - profit_pct * fraction)

    def _update_stored_stop(self, order_id, new_stop, size):
        current_stop = self.position_trailing_stop.get(order_id)
        if current_stop is None:
            self.position_trailing_stop[order_id] = new_stop
            return new_stop
        improved_stop = max(current_stop, new_stop) if size > 0 else min(current_stop, new_stop)
        self.position_trailing_stop[order_id] = improved_stop
        return improved_stop

    def _should_trigger_stop(self, size, live_price, trailing_stop):
        return live_price < trailing_stop if size > 0 else live_price > trailing_stop

    def _close_position(self, symbol, size):
        side = "sell" if size > 0 else "buy"
        qty = abs(size)
        close_order = self.trade_manager.place_market_order(symbol, side, qty, params={"time_in_force": "ioc"})
        logger.info("Closed %s position: %s", side, close_order)
        return close_order

    def _update_bracket_order(self, order_id, trailing_stop):
        try:
            bracket_params = {
                "bracket_stop_loss_limit_price": str(trailing_stop),
                "bracket_stop_loss_price": str(trailing_stop),
                "bracket_stop_trigger_method": "last_traded_price"
            }
            return self.trade_manager.order_manager.attach_bracket_to_order(
                order_id, 27, "BTCUSD", bracket_params
            )
        except Exception as e:
            logger.error("Bracket update failed: %s", e)
            return None

    def _handle_profit_booking(self, position, live_price):
        order_id = position.get('id')
        size = self.tracker._get_position_size(position)
        entry = ProfitCalculator._get_entry_price(position)
        if not entry or size == 0:
            return False

        profit_data = ProfitCalculator.calculate_profit(position, live_price)
        if not profit_data:
            return False

        rule = self._get_trailing_rule(profit_data['percentage'])
        trailing_stop = self._calculate_trailing_stop(entry, size, profit_data['percentage'], rule)
        final_stop = self._update_stored_stop(order_id, trailing_stop, size)

        if self._should_trigger_stop(size, live_price, final_stop):
            self._close_position("BTCUSD", size)
            return True

        if rule and rule.get("book_fraction"):
            self._update_bracket_order(order_id, final_stop)
        return False

    def _display_position_status(self, position, live_price):
        profit_data = ProfitCalculator.calculate_profit(position, live_price)
        entry = ProfitCalculator._get_entry_price(position)
        size = self.tracker._get_position_size(position)
        trailing_stop = self.position_trailing_stop.get(position.get('id'))
        profit_usd = profit_data['raw'] / 1000 if profit_data else None
        profit_inr = profit_usd * 85 if profit_usd else None

        logger.info(
            "Order: %s | Size: %s | Entry: %.2f | Live: %.2f | Profit: %.2f%% | USD: %.2f | INR: %.2f | Stop: %.2f",
            position.get('id'), size, entry, live_price,
            profit_data['percentage'] * 100 if profit_data else 0,
            profit_usd or 0,
            profit_inr or 0,
            trailing_stop or 0
        )

    def track(self):
        binance_ws.run_in_thread()
        self._wait_for_price_initialization()
        last_refresh = time.time()

        while True:
            live_price = binance_ws.current_price

            if time.time() - last_refresh > 300:
                self.position_trailing_stop.clear()
                last_refresh = time.time()

            if live_price:
                positions = self.tracker.get_valid_positions()
                if not positions:
                    logger.info("No active positions")
                    time.sleep(self.check_interval)
                    continue

                for position in positions:
                    self._display_position_status(position, live_price)
                    self._handle_profit_booking(position, live_price)

            time.sleep(self.check_interval)

    def _wait_for_price_initialization(self):
        timeout = 30
        start = time.time()
        while not binance_ws.current_price:
            if time.time() - start > timeout:
                logger.error("Price feed unavailable")
                return
            logger.info("Awaiting price feed...")
            time.sleep(2)

if __name__ == '__main__':
    pt = ProfitTrailing(check_interval=1)
    pt.track()
