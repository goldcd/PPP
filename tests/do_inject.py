import builtins
original_repr = builtins.repr

ns = {}
builtins.repr = lambda x: x
try:
    with open(r'app\prompts.py', 'r', encoding='utf-8') as f:
        exec(f.read(), ns)
finally:
    builtins.repr = original_repr

master   = ns['PROMPT_V18_DIARIZED_MASTER']
boundary = ns['PROMPT_BOUNDARY_VERIFICATION']

header = (
    '\n'
    '# ===========================================================================\n'
    '# FIXED PROMPTS (FIX-1: repr removed; FIX-2: format; FIX-6: boundary ex2)\n'
    '# ===========================================================================\n'
    '\n'
)

dq3 = chr(34) * 3

inject_block = (
    header
    + 'PROMPT_V18_DIARIZED_MASTER = ' + dq3 + master + dq3 + '\n'
    + '\n'
    + 'PROMPT_BOUNDARY_VERIFICATION = ' + dq3 + boundary + dq3 + '\n'
    + '\n'
)

TARGET = r'tests\test_detect.py'
with open(TARGET, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print('Line 92:', repr(lines[91][:60]))

new_lines = lines[:91] + [inject_block] + lines[91:]

with open(TARGET, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

with open(TARGET, 'r', encoding='utf-8') as f:
    content = f.read()
print('Has PROMPT_V18_DIARIZED_MASTER:', 'PROMPT_V18_DIARIZED_MASTER' in content)
print('Has PROMPT_BOUNDARY_VERIFICATION:', 'PROMPT_BOUNDARY_VERIFICATION' in content)
print('Total lines:', len(content.splitlines()))
