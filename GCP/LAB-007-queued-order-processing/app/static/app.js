(() => {
"use strict";
const $ = id => document.getElementById(id), hex = s => typeof s === "string" && /^[a-f0-9]{32}$/.test(s);
let user=null, role=null, csrf="", pending=null, broken=false, selected=null, generation=0, busy=false;
const cursors={orders:null,operatorOrders:null,outbox:null};
const note = text => { $("message").textContent=text; };
const money = amount => (amount/100).toFixed(2)+" บาท";
const key = () => "lab007.pending."+user;
function cell(text) { const td=document.createElement("td"); td.textContent=text; return td; }
async function api(path, body) {
  const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),10000);
  try {
    const response=await fetch(path,{method:body===undefined?"GET":"POST",credentials:"same-origin",
      redirect:"error",signal:controller.signal,headers:body===undefined?{}:
      {"Content-Type":"application/json","X-CSRF-Token":csrf},
      body:body===undefined?undefined:JSON.stringify(body)});
    const reader=response.body.getReader(), parts=[]; let length=0;
    for (;;) { const {done,value}=await reader.read(); if(done)break;
      length+=value.length; if(length>65536){await reader.cancel();throw Error("response_limit");} parts.push(value); }
    const bytes=new Uint8Array(length); let offset=0;
    for(const part of parts){bytes.set(part,offset);offset+=part.length;}
    const data=JSON.parse(new TextDecoder("utf-8",{fatal:true}).decode(bytes));
    if(!response.ok){const error=Error("request_failed");error.status=response.status;error.code=data.error;throw error;}
    return data;
  } finally {clearTimeout(timer);}
}
async function run(work) {
  if(busy)return; busy=true;
  document.querySelectorAll("[data-mutation]").forEach(b=>{b.disabled=true;});
  try{await work();}catch(error){
    note(error.status?"คำขอไม่สำเร็จ ("+error.status+") ตรวจ session และงานเดิมก่อนลองใหม่":
      "ยังยืนยันผลไม่ได้ โปรดตรวจงานหรือส่งคำขอเดิมอีกครั้ง โดยไม่เปลี่ยนหมายเลข");
    if(error.status===401||error.code==="csrf_required"){
      try{await session();}catch(_){note("ตรวจ session ไม่สำเร็จ โปรดโหลดหน้าใหม่");}
    }
  }finally{busy=false;document.querySelectorAll("[data-mutation]").forEach(b=>{b.disabled=false;});}
}
function valid(p){
  return p&&hex(p.key)&&Array.isArray(p.items)&&p.items.length>=1&&p.items.length<=2&&
    p.items.every(i=>i&&typeof i.sku==="string"&&/^[A-Z0-9-]{1,32}$/.test(i.sku)&&
      Number.isInteger(i.quantity)&&i.quantity>=1&&i.quantity<=3)&&
    new Set(p.items.map(i=>i.sku)).size===p.items.length&&(p.order_id===undefined||hex(p.order_id));
}
function pendingNote(){
  $("pending-note").textContent=broken?"บันทึกคำขอเสียหาย หยุดส่งงานและตรวจ order กับผู้ดูแลก่อน":
    pending?(pending.order_id?"กลับมาตรวจงาน "+pending.order_id:"มีคำขอยังยืนยันไม่ได้ ส่งซ้ำด้วยสินค้าและหมายเลขเดิมเท่านั้น"):
    "ไม่มีคำขอค้าง หมายเลขจะถูกบันทึกก่อนส่ง";
}
function save(value){
  if(value)sessionStorage.setItem(key(),JSON.stringify(value));else sessionStorage.removeItem(key());
  pending=value;pendingNote();
}
function cart(){return [...$("catalog-body").querySelectorAll("input")].map(i=>({sku:i.dataset.sku,quantity:Number(i.value)}))
  .filter(i=>i.quantity!==0).sort((a,b)=>a.sku.localeCompare(b.sku));}
async function catalog(){
  const account=user,data=await api("/api/catalog");if(account!==user)return;
  $("catalog-body").replaceChildren();
  for(const p of data.items){
    const tr=document.createElement("tr"),td=document.createElement("td"),input=document.createElement("input");
    input.type="number";input.min="0";input.max="3";input.step="1";input.className="quantity";
    input.dataset.sku=p.sku;input.setAttribute("aria-label","จำนวน "+p.sku);
    input.value=String(pending?.items.find(i=>i.sku===p.sku)?.quantity||0);
    td.append(input);tr.append(cell(p.sku),cell(money(p.unit_price_satang)),cell(p.available),td);
    $("catalog-body").append(tr);
  }
}
async function list(kind,cursor=null){
  const account=user,isOwn=kind==="orders",isBox=kind==="outbox";
  const path=isOwn?"/api/orders":"/api/operator/"+(isBox?"outbox":"orders");
  const page=await api(path+"?limit=20"+(cursor?"&cursor="+encodeURIComponent(cursor):""));
  if(account!==user)return;
  cursors[kind]=page.next_cursor;
  const target=$(isOwn?"orders-body":isBox?"operator-outbox-body":"operator-orders-body");
  $(isOwn?"next-orders":isBox?"next-operator-outbox":"next-operator-orders").disabled=!page.next_cursor;
  target.replaceChildren();
  for(const item of page.items){
    const tr=document.createElement("tr");
    if(isBox)tr.append(cell(item.event_id+" / "+item.order_id),cell(item.state),cell(item.epoch+" / "+item.attempts));
    else tr.append(cell(item.order_id+(isOwn?"":" / "+item.owner)),cell(money(item.total_satang)),cell(item.state));
    if(isOwn||isBox){
      const td=document.createElement("td"),button=document.createElement("button");
      button.type="button";button.textContent=isOwn?"ดูรายละเอียด":"ดู metadata";
      button.addEventListener("click",()=>{
        if(isOwn)inspect(item.order_id).catch(()=>note("ตรวจงานไม่สำเร็จ เลือกรายการเดิมเพื่อลองใหม่"));
        else run(async()=>{
          if(!hex(item.event_id))throw Error("invalid_event");
          const result=await api("/api/operator/outbox/"+item.event_id);
          if(account===user&&role==="operator")$("operator-detail").textContent=JSON.stringify(result,null,2);
        });
      });td.append(button);tr.append(td);
    }
    target.append(tr);
  }
}
async function inspect(id){
  if(!hex(id))throw Error("invalid_order");
  selected=id;const token=++generation,account=user,start=Date.now();
  for(let round=0;round<30&&Date.now()-start<90000;round++){
    const data=await api("/api/orders/"+id);
    if(token!==generation||account!==user||selected!==id)return;
    $("order-detail").textContent=JSON.stringify(data,null,2);
    if(["confirmed","rejected"].includes(data.state)){
      if(pending?.order_id===id)save(null);
      note("งานจบด้วยสถานะ "+data.state+" — กดเริ่มรายการใหม่ก่อนสั่งครั้งถัดไป");await list("orders");return;
    }
    if(round===0)note("accepted = รับงานแล้ว กำลังตรวจผลธุรกิจ ไม่ใช่จองสำเร็จ");
    await new Promise(resolve=>setTimeout(resolve,2000));
    if(token!==generation||account!==user)return;
  }
  note("ครบขอบเขตตรวจอัตโนมัติ เลือกรายละเอียดเพื่อตรวจต่อได้");
}
async function session(data){
  data=data||await api("/api/session");++generation;
  user=data.user;role=data.role;csrf=data.csrf;pending=null;broken=false;selected=null;
  $("identity").textContent=user?user+" · "+role:"ยังไม่ได้เข้าสู่ระบบ";
  $("logout").hidden=!user;$("login-panel").hidden=!!user;
  $("customer").hidden=role!=="customer";$("operator").hidden=role!=="operator";
  for(const id of ["catalog-body","orders-body","operator-orders-body","operator-outbox-body"])$(id).replaceChildren();
  $("order-detail").textContent="ยังไม่ได้เลือกรายการ";$("operator-detail").textContent="ยังไม่ได้เลือกรายการ";
  if(role==="customer"){
    try{const raw=sessionStorage.getItem(key());if(raw){pending=JSON.parse(raw);if(!valid(pending))throw Error("invalid_journal");}}
    catch(_){pending=null;broken=true;}
    pendingNote();await catalog();await list("orders");note("เลือกสินค้าหรือตรวจคำขอเดิมได้ ไม่ส่งงานอัตโนมัติหลัง reload");
  }else if(role==="operator"){await list("operatorOrders");await list("outbox");note("ภาพรวมสำหรับตรวจสอบงาน");}
  else note("กรุณาเข้าสู่ระบบ");
}
$("login-form").addEventListener("submit",event=>{event.preventDefault();run(async()=>{
  const password=$("password").value;$("password").value="";
  await session(await api("/api/login",{username:$("username").value,password}));
});});
$("logout").addEventListener("click",()=>run(async()=>session(await api("/api/logout",{}))));
$("order-form").addEventListener("submit",event=>{event.preventDefault();run(async()=>{
  if(broken)throw Error("journal_broken");
  if(pending?.order_id){inspect(pending.order_id).catch(()=>note("ตรวจงานไม่สำเร็จ เลือกงานเดิมเพื่อลองใหม่"));return;}
  if(selected&&!pending){note("กดเริ่มรายการใหม่ก่อนส่งคำสั่งซื้อครั้งถัดไป");return;}
  const items=cart();
  if(items.length<1||items.length>2||items.some(i=>!Number.isInteger(i.quantity)||i.quantity<1||i.quantity>3)){
    note("เลือก 1–2 SKU จำนวน SKU ละ 1–3 ชิ้น");return;
  }
  if(pending&&JSON.stringify(pending.items)!==JSON.stringify(items)){note("คืนจำนวนสินค้าให้ตรงคำขอเดิมก่อนส่งซ้ำ");return;}
  if(!pending)save({key:crypto.randomUUID().replaceAll("-",""),items});
  const data=await api("/api/orders",{idempotency_key:pending.key,items:pending.items});
  if(!hex(data.order_id))throw Error("invalid_order_response");
  save({...pending,order_id:data.order_id});selected=data.order_id;await list("orders");
  inspect(data.order_id).catch(()=>note("ตรวจงานไม่สำเร็จ เลือกงานเดิมเพื่อลองใหม่"));
});});
$("new-order").addEventListener("click",()=>run(async()=>{
  if(broken||(pending&&!pending.order_id)){note("ต้องยืนยันคำขอเดิมก่อนเริ่มรายการใหม่");return;}
  if(pending&&!window.confirm("งานเดิมยังอยู่ในรายการ จะเริ่มคำสั่งซื้อใหม่หรือไม่?"))return;
  save(null);selected=null;++generation;$("order-detail").textContent="ยังไม่ได้เลือกรายการ";
  await catalog();note("พร้อมเริ่มคำสั่งซื้อใหม่");
}));
$("stop-poll").addEventListener("click",()=>{++generation;note("หยุดตรวจแล้ว งานบน server ไม่ได้ถูกยกเลิก");});
$("reload-orders").addEventListener("click",()=>run(()=>list("orders")));
$("next-orders").addEventListener("click",()=>run(()=>list("orders",cursors.orders)));
$("reload-operator").addEventListener("click",()=>run(async()=>{await list("operatorOrders");await list("outbox");}));
$("next-operator-orders").addEventListener("click",()=>run(()=>list("operatorOrders",cursors.operatorOrders)));
$("next-operator-outbox").addEventListener("click",()=>run(()=>list("outbox",cursors.outbox)));
run(()=>session());
})();
