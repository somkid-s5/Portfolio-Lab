'use strict';
const el=id=>document.getElementById(id);
let state={user:null,role:null,csrf:null,version:null};
let products=[];
let pending=null;
let busy=false;
const quantities=new Map();
const money=value=>new Intl.NumberFormat('th-TH',{style:'currency',currency:'THB'}).format(value/100);
function message(text){el('message').textContent=text;}
function cell(row,text){const c=document.createElement('td');c.textContent=String(text);row.append(c);return c;}
function storageKey(){return 'lab005.pending.'+state.user;}
function readPending(){
  pending=null;
  if(!state.user)return;
  const raw=sessionStorage.getItem(storageKey());
  if(raw){
    try{
      const value=JSON.parse(raw);
      if(typeof value.key==='string'&&Array.isArray(value.items))pending=value;
      else throw new Error('bad pending cart');
    }catch(_){throw new Error('ข้อมูลคำขอค้างอ่านไม่ได้ ให้ตรวจรายการเดิมก่อนแก้ sessionStorage');}
  }
}
function savePending(){
  if(pending)sessionStorage.setItem(storageKey(),JSON.stringify(pending));
  else sessionStorage.removeItem(storageKey());
}
async function request(path,{method='GET',body,key}={}){
  const headers={};
  if(body!==undefined)headers['Content-Type']='application/json';
  if(state.csrf)headers['X-CSRF-Token']=state.csrf;
  if(key)headers['Idempotency-Key']=key;
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),20000);
  try{
    const response=await fetch(path,{method,headers,credentials:'same-origin',cache:'no-store',
      body:body===undefined?undefined:JSON.stringify(body),signal:controller.signal,redirect:'error'});
    const data=await response.json();
    if(!response.ok){
      const error=new Error((data.error||'request_failed')+' · request '+(data.request_id||response.headers.get('X-Request-ID')||'unknown'));
      error.status=response.status;error.code=data.error;throw error;
    }
    if(data.version){state.version=data.version;el('version').textContent='API '+data.version+' · backend '+(data.backend||response.headers.get('X-Backend-ID')||'');}
    return data;
  }finally{clearTimeout(timer);}
}
async function action(fn){
  if(busy)return;
  busy=true;el('place').disabled=true;
  try{await fn();}catch(error){message(error.name==='AbortError'||error instanceof TypeError?'เชื่อมต่อไม่ได้หรือหมดเวลา ผลอาจเกิดขึ้นแล้ว ให้ตรวจหรือส่งคำขอเดิมซ้ำ':error.message+(error.code==='csrf_required'||error.code==='login_required'?' · รีเฟรชหน้าและเข้าสู่ระบบอีกครั้งก่อนส่งคำขอเดิม':''));}
  finally{busy=false;el('place').disabled=false;}
}
function identity(){
  el('identity').textContent=state.user?'ผู้ใช้ '+state.user+' · '+state.role:'ยังไม่ได้เข้าสู่ระบบ';
  el('login-form').hidden=Boolean(state.user);el('logout').hidden=!state.user;
  el('workspace').hidden=!state.user;el('operator-section').hidden=state.role!=='operator';
}
function renderProducts(){
  el('products').replaceChildren();
  for(const product of products){
    const row=document.createElement('tr');
    cell(row,product.sku+' · '+product.name+(product.low_stock?' · สต็อกเหลือน้อย':''));
    cell(row,money(product.unit_price_satang));cell(row,product.available);
    const input=document.createElement('input');input.type='number';input.min='0';input.max='20';input.step='1';
    input.setAttribute('aria-label','จำนวน '+product.sku);
    const saved=pending&&pending.items.find(item=>item.sku===product.sku);
    input.value=saved?saved.quantity:(quantities.get(product.sku)||0);
    input.disabled=Boolean(pending);input.addEventListener('change',()=>quantities.set(product.sku,Number(input.value)));
    cell(row,'').append(input);el('products').append(row);
  }
  el('pending').hidden=!pending;el('place').textContent=pending?'ตรวจผล / ส่งคำขอเดิมซ้ำ':'ส่งคำสั่งซื้อ';
}
async function refresh(){
  products=(await request('/api/products')).products;renderProducts();
  const rows=(await request('/api/orders')).orders;
  el('orders').replaceChildren();
  for(const order of rows){
    const row=document.createElement('tr');cell(row,order.id);cell(row,money(order.total_satang));cell(row,order.status);
    const controls=cell(row,'');const details=document.createElement('button');details.type='button';details.textContent='รายละเอียด';
    details.addEventListener('click',()=>action(async()=>{el('details').textContent=JSON.stringify((await request('/api/orders/'+order.id)).order,null,2);}));
    controls.append(details);
    if(order.status==='confirmed'){
      const cancel=document.createElement('button');cancel.type='button';cancel.textContent='ยกเลิก';
      cancel.addEventListener('click',()=>action(async()=>{
        await request('/api/orders/'+order.id+'/cancel',{method:'POST',body:{}});await refresh();message('ยกเลิกแล้ว คืนสต็อกเพียงครั้งเดียว');
      }));controls.append(' ',cancel);
    }
    el('orders').append(row);
  }
  if(state.role==='operator')el('operator-orders').textContent=JSON.stringify((await request('/api/operator/orders')).orders,null,2);
}
el('login-form').addEventListener('submit',event=>{event.preventDefault();action(async()=>{
  let result;
  try{result=await request('/api/login',{method:'POST',body:{username:el('username').value,password:el('password').value}});}
  finally{el('password').value='';}
  state={...state,user:result.username,role:result.role,csrf:result.csrf};readPending();identity();await refresh();message('เข้าสู่ระบบแล้ว');
});});
el('logout').addEventListener('click',()=>action(async()=>{
  await request('/api/logout',{method:'POST',body:{}});
  state={user:null,role:null,csrf:null};pending=null;quantities.clear();identity();el('details').textContent='';el('operator-orders').textContent='';
  state.csrf=(await request('/api/session')).csrf;message('ออกจากระบบแล้ว คำขอที่ยังไม่ทราบผลเก็บเฉพาะ key/ตะกร้าไว้ในแท็บนี้');
}));
el('refresh').addEventListener('click',()=>action(async()=>{await refresh();message('ข้อมูลล่าสุดแล้ว');}));
el('place').addEventListener('click',()=>action(async()=>{
  if(!pending){
    const items=[...quantities].filter(([,quantity])=>quantity>0).map(([sku,quantity])=>({sku,quantity}));
    if(!items.length||items.some(item=>!Number.isInteger(item.quantity)||item.quantity>20))throw new Error('เลือกจำนวนสินค้าเป็นจำนวนเต็ม 1–20 ก่อนส่ง');
    const bytes=crypto.getRandomValues(new Uint8Array(16));const key='web-'+[...bytes].map(n=>n.toString(16).padStart(2,'0')).join('');
    pending={key,items};savePending();renderProducts();
  }
  let result;
  try{result=await request('/api/orders',{method:'POST',body:{items:pending.items},key:pending.key});}
  catch(error){
    if(error.status===400||error.status===404||error.code==='insufficient_stock'){pending=null;savePending();renderProducts();}
    throw error;
  }
  if(!result.order||!result.order.id)throw new Error('คำตอบไม่ครบ ให้ตรวจรายการก่อนส่งคำขอเดิมซ้ำ');
  pending=null;savePending();quantities.clear();await refresh();el('details').textContent=JSON.stringify(result.order,null,2);
  message('ยืนยันคำสั่งซื้อ '+result.order.id+(result.replayed?' · ได้ผลรายการเดิมจาก retry':''));
}));
action(async()=>{
  const result=await request('/api/session');state={...state,user:result.username,role:result.role,csrf:result.csrf};
  readPending();identity();if(state.user)await refresh();
});
