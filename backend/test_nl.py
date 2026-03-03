import requests

url = "http://127.0.0.1:8000/api/diagnose_nl"
payload = {
    "network": "case118",
    "description": "Can you run AC power flow on the IEEE 118-bus grid to find the top 5 most heavily loaded lines, then run contingency analysis on those and summarize any operational limit violations."
}

try:
    response = requests.post(url, json=payload, timeout=120)
    data = response.json()
    
    print("----- BASELINE RESPONSE -----")
    print("\n".join(data["baseline"]["rootCauses"]))
    
    print("\n----- AGENTIC RESPONSE -----")
    print("\n".join(data["agentic"]["rootCauses"]))
    
except Exception as e:
    print("Error:", e)
