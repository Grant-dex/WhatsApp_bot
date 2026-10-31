import sqlite3
from datetime import datetime,timedelta
from pathlib import Path
root=Path(__file__).resolve().parents[2] / 'data-ui-test'
assert root.name=='data-ui-test'
c=sqlite3.connect(root/'data/customers.db')
assert c.execute('SELECT COUNT(*) FROM customers').fetchone()[0]==0,'fixture requires empty isolated database'
names=['林晓（测试）','Sofia Silva','Omar Ali','Emma Wilson','Daniel Lee','Maya Stone','Ryan Carter']
now=datetime.now()
for i,n in enumerate(names):
 cid=i+1
 c.execute('INSERT INTO customers(phone,name,company,email,notes,status) VALUES(?,?,?,?,?,?)',(f'44770090000{i}',n,['Atlas Energy','Nova Power','Horizon Tech'][i%3],f'ui{i}@example.invalid','隔离视觉测试资料，不是真实客户','inactive' if i==4 else 'active'))
 for j,(direction,content,status) in enumerate([('inbound','Hello, could you send the specifications for the gas generator?','received'),('outbound','Of course. What power output and voltage do you need?','sent'),('inbound','We need 800 kW, 400 V, 50 Hz.','received'),('outbound','Thank you. Please share the site temperature and altitude.','unknown' if i==5 else 'sent')]):
  c.execute('INSERT INTO conversations(customer_id,direction,content,status,send_kind,ai_generated,sent_at) VALUES(?,?,?,?,?,?,?)',(cid,direction,content,status,'inbound' if direction=='inbound' else 'manual',0,(now-timedelta(minutes=20-j*4+i*15)).isoformat()))
 c.execute('INSERT INTO follow_up_schedule(customer_id,frequency_days,next_followup_at,active) VALUES(?,?,?,?)',(cid,7,(now+timedelta(days=i-3)).isoformat(),0 if i==4 else 1))
 c.execute('INSERT INTO orders(order_no,customer_id,product,quantity,unit_price,total_amount,status,order_date,delivery_date,currency,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(f'UI-{cid:03}',cid,['燃气发电机组','备件包','柴油发电机组'][i%3],1,48000,48000,['pending','confirmed','processing','shipped','delivered','cancelled','pending'][i],now.date().isoformat(),(now+timedelta(days=14)).date().isoformat(),'USD','隔离测试订单'))
for i,(title,text) in enumerate([('燃气机组产品介绍','产品型号与应用场景；仅用于 UI 验证。'),('项目询盘信息表','功率、电压、气源与环境条件。'),('安装准备说明','安装前资料准备清单。'),('售后服务说明','维护与备件咨询流程。'),('常见问题','客户常见问题与回复参考。'),('产品铭牌示例','参数阅读示例。')]):c.execute('INSERT INTO product_docs(title,content) VALUES(?,?)',(title,text))
for cid,status,error in [(5,'failed','模拟连接超时'),(6,'unknown','等待平台发送结果确认'),(1,'sent',None),(2,'sent',None)]:c.execute('INSERT INTO sent_followups(customer_id,schedule_id,status,error_message,sent_at) VALUES(?,?,?,?,?)',(cid,cid,status,error,now.isoformat()))
c.commit();c.close()
print('isolated UI fixture created',root)
