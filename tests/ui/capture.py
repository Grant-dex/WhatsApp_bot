from pathlib import Path
import shutil
from playwright.sync_api import sync_playwright
import json
root=Path(__file__).resolve().parents[2]
out=root/'artifacts/screenshots';out.mkdir(parents=True, exist_ok=True)
results=[];errors=[]
with sync_playwright() as p:
 b=p.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
 for w,h in [(1024,768),(1280,800),(1440,900),(1920,1080)]:
  page=b.new_page(viewport={'width':w,'height':h},device_scale_factor=1)
  page.on('pageerror',lambda e: errors.append(str(e)))
  page.on('response',lambda r: errors.append(f'HTTP {r.status}: {r.url}') if r.status>=400 and '/assets/' in r.url else None)
  page.goto('http://127.0.0.1:8080');page.wait_for_selector('#page-dashboard .stats')
  for n in ['dashboard','customers','conversations','followups','orders','product-docs','bridge','activity']:
   page.locator(f'nav a[data-page="{n}"]').click()
   page.wait_for_selector(f'#page-{n}.active h1')
   page.wait_for_timeout(350)
   assert page.locator(f'#page-{n}').inner_text().find('页面加载失败')<0,(n,'failed load')
   if n=='conversations':
    item=page.locator('.chat-item').first
    if item.count():item.click();page.wait_for_timeout(300)
   overflow=page.evaluate('document.documentElement.scrollWidth > innerWidth')
   assert not overflow,(n,w,'document overflow')
   page.screenshot(path=str(out/f'{n}-{w}x{h}.png'))
   results.append({'page':n,'viewport':f'{w}x{h}','document_overflow':overflow})
  page.close()
 b.close()
assert not errors,errors
(root/'artifacts/viewport-results.json').write_text(json.dumps({'checks':results,'page_errors':errors,'data':'isolated SQLite UI fixture; Bridge disabled; scheduler disabled'},ensure_ascii=False,indent=2))
print('PASS',len(results),'page/viewport captures; no page errors or missing assets')
