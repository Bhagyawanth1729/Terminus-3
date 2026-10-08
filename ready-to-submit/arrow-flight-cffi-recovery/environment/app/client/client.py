import urllib.request
import urllib.error
import json
import time

SERVER_URL = "http://127.0.0.1:50051"

class FlightClient:
    def __init__(self, base_url=SERVER_URL):
        self.base_url = base_url

    def query(self, query_id, batches=10, timeout=10):
        url = f"{self.base_url}/query?id={query_id}&batches={batches}"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
                return data
        except urllib.error.HTTPError as e:
            data = json.loads(e.read().decode())
            return data
        except Exception as e:
            return {"status": "ERROR", "error": str(e)}

    def cancel(self):
        url = f"{self.base_url}/cancel"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            return {"status": "ERROR", "error": str(e)}

    def metrics(self):
        url = f"{self.base_url}/metrics"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            return {"status": "ERROR", "error": str(e)}
