import re

with open('frontend/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

classes_in_html = set(re.findall(r'class=["\']([^"\']+)["\']', html))
all_classes = set()
for c in classes_in_html:
    for item in c.split():
        all_classes.add(item)

ids_in_html = set(re.findall(r'id=["\']([^"\']+)["\']', html))

for js_path in ['frontend/assets/js/main.js', 'frontend/assets/js/ui.js']:
    with open(js_path, 'r', encoding='utf-8') as f:
        js = f.read()
    
    # check querySelector / querySelectorAll
    qs = re.findall(r'querySelector(?:All)?\(["\']([^"\']+)["\']\)', js)
    for q in qs:
        # if ID
        if q.startswith('#'):
            clean_id = q[1:].split()[0].split(':')[0].split('.')[0]
            if clean_id not in ids_in_html:
                print(f"{js_path} MISSING ID in selector: {q}")
        # if class
        elif q.startswith('.'):
            clean_class = q[1:].split()[0].split(':')[0]
            if clean_class not in all_classes:
                print(f"{js_path} MISSING CLASS in selector: {q}")

