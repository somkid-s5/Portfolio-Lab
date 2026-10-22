"""Transactional order domain. HTTP identity must be validated before calling it."""
import hashlib
import json
import re
import uuid
from sqlalchemy import text

class Problem(Exception):
    def __init__(self,status,error):
        super().__init__(error)
        self.status,self.error=status,error

def cart(items):
    if not isinstance(items,list) or not 1<=len(items)<=10:
        raise Problem(400,'invalid_items')
    normalized=[]
    seen=set()
    for row in items:
        if not isinstance(row,dict) or set(row)!={'sku','quantity'}:
            raise Problem(400,'invalid_item')
        sku,quantity=row['sku'],row['quantity']
        if not isinstance(sku,str) or not re.fullmatch(r'[A-Z0-9][A-Z0-9-]{2,19}',sku):
            raise Problem(400,'invalid_sku')
        if type(quantity) is not int or not 1<=quantity<=20 or sku in seen:
            raise Problem(400,'invalid_quantity_or_duplicate_sku')
        seen.add(sku)
        normalized.append({'sku':sku,'quantity':quantity})
    return sorted(normalized,key=lambda row:row['sku'])

class Orders:
    def __init__(self,engine):
        self.engine=engine

    def products(self):
        with self.engine.connect() as conn:
            return [dict(r) for r in conn.execute(text('SELECT sku,name,unit_price_satang,available FROM products ORDER BY sku')).mappings()]

    def _read(self,conn,order_id):
        row=conn.execute(text('SELECT id::text,username,status,total_satang,created_at::text,cancelled_at::text FROM orders WHERE id=CAST(:id AS uuid)'),{'id':order_id}).mappings().one()
        result=dict(row)
        result['items']=[dict(r) for r in conn.execute(text('SELECT sku,quantity,price_snapshot_satang FROM order_items WHERE order_id=CAST(:id AS uuid) ORDER BY sku'),{'id':order_id}).mappings()]
        return result

    def get(self,username,order_id):
        try:
            order_id=str(uuid.UUID(str(order_id)))
        except (ValueError,TypeError,AttributeError):
            raise Problem(404,'order_not_found')
        with self.engine.connect() as conn:
            if not conn.execute(text('SELECT 1 FROM orders WHERE id=CAST(:id AS uuid) AND username=:u'),{'id':order_id,'u':username}).first():
                raise Problem(404,'order_not_found')
            return self._read(conn,order_id)

    def list(self,username):
        with self.engine.connect() as conn:
            return [dict(r) for r in conn.execute(text('SELECT id::text,status,total_satang,created_at::text FROM orders WHERE username=:u ORDER BY created_at DESC,id LIMIT 100'),{'u':username}).mappings()]

    def place(self,username,key,items):
        if not isinstance(username,str) or not username or len(username)>64:
            raise Problem(400,'invalid_owner')
        if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,80}',key):
            raise Problem(400,'invalid_idempotency_key')
        normalized=cart(items)
        fingerprint=hashlib.sha256(json.dumps(normalized,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        with self.engine.begin() as conn:
            conn.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:lock_key,0))'),{'lock_key':username+':'+key})
            old=conn.execute(text('SELECT id::text,request_fingerprint FROM orders WHERE username=:u AND request_key=:k'),{'u':username,'k':key}).mappings().first()
            if old:
                if old['request_fingerprint']!=fingerprint:
                    raise Problem(409,'idempotency_conflict')
                return self._read(conn,old['id']),True
            rows=[]
            for item in normalized:
                product=conn.execute(text('SELECT sku,unit_price_satang,available FROM products WHERE sku=:sku FOR UPDATE'),{'sku':item['sku']}).mappings().first()
                if not product:
                    raise Problem(404,'product_not_found')
                if product['available']<item['quantity']:
                    raise Problem(409,'insufficient_stock')
                rows.append((item,product))
            order_id=str(uuid.uuid4())
            total=sum(item['quantity']*product['unit_price_satang'] for item,product in rows)
            conn.execute(text("INSERT INTO orders(id,username,request_key,request_fingerprint,status,total_satang) VALUES(CAST(:id AS uuid),:u,:k,:f,'confirmed',:total)"),
                         {'id':order_id,'u':username,'k':key,'f':fingerprint,'total':total})
            for item,product in rows:
                params={'id':order_id,'sku':item['sku'],'quantity':item['quantity'],'price':product['unit_price_satang']}
                conn.execute(text('INSERT INTO order_items(order_id,sku,quantity,price_snapshot_satang) VALUES(CAST(:id AS uuid),:sku,:quantity,:price)'),params)
                conn.execute(text('UPDATE products SET available=available-:quantity WHERE sku=:sku'),params)
                conn.execute(text("INSERT INTO stock_events(order_id,sku,event,delta) VALUES(CAST(:id AS uuid),:sku,'reserved',-:quantity)"),params)
            return self._read(conn,order_id),False

    def cancel(self,username,order_id):
        try:
            order_id=str(uuid.UUID(str(order_id)))
        except (ValueError,TypeError,AttributeError):
            raise Problem(404,'order_not_found')
        with self.engine.begin() as conn:
            row=conn.execute(text('SELECT status FROM orders WHERE id=CAST(:id AS uuid) AND username=:u FOR UPDATE'),{'id':order_id,'u':username}).first()
            if not row:
                raise Problem(404,'order_not_found')
            if row[0]=='cancelled':
                return self._read(conn,order_id),True
            items=conn.execute(text('SELECT sku,quantity FROM order_items WHERE order_id=CAST(:id AS uuid) ORDER BY sku'),{'id':order_id}).mappings().all()
            for item in items:
                conn.execute(text('SELECT sku FROM products WHERE sku=:sku FOR UPDATE'),{'sku':item['sku']})
            for item in items:
                params={'id':order_id,'sku':item['sku'],'quantity':item['quantity']}
                conn.execute(text('UPDATE products SET available=available+:quantity WHERE sku=:sku'),params)
                conn.execute(text("INSERT INTO stock_events(order_id,sku,event,delta) VALUES(CAST(:id AS uuid),:sku,'cancelled',:quantity)"),params)
            conn.execute(text("UPDATE orders SET status='cancelled',cancelled_at=now() WHERE id=CAST(:id AS uuid)"),{'id':order_id})
            return self._read(conn,order_id),False
