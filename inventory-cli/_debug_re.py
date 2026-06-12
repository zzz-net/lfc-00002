import re
import sys
sys.stdout.reconfigure(encoding='utf-8')

content = open('README.md', encoding='utf-8').read()

# Check for backtick commands
all_backtick = re.findall(r"`[^`]+`", content)
print(f"Total backtick items: {len(all_backtick)}")
prune_backtick = [x for x in all_backtick if 'prune' in x]
print(f"Backtick items with 'prune': {len(prune_backtick)}")
for item in prune_backtick:
    print(f"  {repr(item[:80])}")

print()
# Check for "inventory prune" occurrences
count = content.count('inventory prune')
print(f"'inventory prune' occurrences: {count}")

# Check for "python -m inventory_cli.cli prune"
count2 = content.count('inventory_cli.cli prune')
print(f"'inventory_cli.cli prune' occurrences: {count2}")

print()
# Try the regex
pattern = r"`inventory prune ([^`]+)`"
matches = re.findall(pattern, content)
print(f"Regex matches for `inventory prune ...`: {len(matches)}")
for m in matches:
    print(f"  {repr(m)}")
