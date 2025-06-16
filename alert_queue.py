"""
Alert Queue Service
------------------
This service receives alerts for network faults and queues them up for processing by downstream event-driven automation services.

- Endpoint: POST /alert
- Receives: Any valid JSON content
- Appends alert content to a queue file for later processing.
"""
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os
import argparse
import uvicorn
import json

app = FastAPI()

ALERT_QUEUE_FILE = os.path.join(os.path.dirname(__file__), 'workbench', 'alert_queue.txt')

@app.post("/alert")
async def receive_alert(request: Request):
    """
    Receives an alert and appends it to the alert queue file for processing.
    Accepts any valid JSON structure and stores it in JSON Lines format.
    """
    try:
        # Parse the raw JSON directly from the request
        alert_json = await request.json()
        
        # Create directory if it doesn't exist
        os.makedirs(os.path.dirname(ALERT_QUEUE_FILE), exist_ok=True)
        
        # Write the raw JSON to the file
        with open(ALERT_QUEUE_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(alert_json, ensure_ascii=False) + '\n')
            
        return JSONResponse(content={"status": "success"})
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": f"Invalid JSON: {str(e)}"}
        )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Alert Queue service.")
    parser.add_argument("--port", type=int, default=8001, help="Port to run the Alert Queue service on (default: 8001)")
    args = parser.parse_args()
    uvicorn.run("alert_queue:app", host="0.0.0.0", port=args.port)
