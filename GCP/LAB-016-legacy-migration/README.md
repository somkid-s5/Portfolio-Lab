# Lab 16 — ย้ายระบบ Legacy พร้อมข้อมูลขึ้น Cloud

> **สถานะเอกสาร:** Design in progress — ปิด Brief แล้ว กำลังตรวจ Architecture และ migration flow ก่อนเขียน Tasks  
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

Front door ใช้ global external Application Load Balancer กับ HTTPS และใบรับรองทดสอบแบบ self-signed สำหรับ orders.lab.test; ทดสอบด้วย curl --resolve และ CA ที่ผู้เรียนสร้างในเครื่อง โดยไม่ต้องจดโดเมนสาธารณะหรือเก็บ private key ใน Repo. URL map เปลี่ยน default backend ระหว่าง backend service ของ unmanaged instance group กับ backend service ของ Cloud Run serverless NEG โดยเลือกให้มี active backend เพียงชุดเดียวในแต่ละครั้ง

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

## Design decision checkpoint

### ภาพรวม Solution

![Architecture ของระบบ Orders ก่อนและหลังย้าย](assets/solution.svg)

ภาพแสดงขอบเขตจริง: Load Balancer เป็น global service; VPC มี VM และ subnet ของ Direct VPC egress; Cloud Run กับ Cloud SQL เป็น regional managed services ที่อยู่นอก customer VPC; Private Services Access เชื่อม VPC ไป Cloud SQL private IP. Legacy VM อยู่ใน zonal unmanaged instance group สำหรับ backend ของ Load Balancer ส่วน Cloud Run ใช้ serverless NEG และ backend service แยกประเภทกัน

### เส้นทางย้ายข้อมูลและ Cutover

![ลำดับ freeze, transfer, reconcile, cutover และ backout](assets/migration-flow.svg)

### การตัดสินใจด้าน Design

| เรื่อง | แบบที่เลือก | เหตุผลและข้อจำกัด |
|---|---|---|
| Front door | Global external Application Load Balancer, HTTPS, URL map และ backend service แยกสำหรับ VM กับ serverless NEG | คง URL เดิมระหว่าง cutover; URL map ชี้ไป backend เดียวในแต่ละช่วง ไม่มีการแบ่ง traffic ระหว่างฐานข้อมูล |
| ทดสอบ TLS | orders.lab.test กับ self-signed certificate ที่สร้างในเครื่อง และ curl --resolve | ทดสอบ TLS/SAN โดยไม่ใช้ DNS สาธารณะ; private key อยู่ในเครื่องผู้เรียนเท่านั้น |
| Source | Compute Engine VM + Orders API + PostgreSQL 16 ใน zonal unmanaged instance group | ใช้จำลองระบบเดิมที่ทีมควบคุมเองและทำ backup/restore ซ้ำได้; ไม่อ้างว่าแทนระบบ on-premises จริง |
| Target | Orders API บน Cloud Run; PostgreSQL 16 บน Cloud SQL private IP | ใช้ Cloud SQL Auth Proxy/Cloud Run Cloud SQL connection ผ่าน Direct VPC egress และ Private Services Access; secret และ IAM จำกัดตาม runtime identity |
| Network ranges | VM subnet 10.80.0.0/24, Direct VPC egress subnet 10.80.1.0/26, PSA reserved range 10.80.2.0/24 | เป็นค่าตั้งต้นของ Lab; ก่อนสร้างต้องตรวจ overlap กับทุก subnet, peering route, quota และ Cloud SQL prerequisites |
| Migration หลัก | หยุด writers, ตรวจ transaction, pg_dump/restore, reconcile และค่อยเปลี่ยน URL map | เหมาะกับ dataset จำลองขนาดจำกัดและพิสูจน์ cutover/backout ได้; ผู้เรียนวัด write-freeze จริง ไม่มีคำกล่าวอ้าง zero downtime |
| DMS | Change Request เท่านั้น; ต้องผ่าน source configuration, private connectivity, compatibility และ cost/access gate | DMS ทำ initial load/CDC แต่เพิ่มทรัพยากรและ prerequisites; หาก gate ไม่ผ่านให้บันทึกเหตุผลแล้วใช้เส้นทางหลัก |
| Rollback | ก่อนเปิด writes ที่ target ให้คืน URL map ได้; หลัง target รับ writes ให้ forward-recover หรือทำ reverse synchronization ที่ออกแบบและพิสูจน์แล้ว | ป้องกัน split-brain และการทิ้งคำสั่งซื้อที่เขียนหลัง cutover |

### Network และ Identity ที่ต้องคงในคู่มือ

- Request: client → global HTTPS Load Balancer → URL map → backend service ที่เลือก → VM หรือ Cloud Run serverless NEG.
- Target database: Cloud Run ใช้ Direct VPC egress จาก subnet ที่กำหนด แล้วเชื่อม Cloud SQL ผ่าน private IP/PSA; runtime service account ได้ Cloud SQL Client และ Secret Manager Secret Accessor เฉพาะ secret ที่ต้องอ่าน.
- Public ingress: เปิด Cloud Run invocations ที่จำเป็นต่อ serverless NEG แต่จำกัด ingress ให้รับทาง external Application Load Balancer; ห้ามใช้ all ingress เป็นทางลัด.
- Legacy backend: health-check firewall เปิดเฉพาะช่วง IP และ port ที่ Google ระบุในเอกสาร ณ วันที่เขียน Tasks; SSH ใช้ IAP/OS Login ตาม Lab และไม่เปิด 22 สู่ Internet.
- DMS Change Request: private source connectivity ต้องตั้งตามวิธี DMS ที่เลือกจริง; destination Cloud SQL เป็นผู้เชื่อมต่อไป source ตาม migration flow ของ DMS. ไม่เปิด PostgreSQL สู่ public internet.
- Secrets, dump files, certificates และ Terraform state ต้องไม่ commit; ใช้ไฟล์ชั่วคราวที่จำกัดสิทธิ์และลบทิ้งหลัง Lab.

### เงื่อนไขก่อนเริ่ม Tasks

1. ตรวจเอกสารปัจจุบันของ global external Load Balancer, instance-group backend, serverless NEG, Cloud Run ingress/Direct VPC egress, Cloud SQL private IP/PSA และ PostgreSQL 16 ที่เลือก
2. ตรวจ API, IAM roles, region, subnet range, PSA allocation, quota, health-check firewall และค่าใช้จ่ายในบัญชีทดลอง โดยยังไม่สร้าง resource
3. ยืนยันว่า Cloud SQL Auth Proxy/socket + Direct VPC egress ใช้กับ app sample และ target private IP ตาม flow ที่จะเขียน; ตรวจคำสั่งและ syntax ใน CI เท่าที่ทำได้
4. ทำ runbook สำหรับ write-freeze, active transaction check, final backup/restore, row/business-total/sequence reconcile และ URL-map boundary ให้สอดคล้องกัน
5. แยก baseline path ออกจาก DMS Change Request และใส่ทางออกชัดเจนเมื่อ DMS gate ไม่ผ่าน

ภาพเป็น Architecture proposal สำหรับคู่มือ ยังไม่มีผล Cloud execution; Cloud verification ยังคง Not run.

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
