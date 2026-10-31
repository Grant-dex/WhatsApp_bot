from pathlib import Path
import shutil
import json
from playwright.sync_api import sync_playwright
root=Path(__file__).resolve().parents[2];checks=[];errors=[]
with sync_playwright() as p:
 b=p.chromium.launch(executable_path=shutil.which('chromium'),args=['--no-sandbox'])
 page=b.new_page(viewport={'width':1440,'height':900})
 page.on('pageerror',lambda e:errors.append(str(e)))
 sends=[]
 def block_send(route):
  sends.append(route.request.url);route.fulfill(status=200,json={'ok':False,'status':'unknown','error':'UI test stub: result unknown'})
 page.route('**/admin/api/send-manual',block_send)
 page.route('**/admin/api/followups/*/send-now',block_send)
 page.goto('http://127.0.0.1:8080');page.wait_for_selector('#page-dashboard .stats')
 # Sidebar uses actual API detail, including recent send issue link.
 page.locator('.dashboard-issues .customer-link').first.click();page.wait_for_selector('#edit-name');checks.append('dashboard issue opens full customer detail');page.evaluate('closeSidebar()')
 page.locator('nav [data-page="customers"]').click();page.wait_for_selector('#cust-table-body tr')
 page.locator('#cust-search-input').fill('不存在的UI客户');page.wait_for_timeout(500);page.wait_for_selector('#cust-table-body .empty-state');assert page.locator('#cust-table-body .person').count()==0;checks.append('customer search empty state')
 page.locator('#cust-search-input').fill('');page.wait_for_timeout(500)
 page.evaluate('viewCustomer(1)');page.wait_for_selector('#edit-name')
 old=page.locator('#edit-company').input_value();page.locator('#edit-company').fill('UI updated company');page.evaluate('saveCustomerEdits(1)');page.wait_for_timeout(300)
 assert page.request.get('http://127.0.0.1:8080/admin/api/customers/1').json()['customer']['company']=='UI updated company';checks.append('real customer edit persisted')
 page.request.post('http://127.0.0.1:8080/admin/api/customers/1/status',data={'company':old})
 # Customer CSV import is local; no messaging operation is invoked.
 page.locator('nav [data-page="customers"]').click();page.wait_for_selector('#cust-search-input')
 with page.expect_file_chooser() as chooser:
  page.get_by_role('button',name='导入 Excel').click()
 chooser.value.set_files({'name':'ui-import.csv','mimeType':'text/csv','buffer':'姓名,电话,公司\nUI导入测试,+447700900099,UI Only\n'.encode()})
 page.wait_for_selector('#ui-dialog-overlay.show');assert '成功 1 条' in page.locator('#ui-dialog-message').inner_text();page.locator('#ui-dialog-ok').click()
 imported=page.request.get('http://127.0.0.1:8080/admin/api/customers?search=UI导入测试').json()['items'];assert len(imported)==1
 page.request.delete('http://127.0.0.1:8080/admin/api/customers/'+str(imported[0]['id']));checks.append('real CSV import through browser file chooser and cleanup')
 # Real product doc create/edit/delete with side drawer and API, no external action.
 page.locator('nav [data-page="product-docs"]').click();page.wait_for_selector('#page-product-docs table');page.evaluate('editProductDoc(0)');page.wait_for_selector('#doc-title')
 page.locator('#doc-title').fill('UI CRUD verification');page.locator('#doc-content').fill('<img src=x onerror=alert(1)> must remain plain text');page.evaluate('saveProductDoc(0)');page.wait_for_timeout(300)
 docs=page.request.get('http://127.0.0.1:8080/admin/api/product-docs').json()['items'];doc=next(x for x in docs if x['title']=='UI CRUD verification');did=doc['id']
 page.evaluate(f'editProductDoc({did})');page.wait_for_selector('#doc-title');assert page.locator('#doc-content').input_value().startswith('<img');page.locator('#doc-title').fill('UI CRUD edited');page.evaluate(f'saveProductDoc({did})');page.wait_for_timeout(300)
 page.evaluate(f'void deleteProductDoc({did})');page.wait_for_selector('#ui-dialog-overlay.show');page.locator('#ui-dialog-ok').click();page.wait_for_timeout(300);assert not any(x['id']==did for x in page.request.get('http://127.0.0.1:8080/admin/api/product-docs').json()['items']);checks.append('real document create/edit/delete and hostile text')
 # Real order create and edit from full form, then delete using confirmation.
 page.locator('nav [data-page="orders"]').click();page.wait_for_selector('#page-orders table');page.evaluate('openOrderForm(0)');page.wait_for_selector('#ord-product')
 page.locator('#ord-customer').select_option('1');page.locator('#ord-product').fill('UI CRUD order');page.locator('#ord-price').fill('0');page.locator('#ord-qty').fill('2');page.locator('#ord-total').fill('0');page.evaluate('saveOrder(0)');page.wait_for_timeout(300)
 orders=page.request.get('http://127.0.0.1:8080/admin/api/orders?per_page=100').json()['items'];order=next(x for x in orders if x['product']=='UI CRUD order');oid=order['id'];assert order['total_amount']==0
 page.evaluate(f'openOrderForm({oid})');page.wait_for_selector('#ord-product');page.locator('#ord-notes').fill('edited');page.evaluate(f'saveOrder({oid})');page.wait_for_timeout(300);assert page.request.get(f'http://127.0.0.1:8080/admin/api/orders/{oid}').json()['order']['notes']=='edited'
 page.evaluate(f'void deleteOrder({oid})');page.wait_for_selector('#ui-dialog-overlay.show');page.locator('#ui-dialog-ok').click();page.wait_for_timeout(300);checks.append('real order CRUD and zero amount preserved')
 # Pause switch state truly persisted, then restored.
 before=page.request.get('http://127.0.0.1:8080/admin/api/bot-state').json()['paused'];page.locator('.pause-toggle').click();page.wait_for_timeout(300);assert page.request.get('http://127.0.0.1:8080/admin/api/bot-state').json()['paused'] != before;page.locator('.pause-toggle').click();page.wait_for_timeout(300);checks.append('real pause switch read/update/restore')
 # A failed pause update must restore the confirmed state and show failure.
 page.route('**/admin/api/bot-state/toggle',lambda r:r.fulfill(status=500,json={'detail':'UI injected pause failure'}))
 previous=page.locator('#pause-label').inner_text();page.locator('.pause-toggle').click();page.wait_for_selector('#ui-dialog-overlay.show');assert '保存失败' in page.locator('#ui-dialog-message').inner_text();assert page.locator('#pause-label').inner_text()==previous;page.locator('#ui-dialog-ok').click();page.unroute('**/admin/api/bot-state/toggle');checks.append('failed pause update does not claim success')
 # Dashboard failure cannot display normal zero counts.
 page.route('**/admin/api/dashboard',lambda r:r.fulfill(status=500,json={'detail':'UI injected failure'}));page.locator('nav [data-page="dashboard"]').click();page.wait_for_selector('#page-dashboard h1');page.wait_for_timeout(250);assert '页面加载失败' in page.locator('#page-dashboard').inner_text();assert page.locator('#page-dashboard .stat-val').count()==0;checks.append('HTTP failure replaces counts with error state');page.unroute('**/admin/api/dashboard')
 # Proxy partial failure is visible and prevents accidental blank overwrite.
 page.route('**/admin/api/proxy',lambda r:r.fulfill(status=500,json={'detail':'UI injected proxy failure'}));page.locator('nav [data-page="bridge"]').click();page.wait_for_selector('#proxy-input');page.wait_for_timeout(250);assert page.locator('#proxy-input').is_disabled();assert '读取失败' in page.locator('.proxy-note').inner_text();checks.append('bridge partial failure visible; save disabled');page.unroute('**/admin/api/proxy')
 # QR is local synthetic data; disappearing QR must never imply authenticated.
 page.route('**/admin/api/bridge',lambda r:r.fulfill(status=200,json={'online':True,'authenticated':False,'phone':None,'recent_events':[]}))
 qr={'status':'pending','qr_text':'UI-TEST-NOT-A-WHATSAPP-LOGIN'}
 page.route('**/admin/api/qr',lambda r:r.fulfill(status=200,json=qr))
 page.evaluate("loadPage('bridge')");page.wait_for_selector('#qr-toggle-btn');page.locator('#qr-toggle-btn').click();page.wait_for_selector('#qr-code img',timeout=7000);assert page.locator('#qr-code img').get_attribute('src').startswith('data:image/')
 qr.clear();qr.update({'status':'none'});page.wait_for_function("document.getElementById('qr-area')?.textContent.includes('已失效或已处理')",timeout=7000)
 assert '已扫码' not in page.locator('#qr-area').inner_text();checks.append('synthetic QR renders; disappearance does not claim authentication')
 page.unroute('**/admin/api/qr');page.unroute('**/admin/api/bridge')
 # Unknown send mocked; no bridge can receive an actual send.
 page.locator('nav [data-page="conversations"]').click();page.wait_for_selector('.chat-item');page.evaluate('selectCustomer(1)');page.wait_for_selector('#manual-msg');page.locator('#manual-msg').fill('UI test message');page.evaluate('sendManual(1)');page.wait_for_function("document.getElementById('toast')?.textContent.includes('待确认')");assert len(sends)==1;assert '待确认' in page.locator('#toast').inner_text();checks.append('manual send stub called once, unknown retained, no retry')
 b.close()
assert not errors,errors
(root/'artifacts/functional-results.json').write_text(json.dumps({'checks':checks,'page_errors':errors,'stub_send_count':len(sends)},ensure_ascii=False,indent=2));print('PASS',len(checks),'functional checks')
