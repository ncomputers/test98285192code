import threading
import logging
from signal_processor import TradingBot
from profit_trailing import ProfitTrailing
from logger import setup_logging


def run_profit_trailing():
    trailing = ProfitTrailing(check_interval=1)
    trailing.track()


def main():
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting trading system...")

    # Start profit trailing as background thread
    trailing_thread = threading.Thread(target=run_profit_trailing, daemon=True)
    trailing_thread.start()

    # Start signal listener (Firebase-based)
    bot = TradingBot()
    bot.start()


if __name__ == '__main__':
    main()