import os
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()

# API credentials for Delta Exchange
API_KEY = os.getenv('DELTA_API_KEY', 'sUABSFPLpe5QNVJuKsOL6O0r5TiUoP')
API_SECRET = os.getenv('DELTA_API_SECRET', 'Q6Fo1NcOtNIxJZ9IPRUxROcSZ4vQdI31hDVPaoOvJnYfPt5wQLaNb6WMnNOy')

# Delta Exchange API endpoints
DELTA_API_URLS = {
    'public': os.getenv('DELTA_PUBLIC_URL', 'https://api.india.delta.exchange'),
    'private': os.getenv('DELTA_PRIVATE_URL', 'https://api.india.delta.exchange'),
}
FIXED_OFFSET = int(os.getenv('FIXED_OFFSET', 100))

# Trading parameters
DEFAULT_ORDER_TYPE = 'limit'
TRAILING_STOP_PERCENT = 2.0  # 2% trailing stop
BASKET_ORDER_ENABLED = True

# Logging configuration
LOG_FILE = os.getenv('LOG_FILE', 'trading.log')
LOG_LEVEL = os.getenv('LOG_LEVEL', 'DEBUG')


# Market data caching TTL (in seconds)
MARKET_CACHE_TTL = int(os.getenv('MARKET_CACHE_TTL', '300'))

# Database configuration (if needed)
DATABASE_URI = os.getenv('DATABASE_URI', 'sqlite:///trading.db')

# Profit trailing configuration
PROFIT_TRAILING_CONFIG = {
    "start_trailing_profit_pct": 0.005,
    "levels": [
         {"min_profit_pct": 0.005, "trailing_stop_offset": 0.001, "book_fraction": 1.0},
         {"min_profit_pct": 0.01,  "trailing_stop_offset": 0.006, "book_fraction": 1.0},
         {"min_profit_pct": 0.015, "trailing_stop_offset": 0.012, "book_fraction": 1.0},
         {"min_profit_pct": 0.02,  "trailing_stop_offset": None, "book_fraction": 0.9}
    ],
    "fixed_stop_loss_pct": 0.005,
    "trailing_unit": "percent"
}

# Account mapping for Firebase signal routing
# Account mapping for Firebase signal routing
ACCOUNTS = {
    "MAIN": {
        "REDIS_KEY": "signal_MAIN"
    }
}
