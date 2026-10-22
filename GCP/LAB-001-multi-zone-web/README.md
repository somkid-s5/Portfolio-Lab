---
lab: LAB-001
platform: GCP
guide_status: Brief
cloud_verification: Not run
---
# Lab 01 — เว็บหลาย Zone หลัง Load Balancer

ทีม Field Notes มีเว็บประชาสัมพันธ์แบบ stateless บน VM เครื่องเดียว เมื่อหยุด App เพื่อซ่อม ผู้ใช้เข้าเว็บไม่ได้ เป้าหมายคือให้ผู้ใช้เข้าผ่าน IP เดียวและส่งคำขอไปยัง App ที่พร้อม โดยผู้ดูแลตรวจอาการ แยกสาเหตุ และกู้บริการได้

## ขอบเขต Solution

ใช้ Global external Application Load Balancer แบบ HTTP, backend service เดียว และ unmanaged instance groups สองกลุ่มใน `asia-southeast1-b` และ `asia-southeast1-c` กลุ่มละ VM ใช้ Debian 12 และ Python standard library รับ HTTP ที่ 8080 มีหน้าเว็บและ JSON แสดงชื่อ backend เพื่อทดสอบเส้นทางจริง ไม่ใช้ session หรือฐานข้อมูล

VPC เป็น global; subnet `10.21.0.0/24` เป็น regional และใช้ร่วมกันทั้งสอง Zone ไม่วาด subnet แยกตาม Zone ตัว LB เป็น global อยู่นอก regional subnet ผู้ดูแลใช้ IAP SSH จาก Cloud Shell

## Requirements และเกณฑ์พิสูจน์

| ID | ความต้องการ | วิธีตรวจและเกณฑ์ | หลักฐานจริงที่ต้องบันทึก |
|---|---|---|---|
| R1 | มีทางเข้าเดียวและสอง App รับงาน | ส่ง 100 requests ที่ 5 requests/s ไป /api ผ่าน LB หลัง healthy ทั้งคู่ ต้องตอบ 200 พร้อม service/version/hostname และเห็นทั้ง A/B; ไม่กำหนดสัดส่วน 50:50 | CSV, summary JSON, backend health |
| R2 | App port ไม่รับ client อินเทอร์เน็ตโดยตรง | จาก Cloud Shell ทดสอบ external VM IP:8080 ด้วย timeout 5 วินาที ต้องเข้าไม่ได้ แต่ LB /api เข้าได้; ตรวจ firewall ประกอบ ไม่ใช้ timeout อย่างเดียวสรุปสาเหตุ | คำสั่ง ผลตรวจ และ firewall effective scope |
| R3 | เมื่อ A หยุด ยังให้บริการผ่าน B | เก็บ probe ต่อเนื่องช่วงหยุด service A พร้อมเวลา health transition หลัง LB แสดง A unhealthy ส่งอีก 50 requests ต้องสำเร็จและมาจาก B ทั้งหมด | transition CSV, health timestamps, steady-state CSV |
| R4 | กู้ A แล้วกลับมารับงาน | start service ตรวจ health ใน VM และ LB แล้วส่ง 100 requests ต้องเห็น A/B อีกครั้ง | journal, health, recovery CSV |
| R5 | เพิ่ม backend โดยไม่เปลี่ยน public endpoint | เพิ่ม C ใน asia-southeast1-a, group และ named port เดียวกัน แนบ backend service หลัง healthy ส่ง 150 requests เห็น A/B/C และใช้ IP เดิม | before/after config, CSV, เวลาเปลี่ยน |
| R6 | อธิบายผลโหลดอย่างมีขอบเขต | เปรียบเทียบ 2 กับ 10 requests/s จำนวน 100/300 ตามลำดับ วัด success/error และ p95 ของคำขอสำเร็จ ไม่เรียกค่าที่วัดว่า production capacity | raw CSV, summary, ข้อจำกัดการวัด |
| R7 | ปิดงานและสร้างกลับได้ | ลบครบ resource inventory รวม C และ reserved IPv4 ตรวจรายการเหลือ และบันทึก commit ที่ใช้เริ่มใหม่ | cleanup outputs, commit SHA |

ช่วง R3 อาจมีคำขอล้มเหลวก่อน health convergence ต้องเก็บตามจริง ไม่ตั้งเงื่อนไขว่า zero downtime และการหยุด service ไม่ใช่การจำลอง Zone outage จริง หาก sample ไม่เห็นทุก backend ให้ตรวจ health/affinity/cache แล้วรันทดสอบแบบจำกัดอีกครั้ง ไม่แก้ผลย้อนหลัง

## สัญญาของ App และเครื่องมือ

- `GET /`: หน้า Field Notes แสดง hostname, version, UTC
- `GET /api`: JSON service=field-notes พร้อม hostname/version/time_utc
- `GET /healthz`: 200 ปกติ และ 503 เมื่อมีไฟล์ unhealthy สำหรับแยก readiness ออกจาก process crash
- ทุก response มี Cache-Control: no-store และ X-Lab-Backend; unknown route ตอบ 404
- รันด้วย systemd ใต้ user เฉพาะ ไม่ใช้ root; Restart=on-failure ไม่ทำให้ manual stop กลับมาทันที
- probe ใช้ Python standard library จำกัด 600 requests, 10 requests/s, concurrency 10 และ timeout 30s ต่อครั้ง บันทึกทุก request และไม่เขียนทับผลเดิม
- ต้องตรวจ startup shell syntax และรัน App/probe integration tests ใน cloud CI ก่อนถือว่า materials ผ่าน review

## ทางเลือกและข้อแลกเปลี่ยน

เลือก unmanaged groups เพื่อเห็นการจัดการ A/B/C ชัดและฝึกแก้ service ด้วยตนเอง จึงไม่มี autoscaling หรือ autohealing ต้องไม่ใช้คำอธิบายว่า LB ซ่อม VM ให้ เลือก HTTP เพื่อตั้งต้นจาก IP โดยไม่ต้องซื้อ domain ห้ามใช้ข้อมูลลับหรือ credential จริง ก่อนใช้ production ต้องออกแบบ TLS/runtime/patching/observability และ availability เพิ่ม

VM มี ephemeral external IPv4 เพื่อออกไปติดตั้งแพ็กเกจ แต่ firewall inbound อนุญาต 8080 เฉพาะ Google proxy/health ranges และ 22 เฉพาะ IAP ไม่มี VM service account เพราะ App ไม่เรียก Cloud API ถ้าองค์กรห้าม external IPv4 ให้หยุด baseline และออกแบบ NAT/private access ที่ได้รับอนุญาต ไม่เปลี่ยนนโยบายองค์กรเพื่อผ่าน Lab

## ขอบเขตสิทธิ์และต้นทุนก่อนเริ่ม

ใช้ sandbox project ที่เปิด Billing; ผู้ทำต้องสร้าง Compute/network/firewall/LB และเปิด API ได้ แยกสิทธิ์ IAP กับสิทธิ์ login/sudo บน VM; รายการ role และกรณี OS Login ต้องยืนยันกับเอกสารทางการในคู่มือฉบับเต็ม ตรวจ quota e2-small ในสาม Zone, global address และ forwarding rules ก่อนเริ่ม

ค่า VM/disk/external IPv4/LB/data processing อาจเกิดตลอดเวลาที่ทรัพยากรยังอยู่ Budget alert ไม่ใช่ hard cap ไม่สร้างทรัพยากรในขั้นจัดทำเอกสารนี้ ผู้เรียนต้องอนุมัติงบของตนเองก่อนรัน เผื่อเวลา 3–4 ชั่วโมงและ cleanup วันเดียวกัน

## ลำดับการลงมือทำที่จะจัดทำต่อ

1. ตรวจ project, APIs, IAM, quota, งบ และเตรียม Cloud Shell/ไฟล์จาก commit ที่บันทึกไว้
2. สร้าง VPC/subnet และ firewall; ตรวจ source ranges และ target tags ก่อนสร้าง VM
3. สร้าง A/B ด้วย startup script เดียวกัน แล้วตรวจ process, local health และ journal
4. สร้าง zonal unmanaged groups และ named port http:8080
5. สร้าง health check, global backend service, URL map, proxy, frontend และ static IP ผ่าน Console
6. ตรวจเส้นทางหลักและ R1/R2 พร้อมบันทึกผลติดจุดตรวจ
7. ทำ fault/recovery และ bounded load comparison ตาม R3/R4/R6
8. วิเคราะห์ change request แล้วเพิ่ม C พร้อมทดสอบ R5; แยก diagram baseline กับหลังเปลี่ยน
9. สรุป requirement/evidence matrix, incident timeline, trade-offs และ case study จาก Actual เท่านั้น
10. ลบตาม dependency order และตรวจ R7; อธิบาย rebuild จาก clean project

## บันทึกผล

ยังไม่ได้สร้างทรัพยากรหรือรันทดสอบบน GCP ช่องผลจริงจะเพิ่มติดแต่ละ Task ในคู่มือฉบับเต็ม สถานะปัจจุบันเป็น Brief ไม่ใช่ Guide-ready
