import time
import logging
import uuid
from exchange import DeltaExchangeClient
from order_manager import OrderManager
from firebase_client import store_order
import config

logger = logging.getLogger(__name__)

class TradeManager:
    def __init__(self):
        self.client = DeltaExchangeClient()
        self.order_manager = OrderManager()
        self.highest_price = None

    def get_current_price(self, product_symbol):
        try:
            ticker = self.client.exchange.fetch_ticker(product_symbol)
            price = ticker.get('last')
            return float(price)
        except Exception as e:
            logger.error("Error fetching current price for %s: %s", product_symbol, e)
            raise

    def monitor_trailing_stop(self, bracket_order_id, product_symbol, trailing_stop_percent, update_interval=10):
        logger.info("Starting trailing stop monitoring for %s", product_symbol)
        self.highest_price = self.get_current_price(product_symbol)
        logger.info("Initial highest price: %s", self.highest_price)

        while True:
            try:
                current_price = self.get_current_price(product_symbol)
            except Exception as e:
                logger.error("Error fetching price, retrying: %s", e)
                time.sleep(update_interval)
                continue

            if current_price > self.highest_price:
                self.highest_price = current_price
                logger.info("New highest price: %s", self.highest_price)

            new_stop_loss = self.highest_price * (1 - trailing_stop_percent / 100.0)
            logger.info("Current price: %.2f, Calculated new stop loss: %.2f", current_price, new_stop_loss)

            new_stop_loss_order = {
                "order_type": "limit_order",
                "stop_price": str(round(new_stop_loss, 2)),
                "limit_price": str(round(new_stop_loss * 0.99, 2))
            }

            try:
                modified_order = self.order_manager.modify_bracket_order(bracket_order_id, new_stop_loss_order=new_stop_loss_order)
                logger.info("Modified bracket order: %s", modified_order)
            except Exception as e:
                logger.error("Error modifying bracket order: %s", e)

            time.sleep(update_interval)

    def place_market_order(self, symbol, side, amount, params=None):
        try:
            order = self.client.exchange.create_order(symbol, 'market', side, amount, None, params or {})
            order_id = order.get('id', str(uuid.uuid4()))
            order_info = {
                'id': order_id,
                'symbol': symbol,
                'side': side,
                'amount': amount,
                'params': params or {},
                'status': order.get('status', 'open'),
                'timestamp': order.get('timestamp', int(time.time() * 1000))
            }
            self.order_manager.orders[order_id] = order_info
            store_order("MAIN", order_id, order_info)
            logger.info("Market order placed: %s", order_info)
            return order_info
        except Exception as e:
            logger.error("Error placing market order for %s: %s", symbol, e)
            raise

if __name__ == '__main__':
    tm = TradeManager()
    print("Testing market order placement...")
    try:
        market_order = tm.place_market_order("BTCUSD", "buy", 1, params={"time_in_force": "ioc"})
        print("Market order placed:", market_order)
    except Exception as e:
        print("Failed to place market order:", e)