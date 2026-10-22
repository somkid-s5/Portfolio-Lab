const el=id=>document.getElementById(id);
let csrf='';
function key(){return Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join('');}
async function call(path,method='GET',data=null,requestKey=null){
 const headers={};if(method!=='GET'){headers['X-CSRF-Token']=csrf;headers['Content-Type']='application/json';}
 if(requestKey)headers['Idempotency-Key']=requestKey;
 const response=await fetch(path,{method,headers,body:data===null?null:JSON.stringify(data),credentials:'same-origin'});
 const body=await response.json();el('result').textContent=JSON.stringify({status:response.status,...body},null,2);
 return {response,body};
}
async function identity(){
 const {body}=await call('/api/session');csrf=body.csrf;
 el('identity').textContent=body.username?body.username+' / '+body.role:'ยังไม่ได้เข้าใช้งาน';
}
function cell(tr,value){const td=document.createElement('td');td.textContent=value;tr.append(td);return td;}
async function slots(){
 const {body}=await call('/api/slots');el('slots').replaceChildren();
 for(const slot of body.slots||[]){const tr=document.createElement('tr');cell(tr,slot.label);cell(tr,slot.booked+'/'+slot.capacity);
 const td=cell(tr,'');const button=document.createElement('button');button.textContent='จอง';let retryKey=key();
 button.onclick=async()=>{button.disabled=true;try{const {response}=await call('/api/bookings','POST',{slot_id:slot.id},retryKey);
 if(response.ok){retryKey=key();await refreshData();}}catch(e){el('result').textContent='Network error: ตรวจรายการของคุณก่อนลองซ้ำ';}finally{button.disabled=false;}};
 td.append(button);tr.append(td);el('slots').append(tr);}
}
async function bookings(){
 const {body}=await call('/api/bookings');el('bookings').replaceChildren();
 for(const booking of body.bookings||[]){const tr=document.createElement('tr');cell(tr,booking.id);cell(tr,booking.slot_id);cell(tr,booking.status);
 const td=cell(tr,'');if(booking.status==='confirmed'){const button=document.createElement('button');button.textContent='ยกเลิก';
 button.onclick=async()=>{button.disabled=true;try{await call('/api/bookings/'+encodeURIComponent(booking.id)+'/cancel','POST',{});await refreshData();}finally{button.disabled=false;}};td.append(button);}
 el('bookings').append(tr);}
}
async function refreshData(){await slots();await bookings();}
el('login').onsubmit=async event=>{event.preventDefault();const form=new FormData(event.target);
 try{const {response,body}=await call('/api/login','POST',{username:form.get('username'),password:form.get('password')});
 event.target.elements.password.value='';if(response.ok){csrf=body.csrf;await identity();await refreshData();}}
 catch(e){el('result').textContent='Network error';}};
el('logout').onclick=async()=>{try{await call('/api/logout','POST',{});el('slots').replaceChildren();el('bookings').replaceChildren();await identity();}catch(e){el('result').textContent='Network error';}};
el('load-slots').onclick=()=>slots().catch(()=>{el('result').textContent='Network error';});
el('load-bookings').onclick=()=>bookings().catch(()=>{el('result').textContent='Network error';});
el('operator').onclick=()=>call('/api/operator/bookings').catch(()=>{el('result').textContent='Network error';});
identity().catch(()=>{el('result').textContent='ไม่สามารถโหลด session ได้';});
