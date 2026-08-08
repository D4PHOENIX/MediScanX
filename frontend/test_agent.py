import urllib.request
import json
import sys

def run_test_scenario_1():
    url = 'https://mediscanx.app/api/v1/agent/chat'
    headers = {
        'Authorization': 'Bearer dev-token',
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
        'User-Agent': 'MediScanX-TestScript/1.0'
    }
    
    data = {
        'messages': [
            {'role': 'user', 'content': 'Hello, this is a test of the dev-token bypass.'}
        ],
        'patient_id': 'test-123',
        'current_scan_id': 'scan-456',
        'execution_step': 'initial_evaluation',
        'multimodal_metadata': {}
    }
    
    print("Executing Scenario 1: Dev-Token Bypass...")
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers)
    
    try:
        with urllib.request.urlopen(req) as response:
            print('Status:', response.status)
            for line in response:
                decoded = line.decode('utf-8').strip()
                if decoded:
                    print(decoded)
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code} {e.reason}")
        if e.code == 530:
            print("Note: Error 530 indicates Cloudflare Tunnel is down.")
        else:
            print("Response body:", e.read().decode('utf-8', errors='ignore'))
    except Exception as e:
        print('Error:', e)

if __name__ == "__main__":
    run_test_scenario_1()
