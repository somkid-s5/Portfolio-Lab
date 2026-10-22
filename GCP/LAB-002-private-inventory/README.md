---
lab: LAB-002
platform: GCP
guide_status: brief
cloud_verification: not-run
last_verified: null
---
# Lab 02 — Inventory ภายในองค์กรที่ไม่เปิด App และ Database สู่อินเทอร์เน็ต

ทีมคลังสินค้าต้องค้นหาสินค้า ดูยอดคงเหลือ และบันทึกรับเข้า/เบิกออกจากเครือข่ายภายใน ผู้ดูแลต้องแยกให้ได้ว่าการเข้าไม่ได้เกิดจาก DNS, network, App auth หรือฐานข้อมูล โดยไม่เปิด public ingress เพื่อแก้ปัญหา

## ขอบเขตที่เลือก

- Singapore region; custom VPC `lab002-vpc` มี app subnet `10.22.10.0/24`, data subnet `10.22.20.0/24`, client subnet `10.22.30.0/24` ทุก subnet เป็น regional ไม่ใช่ zonal
- App VM สอง Zone b/c ไม่มี external IP, unmanaged instance groups และ **regional internal passthrough Network Load Balancer TCP:8080**; App เป็น HTTP UI/API บน TCP นี้ ไม่ใช่ internal Application LB จึงไม่สร้าง proxy-only subnet
- PostgreSQL 15 บน data VM ไม่มี external IP ใช้ private IP คงที่ ให้ application DB user เฉพาะ database Inventory และ firewall 5432 เฉพาะ app target/source tags; client ห้ามต่อ DB โดยตรง
- Client VM ไม่มี external IP เข้า App ผ่าน private DNS `inventory.lab.internal` ซึ่งชี้ internal LB VIP; Cloud Shell ใช้ IAP SSH เข้า client แล้วรัน requests จาก client ไม่ทดสอบ internal VIP จาก Cloud Shell โดยตรง
- Cloud Router + Public NAT สำหรับ outbound package installation ของ private VMs เท่านั้น ไม่ใช่ทางเข้า App
- IAP SSH ใช้ source range/roles ตามข้อกำหนด; VM ไม่มี runtime service account เพราะไม่เรียก Cloud API จาก workload

## Business flow และข้อมูลที่จะเตรียม

UI ค้นหา SKU และดู stock; API ตรวจ role แบบ reader/operator ด้วย bearer token สำหรับ demo เก็บ token hash ใน App config ไม่ใส่ credential ใช้งานจริงใน Repo สร้าง token บน sandbox และส่งผ่าน SSH/file ที่ permission จำกัด ไม่ผ่าน query string หรือ screenshot แบบเปิดเผย App ต้องไม่ log token/password

ฐานข้อมูลมี products, stock และ movements; seed อย่างน้อย 5 สินค้า การเบิกใช้ transaction/row lock และห้าม stock ติดลบ movement มี idempotency key เพื่อไม่หักซ้ำเมื่อ retry สอง App ใช้ข้อมูลชุดเดียว ต้องมี schema/seed และตัวตรวจ invariant ให้ครบใน Lab นี้ ไม่พึ่ง Lab 01

## Requirements และหลักฐาน

| ID | ผลที่ต้องได้ | วิธีพิสูจน์ | หลักฐาน |
|---|---|---|---|
| R1 | Private client resolve และเข้า UI/API ได้ | DNS ตอบ VIP และ HTTP 200 จาก client; ตรวจ VM ทุกตัวไม่มี external IP | DNS output, VM inventory, response |
| R2 | สอง App ใช้ Inventory เดียวกัน | Read stock, operator สร้าง movement แล้วอ่านกลับจาก sample ที่เห็นทั้ง backend | request IDs, backend IDs, stock/movement |
| R3 | จำกัดสิทธิ์ผู้ใช้ App | ไม่มี token ได้ 401, reader write ได้ 403, operator ทำได้ | redacted HTTP results; ไม่เก็บ token |
| R4 | ไม่หัก stock ซ้ำ/ติดลบ | retry key เดิมไม่เพิ่ม movement; concurrent withdrawal เกิน stock ถูก reject อย่างมีเหตุผล; sum movements reconcile | bounded business test JSON, SQL invariant |
| R5 | Network boundary ถูกต้อง | client→DB5432 denied, app→DB allowed, IAP→SSH allowed; public ingress ไม่มีและไม่มี external IP | effective rules, timed tests, resource inventory |
| R6 | แยกและกู้ dependency outage | หยุด PostgreSQL ชั่วคราว ดู App 503/readiness/logs แล้ว start และทดสอบ business flow ซ้ำ | incident timeline, health, redacted logs |
| R7 | เพิ่มเครือข่าย client อย่างควบคุม | เพิ่ม subnet2 10.22.40.0/24/client2; ก่อนอนุญาต App ใช้ไม่ได้ หลังเพิ่มเฉพาะ App rule ใช้ได้ แต่ DB ยังเข้าไม่ได้ | before/after flow matrix |
| R8 | Cleanup/rebuild ครบ | ลบ private DNS/LB/groups/VM/disks/NAT/router/rules/subnets/VPC ที่สร้าง; ต้นทางอยู่ใน commit | inventory และคำสั่งตรวจของเหลือ |

Fault injection ต้องทำใน sandbox หลังบันทึกยอดตั้งต้นและสำรองข้อมูล ไม่อ้าง zero downtime เพราะ DB baseline เป็นเครื่องเดียว ไม่มี managed HA; ภายหลังอธิบาย trade-off ไป Cloud SQL แต่ไม่บังคับสร้างอีก Solution ในเรื่องนี้

## ทางเลือกและขอบเขตความปลอดภัย

เลือก internal passthrough LB เพื่อทดสอบ source-preserving private network path; firewall backend จึงต้องยอมรับ client CIDRs ที่ตั้งใจอนุญาตพร้อม Google health-check ranges ไม่ใช้กฎ proxy-only ของ Application LB มาปะปน LB private ไม่ใช่ระบบยืนยันตัวตนแทน App

Bearer token demo ใช้ฝึกแยก 401/403 จาก network deny ไม่อ้างว่าเป็น enterprise SSO ไม่ใช้ข้อมูลจริง เนื่องจาก baseline HTTP และ PostgreSQL private traffic ยังไม่เข้ารหัส end-to-end ระบุ TLS/องค์กร identity เป็นข้อจำกัด ไม่อ้าง private network เท่ากับป้องกันทุก threat

NAT/LB/VM/disk/IPv4/router traffic มีต้นทุน ต้องกำหนดวงเงินและเวลาปิดก่อนรัน ไม่สร้าง GCP resources ในขั้นจัดทำเอกสาร ตรวจ API, IAM, region/quota, image/แพ็กเกจและ organization constraints ก่อน Guide-ready

## ลำดับงานหลัง Brief

1. ยืนยัน port/source/destination access matrix, subnet/VIP/static addresses และ data/identity flow
2. สร้าง App, schema/seed, token management และ bounded tests พร้อมทดสอบกับ PostgreSQL ใน cloud CI
3. ทำ Diagram ที่ตรง private network และชนิด LB จริง
4. เขียน Console/CLI walkthrough ตั้งแต่ clean project พร้อม DNS/NAT/IAP, deploy และบันทึกข้างแต่ละ Task
5. ตรวจ normal/access/data/fault/change/recovery/cleanup ทุก requirement แล้วจึงเลื่อนเป็น Guide-ready

สถานะ: Brief เท่านั้น ยังไม่มี materials หรือผล GCP จริง
