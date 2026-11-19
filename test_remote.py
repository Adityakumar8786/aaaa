# save as test_remote.py and run
import requests
url = "https://priorities-william-scanner-river.trycloudflare.com"
r = requests.get(f"{url}/api/tags", timeout=30)
print(r.status_code)
print(r.json())