import urllib.request
import json
import time

url = 'http://127.0.0.1:8000/diagnose_nl'
data = json.dumps({
    'network': 'case118',
    'description': 'Can you run AC power flow on the IEEE 118-bus grid to find the top 5 most heavily loaded lines, then run contingency analysis on those and summarize any operational limit violations.'
}).encode('utf-8')

req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
try:
    with urllib.request.urlopen(req, timeout=120) as response:
        res = json.loads(response.read().decode())
        print('----- BASELINE RESPONSE -----')
        print('\n'.join(res.get('baseline', {}).get('rootCauses', [])))
        
        print('\n----- AGENTIC RESPONSE -----')
        print('\n'.join(res.get('agentic', {}).get('rootCauses', [])))
except Exception as e:
    print('Error:', e)
