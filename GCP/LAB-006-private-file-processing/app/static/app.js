'use strict';
let csrf = '', user = null, role = null, cursor = null, nextCursor = null, maxBytes = 1048576;
let polling = 0, busy = false;
const byId = id => document.getElementById(id);
const message = text => { byId('message').textContent = text; };
function pendingKey() { return 'lab006.pending.' + user; }
function pending() {
  const raw = sessionStorage.getItem(pendingKey());
  if (!raw) return null;
  try { return JSON.parse(raw); } catch (_) { throw new Error('ข้อมูลคำขอค้างอ่านไม่ได้ กรุณาตรวจรายการงานก่อนแก้ storage'); }
}
async function api(path, data, headers = {}) {
  const options = {credentials:'same-origin', cache:'no-store', signal:AbortSignal.timeout(15000)};
  if (data !== undefined) Object.assign(options, {method:'POST',
    headers:{'Content-Type':'application/json','X-CSRF-Token':csrf,...headers}, body:JSON.stringify(data)});
  const response = await fetch(path, options);
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || 'คำขอไม่สำเร็จ');
  return body;
}
async function session() {
  const result = await api('/api/session');
  csrf = result.csrf; user = result.user; role = result.role;
  maxBytes = result.max_bytes || 1048576;
  polling++;
  byId('login-panel').hidden = !!user; byId('workspace').hidden = !user;
  byId('customer-panel').hidden = role !== 'customer';
  byId('identity').textContent = user ? user + ' · ' + role : 'ยังไม่เข้าสู่ระบบ';
  byId('limits').textContent = 'ขนาดสูงสุด ' + (maxBytes/1048576) + ' MiB · UTF-8 CSV ตาม schema ของ Lab';
}
function button(label, action) {
  const node = document.createElement('button'); node.type = 'button'; node.textContent = label;
  node.className = 'secondary';
  node.addEventListener('click', () => action().catch(error => message(error.message)));
  return node;
}
function endpoint() { return role === 'operator' ? '/api/operator/jobs' : '/api/jobs'; }
async function detail(id) {
  const item = await api(endpoint() + '/' + id);
  byId('detail-panel').hidden = false; byId('detail').textContent = JSON.stringify(item, null, 2);
  return item;
}
async function download(id) {
  const result = await api('/api/jobs/' + id + '/download-link', {});
  const url = new URL(result.url);
  if (url.protocol !== 'https:' || url.hostname !== 'storage.googleapis.com') throw new Error('ปลายทางดาวน์โหลดไม่ตรง');
  const a = document.createElement('a'); a.href = url.href; a.rel = 'noreferrer'; a.referrerPolicy = 'no-referrer';
  document.body.appendChild(a); a.click(); a.remove(); // Do not persist capability in the page or storage.
}
async function retry(id, newEpoch = false) {
  const key = 'lab006.retry.' + user + '.' + id;
  let record = sessionStorage.getItem(key);
  if (newEpoch && !window.confirm('เปิดรอบ retry ใหม่โดยคงไฟล์เดิม? ใช้ได้ไม่เกินสองรอบ')) return;
  if (!record || newEpoch) { record = 'retry-' + crypto.randomUUID(); sessionStorage.setItem(key, record); }
  const result = await api('/api/operator/jobs/' + id + '/retry', {request_key:record});
  message('รอบ retry ' + result.epoch + ' · ' + result.dispatch + ' — ตรวจสถานะงานต่อ ไม่ใช่ผลธุรกิจสำเร็จ');
  await detail(id);
}
async function list(reset = false) {
  if (reset) cursor = null;
  const result = await api(endpoint() + '?limit=20' + (cursor ? '&cursor=' + encodeURIComponent(cursor) : ''));
  nextCursor = result.next_cursor; byId('next').disabled = !nextCursor; byId('jobs').replaceChildren();
  for (const item of result.jobs) {
    const row = document.createElement('tr'), title = document.createElement('td'), status = document.createElement('td'), actions = document.createElement('td');
    const name = document.createElement('div'); name.textContent = item.display_name || 'CSV';
    const id = document.createElement('code'); id.textContent = item.job_id; title.append(name, id);
    const badge = document.createElement('span'); badge.className = 'badge ' + item.state; badge.textContent = item.state;
    status.append(badge); actions.append(button('รายละเอียด', () => detail(item.job_id)));
    if (role === 'customer' && item.state === 'succeeded') actions.append(button('ดาวน์โหลด JSON', () => download(item.job_id)));
    if (role === 'operator' && (item.state === 'retry_pending' || (item.state === 'failed' && item.safe_reason === 'retry_budget'))) {
      actions.append(button('Retry คำขอเดิม', () => retry(item.job_id)));
      if (item.state === 'failed' && item.attempt_epoch > 0 && item.attempt_epoch < 2)
        actions.append(button('เปิดรอบ retry ใหม่', () => retry(item.job_id, true)));
    }
    row.append(title, status, actions); byId('jobs').append(row);
  }
}
async function poll(id) {
  const token = ++polling;
  for (let i = 0; i < 30 && token === polling; i++) {
    const item = await detail(id);
    if (['succeeded','rejected','failed','expired'].includes(item.state)) { await list(true); return; }
    await new Promise(resolve => setTimeout(resolve, 2000));
  }
  if (token === polling) message('ครบช่วงตรวจอัตโนมัติแล้ว กดรายละเอียดหรือโหลดรายการใหม่เพื่อตรวจต่อ');
}
async function upload(event) {
  event.preventDefault(); if (busy) return; busy = true; byId('upload-button').disabled = true; byId('logout').disabled = true;
  try {
    const file = byId('file').files[0];
    if (!file || file.size < 1 || file.size > maxBytes) throw new Error('ขนาดไฟล์ไม่อยู่ในขอบเขตที่กำหนด');
    const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', await file.arrayBuffer())))
      .map(x => x.toString(16).padStart(2,'0')).join('');
    let record = pending();
    if (record && (record.sha256 !== hash || record.name !== file.name))
      throw new Error('มีคำขอค้างของไฟล์อื่น เลือกไฟล์เดิมและ resolve งานก่อน ไม่สร้าง key ใหม่');
    if (!record) {
      record = {key:'upload-' + crypto.randomUUID(), sha256:hash, name:file.name};
      sessionStorage.setItem(pendingKey(), JSON.stringify(record));
    }
    if (!record.job_id) {
      const created = await api('/api/jobs', {display_name:record.name}, {'Idempotency-Key':record.key});
      record.job_id = created.job_id; sessionStorage.setItem(pendingKey(), JSON.stringify(record));
    }
    const current = await api('/api/jobs/' + record.job_id);
    if (current.state !== 'awaiting_upload') {
      sessionStorage.removeItem(pendingKey()); message('พบงานเดิมแล้ว กำลังตรวจสถานะ'); await poll(record.job_id); return;
    }
    const policy = await api('/api/jobs/' + record.job_id + '/upload-policy', {});
    const target = new URL(policy.url);
    if (target.protocol !== 'https:' || target.hostname !== 'storage.googleapis.com') throw new Error('ปลายทางอัปโหลดไม่ตรง');
    const form = new FormData();
    for (const [key,value] of Object.entries(policy.fields)) form.append(key,value);
    form.append('file', new Blob([file], {type:'text/csv'}), 'source.csv');
    const result = await fetch(target.href, {method:'POST', body:form, credentials:'omit',
      redirect:'error', signal:AbortSignal.timeout(30000), referrerPolicy:'no-referrer'});
    if (result.status !== 201) throw new Error('Storage ยังไม่ยืนยันการอัปโหลด ตรวจงานเดิมก่อนส่งต่อ');
    sessionStorage.removeItem(pendingKey()); message('อัปโหลดแล้ว รอ worker ตรวจข้อมูล'); await list(true); await poll(record.job_id);
  } catch (error) { message(error.message + ' — เก็บคำขอเดิมไว้ หากไม่แน่ใจให้ตรวจรายการงานก่อน'); }
  finally { busy = false; byId('upload-button').disabled = false; byId('logout').disabled = false; }
}
byId('upload-form').addEventListener('submit', upload);
byId('login-form').addEventListener('submit', async event => {
  event.preventDefault();
  try {
    await api('/api/login', {username:byId('username').value, password:byId('password').value});
    byId('password').value = ''; await session(); await list(true); message('เข้าสู่ระบบแล้ว');
  } catch (error) { byId('password').value = ''; message(error.message); }
});
byId('logout').addEventListener('click', async () => {
  try { polling++; await api('/api/logout', {}); await session(); byId('jobs').replaceChildren(); byId('detail-panel').hidden = true; }
  catch (error) { message(error.message); }
});
byId('refresh').addEventListener('click', () => list(true).catch(error => message(error.message)));
byId('next').addEventListener('click', () => { cursor = nextCursor; list().catch(error => message(error.message)); });
byId('stop').addEventListener('click', () => { polling++; message('หยุดตรวจอัตโนมัติแล้ว'); });
session().then(() => user && list(true)).catch(error => message(error.message));
