# Lab 16 — ย้ายระบบ Legacy พร้อมข้อมูลขึ้น Cloud

> **สถานะเอกสาร:** Brief in progress — ยังไม่ใช่คู่มือทำตามทีละ Task  
> **Cloud verification:** Not run — ยังไม่มีการสร้างหรือทดสอบทรัพยากร GCP  
> **ข้อมูลใน Lab:** ใช้ข้อมูลจำลองเท่านั้น ห้ามนำข้อมูลลูกค้าหรือข้อมูลจริงมาใส่

## สถานการณ์

ทีมมีระบบจัดการคำสั่งซื้อรุ่นเดิมที่รันบน Compute Engine VM และดูแล PostgreSQL เอง ต้องย้าย App ไป Cloud Run และฐานข้อมูลไป Cloud SQL for PostgreSQL โดยไม่ทำให้ข้อมูลคำสั่งซื้อขาดหรือซ้ำ ทีมต้องควบคุมช่วงที่หยุดเขียนข้อมูล ตรวจปลายทางก่อนเปลี่ยนทางเข้า และรู้ชัดว่าเมื่อไรยังถอยกลับได้

โจทย์นี้จำลองระบบเดิมไว้ใน GCP เพื่อให้ทำซ้ำและตรวจผลได้ ไม่ได้จำลองอุปกรณ์หรือระบบ on-premises จริง

## ผลลัพธ์ที่ต้องได้

เมื่อ Guide พร้อม ผู้เรียนจะได้ฝึกทำ migration แบบมี change control ตั้งแต่สำรวจ source, เลือก migration path, เตรียม target, ตรวจข้อมูล, สลับ traffic, ดูแลหลัง cutover และ cleanup โดยมีหลักฐานที่ตรวจย้อนกลับได้

การย้ายแบบเต็มชุดที่ใช้เป็นเส้นทางหลักยอมรับ write-freeze window และต้องวัดเวลาจริงระหว่างการทำ Lab ส่วนการลดเวลาหยุดเขียนเป็น Change Request ที่ใช้ continuous migration เมื่อ preflight ผ่าน ไม่มีการตั้งเป้า zero downtime หรือ zero data loss โดยไม่มีผลทดสอบรองรับ

## ขอบเขตของระบบ

### ระบบเดิม

- Compute Engine VM รัน Orders API และ PostgreSQL แบบ self-managed
- PostgreSQL เริ่มต้นที่ major version 16 เพื่อให้ source/target อยู่ในช่วงที่เอกสาร Database Migration Service รองรับ ณ วันที่ตรวจเอกสาร
- ใช้ชุดคำสั่งซื้อจำลองขนาดจำกัดและ seed ที่ทำซ้ำได้
- API มี health/readiness, อ่านรายการคำสั่งซื้อ, สร้างคำสั่งซื้อ และระบุว่า request ไปถึง legacy หรือ target

### ระบบเป้าหมาย

- Orders API เป็น container บน Cloud Run
- ข้อมูลอยู่บน Cloud SQL for PostgreSQL และเชื่อมต่อแบบ private
- ใช้ service identity แยกจากผู้เรียน เก็บรหัสผ่าน/ค่าเชื่อมต่อที่เป็นความลับใน Secret Manager
- เปิดทางเข้า App ผ่าน external Application Load Balancer; ปิด direct ingress ที่ไม่จำเป็นตามความสามารถของ Cloud Run

### ทางเข้าระบบ

มี backend service แยกกันสำหรับกลุ่ม VM เดิมและ serverless NEG ของ Cloud Run เพราะ backend คนละชนิด URL map เลือกได้ว่าขณะนั้น traffic จะไป backend ใด ใช้ front door เดิมตลอดการ cutover จึงทดสอบการเปลี่ยนเส้นทางโดยไม่เปลี่ยน URL ของผู้ใช้

ระหว่าง Design จะตัดสินรูปแบบ HTTPS และใบรับรองทดสอบที่ไม่ต้องพึ่งโดเมนสาธารณะ รวมทั้งตรวจข้อกำหนดของ load balancer กับ region อีกครั้ง

## ข้อกำหนดและวิธีพิสูจน์

| ID | Requirement / เกณฑ์ยอมรับ | หลักฐานที่ต้องเก็บ |
|---|---|---|
| R01 | Legacy และ target ทำ business flow เดียวกันได้: health/readiness, อ่านคำสั่งซื้อ และสร้างคำสั่งซื้อจำลอง โดยตอบสถานะ backend ชัดเจน | ผล request/response ของทั้งสองฝั่ง พร้อมเวลาทดสอบและ backend marker |
| R02 | ก่อนย้ายต้องบันทึกเวอร์ชัน PostgreSQL, database/schema, extension, primary keys, object ที่ไม่รองรับ, ขนาดข้อมูล และผู้ใช้/สิทธิ์ที่ App ต้องใช้ | Preflight inventory และรายการ issue ที่แก้แล้ว/ยอมรับเป็นข้อจำกัด |
| R03 | เส้นทางหลักหยุด writes ก่อนสร้าง final export แล้ว restore ลง target โดยมี migration run ID และไฟล์หลักฐานไม่บรรจุ secret | เวลาเริ่ม freeze, เวลา export/restore, checksum หรือ manifest ของไฟล์ และผลคำสั่ง |
| R04 | ระหว่าง freeze คำสั่งเขียนใหม่ต้องถูกปฏิเสธอย่างคาดหมาย และไม่มี transaction/worker ที่ยังเขียน source ค้างก่อน final export | API negative test, DB connection/transaction check และจำนวนรายการก่อน/หลัง freeze |
| R05 | หลัง restore ต้อง reconcile จำนวนรายการ, ยอดรวมตาม business rule, ค่าสถานะ, ID สูงสุด และความปลอดภัยของ sequence; ความต่างทุกจุดต้องอธิบายก่อนเปิดรับ writes | ผล reconciliation ก่อน/หลังและรายการ mismatch; ห้ามใส่ PASS หากยังไม่ได้รัน |
| R06 | สิทธิ์ของ Cloud Run ต่อ Cloud SQL/Secret Manager ต้องจำกัดตามหน้าที่; direct path ที่ไม่ควรเปิดต้องถูกปฏิเสธ แต่ front door ที่กำหนดยังทำงาน | IAM/config snapshot ที่ปกปิดข้อมูลลับ และผล negative/positive access tests |
| R07 | เปลี่ยน backend ของ URL map จาก legacy เป็น target ได้โดยคง front door เดิม และพิสูจน์ว่า request ถึง backend ที่ตั้งใจ | URL-map ก่อน/หลัง, backend marker, health/readiness และ timestamp ของ cutover |
| R08 | ก่อน target รับ writes ให้มี backout path ที่ทดสอบได้; หลัง target รับ writes ห้ามกลับ source โดยไม่ reconcile writes ที่เกิดใหม่ | บันทึก rollback boundary, ผล pre-write backout rehearsal และแผน forward recovery หลัง boundary |
| R09 | ผู้เรียนแยกสาเหตุ routing, App readiness, identity และ database connectivity จาก logs/diagnostics พร้อมกู้บริการตาม runbook | fault timeline, diagnostic output, action ที่ทำ และผลตรวจซ้ำ |
| R10 | Change Request ทดลอง continuous migration ได้เฉพาะเมื่อ version, pglogical/WAL settings, keys/objects, connectivity, IAM และ cost/access ผ่าน preflight; ก่อน promote หยุด writes และรอ lag ใกล้ศูนย์ | Compatibility gate, migration status/lag, promotion timestamp และ reconciliation; ถ้าไม่ผ่านให้เก็บเหตุผลและไม่สร้างทรัพยากร |

## วิธี migration ที่เลือกใน Brief

### เส้นทางหลัก: controlled write-freeze + export/restore

สำหรับข้อมูลจำลองที่มีขนาดจำกัด ให้ประกาศ maintenance/write freeze, ยืนยันว่าไม่มี writers ค้าง, ทำ final dump, restore ไป Cloud SQL, ตรวจ business invariants และ sequence แล้วจึงอนุญาตให้ cutover ได้ วิธีนี้เข้าใจง่ายและทำซ้ำได้ แต่ช่วงหยุดเขียนรวมเวลาที่ใช้ export, restore, ตรวจข้อมูล และเปลี่ยน route ผู้เรียนต้องวัดเวลาเอง

### Change Request: Database Migration Service continuous migration

DMS สำหรับ PostgreSQL ใช้ initial snapshot และ change data capture ในเส้นทาง standard migration ผู้สมัครทำ Lab ต้องตรวจ source/destination version, source configuration, extension, primary keys, DDL policy และ network ก่อนใช้งาน สำหรับ self-managed source บน Compute Engine มีวิธีเชื่อมต่อ private ผ่าน VPC peering ให้ตรวจตามเอกสารปัจจุบัน

ข้อจำกัดที่ต้องออกแบบรับมือ: DMS ไม่ย้าย user/role credentials; extension ที่ Cloud SQL ไม่รองรับใช้ต่อไม่ได้; DDL ทั่วไปไม่ถูก replicate อัตโนมัติ; ตารางไม่มี primary key ไม่รองรับ UPDATE/DELETE ใน standard migration; sequence state อาจต่างระหว่าง CDC และต้องตรวจหลัง promote. ระหว่าง cutover ให้หยุด writes และรอ replication delay ใกล้ศูนย์ เพราะการ promote ขณะที่ยังมี lag อาจทำให้ข้อมูลปลายทางไม่ครบ

DMS เป็น Change Request ที่มี resource/cost เพิ่ม จึงต้องมี cost/access gate ในคู่มือ และไม่ถือว่ารันแล้วจนกว่าจะมีผลจริง

## ขอบเขตและสมมติฐาน

- ใช้ข้อมูลจำลอง ไม่มี PII, credential, private key หรือ runtime export ใน repository
- Source เป็น VM ที่สร้างเพื่อ Lab ไม่ใช่ระบบ on-premises จริง
- PostgreSQL 16 เป็นตัวเลือกตั้งต้น; ตรวจเวอร์ชันที่ Cloud SQL รองรับ, region, edition, quota และวิธีเชื่อมต่ออีกครั้งก่อนเขียน Tasks
- ไม่ใช้ dual-writer และไม่เปิด writes ที่ target ก่อนผ่าน reconciliation/cutover gate
- ไม่มีการวัด production SLA หรืออ้าง throughput/performance จากชุดข้อมูลขนาดเล็ก
- ค่าใช้จ่ายจริงยังไม่ได้ประเมิน. VM/disk, Cloud SQL, load balancer, IP, logging, Artifact Registry และ DMS อาจคิดค่าใช้จ่าย; ผู้เรียนต้องตรวจราคา/งบประมาณก่อนสร้างทรัพยากร และทำ cleanup ตาม inventory
- เอกสารนี้ยังไม่สั่งสร้างทรัพยากร GCP; Cloud verification จึงคงเป็น Not run

## สิ่งที่จะปิดใน Design ก่อนเริ่มเขียน Tasks

1. ยืนยัน topology และ request/data/identity flows พร้อม Diagram ที่อิง service icon ทางการตาม [แนวทางไดอะแกรมของรีโป](../../docs/diagram-style.md)
2. เลือก connectivity ของ Cloud Run ↔ Cloud SQL และ DMS ↔ source ให้ตรงกับข้อจำกัด VPC/PSA/region
3. กำหนด IAM/API/roles, firewall, secret handling, TLS test method, quota และ cost/cleanup boundary
4. กำหนด maintenance gate, final dump/restore commands, data reconciliation contract และ rollback decision table
5. ตัดสินว่า DMS Change Request ใช้ standard migration หรือวิธีอื่น พร้อมกำหนด fallback หาก preflight ไม่ผ่าน

## บันทึกผลและหลักฐานระหว่างทำ

เมื่อเริ่มเขียน Tasks ให้เติมช่องบันทึกติดกับจุดตรวจแต่ละขั้น โดยแยก Expected ออกจากผลจริง:

| รายการบันทึก | Actual / Evidence |
|---|---|
| Source inventory และ compatibility issues | ยังไม่มีผล — รอผู้เรียนรัน Lab |
| จำนวน/ยอดรวม/sequence ก่อนย้าย | ยังไม่มีผล — รอผู้เรียนรัน Lab |
| เวลาเริ่ม/จบ write freeze และเวลาที่ front door สลับ backend | ยังไม่มีผล — รอผู้เรียนรัน Lab |
| ผล reconciliation และ mismatch ที่พบ | ยังไม่มีผล — รอผู้เรียนรัน Lab |
| Fault, diagnosis, recovery และ retest | ยังไม่มีผล — รอผู้เรียนรัน Lab |
| DMS eligibility, replication lag และ promotion (ถ้าทำ Change Request) | ยังไม่มีผล — รอผู้เรียนรัน Lab |
| Resource inventory, cleanup และค่าใช้จ่ายที่สังเกตได้ | ยังไม่มีผล — รอผู้เรียนรัน Lab |

## Case-study summary

- **Problem:** ระบบ Orders รุ่นเดิมอยู่บน VM และต้องย้าย App/Database โดยคุมข้อมูลกับช่วงเปลี่ยนระบบ
- **Decision:** จะบันทึกเหตุผลเลือก full export/restore หรือ continuous migration หลังปิด Design
- **Implementation:** ยังไม่เริ่มสร้าง Cloud resources หรือ author Tasks
- **Verification:** ยังไม่มีผล Cloud; ห้ามใช้ Expected เป็นผลจริง
- **Limitation / next action:** ปิด topology, IAM, network, cost และ cutover design ก่อนเขียนคู่มือ

## เอกสารอ้างอิง

ตรวจเอกสารทางการของ Google Cloud ณ วันที่ 25 ตุลาคม 2026; ตรวจซ้ำก่อนเขียนคำสั่งและ Tasks เพราะบริการ/ข้อกำหนดอาจเปลี่ยน

- [Database Migration Service for PostgreSQL: scenario overview](https://docs.cloud.google.com/database-migration/docs/postgres/scenario-overview)
- [Supported source and destination databases](https://docs.cloud.google.com/database-migration/docs/supported-databases)
- [Configure a self-managed PostgreSQL source for continuous migration](https://docs.cloud.google.com/database-migration/docs/postgres/configure-source-database)
- [PostgreSQL migration known limitations](https://docs.cloud.google.com/database-migration/docs/postgres/known-limitations)
- [PostgreSQL migration fidelity](https://docs.cloud.google.com/database-migration/docs/postgres/migration-fidelity)
- [Promote a PostgreSQL migration job](https://docs.cloud.google.com/database-migration/docs/postgres/promote-migration)
- [Cloud SQL for PostgreSQL from Cloud Run](https://docs.cloud.google.com/sql/docs/postgres/connect-run)
- [External Application Load Balancer use cases](https://docs.cloud.google.com/load-balancing/docs/https/use-cases)
- [Set up an external Application Load Balancer with Cloud Run](https://docs.cloud.google.com/load-balancing/docs/https/setting-up-https-serverless)
- [Network connectivity for standard PostgreSQL migrations](https://docs.cloud.google.com/database-migration/docs/postgres/networking-methods)
- [Private network connectivity to self-hosted PostgreSQL sources](https://docs.cloud.google.com/database-migration/docs/postgres/configure-src-connection-self-hosted)
