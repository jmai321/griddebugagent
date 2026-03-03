import json

with open('curl_output.json') as f:
    data = json.load(f)

print('--- AGENTIC CONVERSATION ---')
conversation = data.get('agentic', {}).get('conversation', [])

for msg in conversation:
    role = msg.get('role', '')
    content = msg.get('content', '') or ''
    
    if role == 'assistant' and 'tool_calls' in msg:
        calls = [tc['function']['name'] for tc in msg['tool_calls']]
        print(f'ASSISTANT CALLED TOOL: {calls}')
    elif role == 'tool':
        name = msg.get('name', '')
        print(f'TOOL {name} RETURNED:\n{content[:500]}...\n')
    else:
        print(f'{role.upper()}:\n{content[:500]}...\n')
