import os
import json
import time
import hashlib
import requests
from private import PASSWORD, EMAIL

# --- CONFIGURATION SETTINGS ---
BASE_URL = "https://api-us.libreview.io"  # Update to your regional URL

TOKEN_FILE = "libre_token.json"

HEADERS = {
    "Content-Type": "application/json",
    "Accept-Encoding": "gzip",
    "product": "llu.android",
    "version": "4.17.0"
}

def login_with_backoff():
    """Logs into LibreLinkUp and handles rate limits."""
    url = f"{BASE_URL}/llu/auth/login"
    payload = {"email": EMAIL, "password": PASSWORD}
    wait_time = 30 
    
    for attempt in range(3):
        response = requests.post(url, json=payload, headers=HEADERS)
        
        if response.status_code == 429:
            print(f"Rate limited (429)! Waiting {wait_time} seconds...")
            time.sleep(wait_time)
            wait_time *= 2
            continue
            
        if response.status_code != 200:
            print(f"Login failed! Status: {response.status_code}")
            return None
            
        data = response.json()
        token = data["data"]["authTicket"]["token"]
        user_id = data["data"]["user"]["id"]
        
        # Save locally for 12 hours
        token_data = {
            "token": token,
            "user_id": user_id,
            "expires_at": time.time() + (12 * 3600)
        }
        with open(TOKEN_FILE, "w") as f:
            json.dump(token_data, f)
        return token, user_id
        
    return None

def get_valid_credentials():
    """Returns cached credentials or requests fresh ones."""
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r") as f:
                cached = json.load(f)
                if time.time() < cached["expires_at"]:
                    return cached["token"], cached["user_id"]
        except Exception:
            pass
    return login_with_backoff()

def build_authenticated_headers(token, user_id):
    """Generates standard tracking and security headers."""
    account_id_hash = hashlib.sha256(user_id.encode()).hexdigest()
    auth_headers = HEADERS.copy()
    auth_headers["Authorization"] = f"Bearer {token}"
    auth_headers["Account-Id"] = account_id_hash
    return auth_headers

def get_patient_id(auth_headers):
    """Finds the first available patient ID linked to this caregiver."""
    url = f"{BASE_URL}/llu/connections"
    response = requests.get(url, headers=auth_headers)
    
    if response.status_code == 401:
        if os.path.exists(TOKEN_FILE):
            os.remove(TOKEN_FILE)
        raise PermissionError("Token expired or unauthorized.")
        
    data = response.json()
    connections = data.get("data", [])
    
    if not connections:
        raise ValueError("No patients linked to this caregiver account.")
        
    first_patient = connections[0]
    patient_id = first_patient["patientId"]
    name = f"{first_patient.get('firstName')} {first_patient.get('lastName')}"
    return patient_id, name

def map_trend_arrow(arrow_integer):
    """Maps the API trend number to a clear human description."""
    trend_map = {
        1: "Falling Quickly ⬇️",
        2: "Falling 📉",
        3: "Stable ➡️",
        4: "Rising 📈",
        5: "Rising Quickly ⬆️"
    }
    return trend_map.get(arrow_integer, f"Unknown ({arrow_integer})")

def fetch_glucose_data(auth_headers, patient_id):
    """Extracts real-time values and the historical data arrays."""
    url = f"{BASE_URL}/llu/connections/{patient_id}/graph"
    response = requests.get(url, headers=auth_headers)
    
    if response.status_code != 200:
        print(f"Failed to fetch data graph! Status: {response.status_code}")
        return
        
    payload = response.json()
    connection_data = payload.get("data", {}).get("connection", {})
    
    # Extract Real-Time Measurement
    realtime = connection_data.get("glucoseMeasurement")
    if realtime:
        print("\n--- CURRENT METRICS ---")
        print(f"Glucose Value: {realtime.get('Value')} mg/dL")
        print(f"Recorded At:   {realtime.get('Timestamp')}")
        print(f"Trend State:   {map_trend_arrow(realtime.get('TrendArrow'))}")
    else:
        print("\n[Warning] No active real-time measurement packet found.")
        
    # Extract 12-Hour Trend Graph Array
    history = payload.get("data", {}).get("graphData", [])
    print(f"\n--- HISTORICAL DATA ARRAY (Found {len(history)} entries) ---")
    
    # Print the last 5 data points from history as a snapshot
    for point in history[-5:]:
        print(f"[{point.get('Timestamp')}] {point.get('Value')} mg/dL")

if __name__ == "__main__":
    try:
        token, user_id = get_valid_credentials()
        headers = build_authenticated_headers(token, user_id)
        
        patient_uuid, patient_name = get_patient_id(headers)
        print(f"Targeting Patient: {patient_name}")
        
        fetch_glucose_data(headers, patient_uuid)
        
    except Exception as error:
        print(f"Script aborted: {error}")
