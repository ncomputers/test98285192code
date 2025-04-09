import os
import pyrebase
import config
import json

# Set the base directory (same as where main.py is located)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Firebase configuration
firebase_config = {
    "apiKey": "Fsk89TL7HfPpxcSYecoMro9lJ6ukjKAdWXJOsxUv",
    "authDomain": "alg1-457f6.firebaseapp.com",
    "databaseURL": "https://alg1-457f6-default-rtdb.firebaseio.com/",
    "storageBucket": "alg1-457f6.appspot.com",
    "serviceAccount": os.path.join(BASE_DIR, "alg1-457f6-firebase-adminsdk-fbsvc-3cd134d21c.json")
}

# Initialize Firebase
firebase = pyrebase.initialize_app(firebase_config)
db = firebase.database()

def get_signal(account_key="MAIN"):
    """
    Fetch signal using the Redis-like key structure.
    Example: signal_MAIN, signal_V1, etc.
    """
    redis_key = config.ACCOUNTS[account_key]["REDIS_KEY"]
    try:
        value = db.child(redis_key).get().val()
        print(f"[get_signal] Key: {redis_key}")
        print("Data:", json.dumps(value, indent=2))
        return value
    except Exception as e:
        print(f"Failed to get signal for {account_key}: {e}")
        return None

def store_order(account_key, order_id, order_data):
    """
    Store order under: orders/{account_key}/{order_id}
    """
    try:
        db.child("orders").child(account_key).child(str(order_id)).set(order_data)
        print(f"Order stored for {account_key} - ID: {order_id}")
    except Exception as e:
        print(f"Failed to store order for {account_key}: {e}")

def stream_signal(account_key="MAIN", callback=None):
    """
    Start realtime stream on the top-level signal key (e.g., signal_MAIN).
    """
    redis_key = config.ACCOUNTS[account_key]["REDIS_KEY"]
    try:
        print(f"[stream_signal] Listening on /{redis_key}")
        return db.child(redis_key).stream(callback)
    except Exception as e:
        print(f"Failed to start Firebase stream for {redis_key}: {e}")
        return None

# Debug CLI usage
if __name__ == "__main__":
    def handle_update(message):
        print("Realtime update from Firebase")
        print("Event:", message["event"])
        print("Data:", json.dumps(message["data"], indent=2))
        print("Path:", message["path"])

    print("Fetching current signal for MAIN")
    get_signal("MAIN")

    print("Starting test stream...")
    stream = stream_signal("MAIN", handle_update)

    try:
        while True:
            pass
    except KeyboardInterrupt:
        stream.close()
        print("Stream closed.")