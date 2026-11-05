import re

with open('frontend/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

ids_in_html = set(re.findall(r'id=["\']([^"\']+)["\']', html))

for js_path in ['frontend/assets/js/main.js', 'frontend/assets/js/ui.js']:
    with open(js_path, 'r', encoding='utf-8') as f:
        js = f.read()
    ids_in_js = set(re.findall(r'getElementById\(["\']([^"\']+)["\']\)', js))
    missing = ids_in_js - ids_in_html
    print(f"{js_path} missing IDs: {missing}")

