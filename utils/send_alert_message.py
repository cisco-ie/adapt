import requests
import sys

API_URL = "http://localhost:8001/alert"

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python send_alert_message.py 'Your message here'")
        sys.exit(1)
    message = sys.argv[1]
    response = requests.post(API_URL, json={"content": message})
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text}")