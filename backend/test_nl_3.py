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
        print('--- AGENTIC CONVERSATION ---')
        conversation = res.get('agentic', {}).get('conversation', [])
        
        for msg in conversation:
            role = msg.get('role', '')
            content = msg.get('content', '') or ''
            
            if role == 'assistant' and 'tool_calls' in msg:
                calls = [tc['function']['name'] for tc in msg['tool_calls']]
                print(f'ASSISTANT CALLED TOOL: {calls}')
            elif role == 'tool':
                name = msg.get('name', '')
                print(f'TOOL {name} RETURNED:\n{content[:200]}...\n')
            else:
                print(f'{role.upper()}:\n{content[:300]}...\n')
except Exception as e:
    print('Error:', e)
