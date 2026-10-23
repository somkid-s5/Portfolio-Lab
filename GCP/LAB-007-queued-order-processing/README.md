---
lab: LAB-007
platform: GCP
guide_status: brief
cloud_verification: not-run
last_verified: null
---
# Lab 07 — รับคำสั่งซื้อผ่าน Queue และจองสต็อกโดยไม่เกิดผลซ้ำ

## สถานการณ์

ทีมขายต้องรับคำสั่งซื้อได้โดยไม่บังคับให้ลูกค้ารอการประมวลผลทั้งหมด เมื่อ worker หยุดชั่วคราว งานต้องไม่หาย และเมื่อ Queue ส่งข้อความซ้ำ ระบบต้องไม่จองสินค้าซ้ำ ลูกค้าต้องกลับมาดูผลของคำสั่งซื้อเดิมได้ ส่วนทีมดูแลต้องรู้ว่างานค้างอยู่ที่การส่งเข้า Queue, การประมวลผล หรือ dead-letter

Solution นี้ชื่อ **Order Queue Desk** ผลสำเร็จทางธุรกิจคือจองสต็อกและเปลี่ยนคำสั่งซื้อเป็น confirmed ไม่ใช่การตัดเงิน ส่งสินค้า หรือรับประกัน exactly-once ของบริการภายนอก

**สถานะ:** Brief — กำหนดโจทย์และเกณฑ์รับมอบ ยังไม่ใช่คู่มือพร้อมทำ ไม่ได้สร้างระบบหรือทดสอบ GCP จริง ขั้นถัดไปต้องปิด Design ก่อนสร้าง App, infrastructure หรือ Tasks

## ผู้ใช้และงานที่ต้องทำได้

- alice / bob: login, เลือกสินค้าจาก catalog, ส่งคำสั่งซื้อ, ตรวจสถานะของตน และกลับมาหาคำขอเดิมเมื่อคำตอบหาย
- operator: ดู outbox/backlog/คำสั่งซื้อที่ติดขัด ตรวจ dead-letter และอนุมัติ replay เฉพาะงานที่ระบุ โดยไม่แก้ owner, ราคา หรือรายการสินค้าเพื่อให้ผ่าน
- dispatcher: ส่ง event ที่บันทึกไว้แล้วเข้า Pub/Sub แบบจำกัดจำนวนต่อรอบ และกู้คำขอ publish ที่ไม่ทราบผลได้
- worker: ตรวจ event และจองสต็อกใน PostgreSQL transaction โดยไม่ใช้ Pub/Sub message ID เป็น business idempotency key เพียงอย่างเดียว

ตัวอย่างข้อมูลสังเคราะห์: BOOK-01 ราคา 12,500 สตางค์, USB-01 ราคา 9,900 สตางค์ และ LAST-01 จำนวนคงเหลือหนึ่งชิ้นสำหรับทดสอบแข่งกันซื้อ ราคาและสต็อกตั้งต้นจะอยู่ใน schema/seed ที่มีเวอร์ชัน ใช้จำนวนเต็ม ไม่รับราคาจาก Browser มาเป็นราคาขายจริง

## Requirements และเกณฑ์รับมอบ

| ID | สิ่งที่ Solution ต้องทำ | หลักฐานที่ต้องเตรียมในคู่มือ |
|---|---|---|
| R1 | รับคำสั่งซื้อและติดตามผลครบวงจร | Browser → accepted/queued → confirmed หรือ rejected; owner, order ID, event ID และรายการสินค้าตรงกัน |
| R2 | ไม่ทำคำสั่งซื้อหายระหว่าง DB กับ Queue | สร้าง order และ outbox ใน transaction เดียว; ฉีด publish failure/คำตอบหาย แล้วส่งงานเดิมได้โดยไม่สร้าง order เพิ่ม |
| R3 | ไม่เกิดผลธุรกิจซ้ำเมื่อส่งหรือรับข้อความซ้ำ | message ID เดิมและใหม่แต่ event/order เดิม; crash หลัง SQL commit ก่อน ack; reservation ledger และยอดสต็อกไม่เปลี่ยนซ้ำ |
| R4 | รักษาสต็อกเมื่อหลายงานแข่งกัน | สอง order ซื้อ LAST-01 ที่เหลือหนึ่งชิ้นพร้อมกัน; confirmed ได้หนึ่งงาน อีกงาน rejected; ไม่มีสต็อกติดลบหรือจองได้เพียงบางรายการ |
| R5 | แยก business rejection ออกจาก transient และ poison event | สินค้าไม่พอเป็น terminal rejection; dependency fault ยังส่งซ้ำได้; schema เสียไป dead-letter โดยไม่แก้ข้อมูลธุรกิจ |
| R6 | ดูแล dead-letter และ replay อย่างตรวจสอบได้ | ตรวจ source/envelope/attempts ตามจริง, เก็บเหตุผล/ผู้อนุมัติ, replay จาก canonical outbox, ตรวจผลก่อน ack รายการ dead-letter |
| R7 | แยก owner, Cloud IAM และ DB roles | bob อ่าน order ของ alice ไม่ได้; anonymous เรียก worker/dispatcher ไม่ได้; runtime ไม่มี DDL/สิทธิ์ admin หรืออ่าน Secret ที่ไม่ต้องใช้ |
| R8 | เปลี่ยน throughput โดยยังรักษาความถูกต้อง | worker capacity 1 → 3 ตาม connection budget; เทียบ backlog/เวลาจบ/error/stock invariants ก่อน–หลัง แล้ว backout ได้ |
| R9 | ส่งมอบและปิดระบบได้ | correlation/logs/runbook, แผนแก้ unknown outcome, evidence/case study, cleanup รวม Queue/DLQ/SQL/Secrets/images/network และ rebuild ที่ไม่สวมรอยเป็น restore |

ผล HTTP 202 ของ Portal หมายถึงบันทึกรับงานแล้ว ไม่ได้หมายถึง publish สำเร็จหรือจองสต็อกแล้ว ผล HTTP ack ของ worker ต้องตามหลัง transaction ที่สรุปผลธุรกิจได้ หรือยืนยันว่าผลเดิมถูกบันทึกแล้วเท่านั้น

## Candidate architecture

วางระบบใน sandbox project ของ Lab นี้ ไม่ต้องเปิดทรัพยากรจาก Lab ก่อนค้างไว้:

| ส่วน | ตัวเลือกที่ต้องยืนยันใน Design |
|---|---|
| UI / Order API | Cloud Run Portal พร้อม session/CSRF/owner checks และ status page |
| Source of truth | Cloud SQL for PostgreSQL: catalog/stock, orders/items, outbox, processed events และ reservation ledger |
| Outbox publisher | Cloud Run dispatcher แบบ IAM-protected; drain จำนวนจำกัดต่อ request และมีการเรียกซ้ำตามรอบที่กำหนด |
| Queue | Pub/Sub topic และ authenticated push subscription ไป worker |
| Processor | Cloud Run worker; transaction จองสินค้าและบันทึก business deduplication |
| งานที่ส่งไม่สำเร็จ | Dead-letter topic พร้อม pull subscription สำหรับ inspect/replay ที่แยกสิทธิ์ |
| การเรียก dispatcher | พิจารณา Cloud Scheduler OIDC หรือ runner แบบ bounded ที่อธิบายความต่อเนื่องและค่าใช้จ่ายได้ ไม่ใช้ background thread ที่หวังว่า Cloud Run จะรันต่อหลังตอบ request |
| Private data path | Cloud SQL private IP และ Cloud Run Direct VPC egress; ระบุ VPC/subnet/private services access ตามขอบเขตจริง |
| Identity / delivery | แยก Portal, dispatcher, worker, push และ scheduler identities; Secret Manager, Artifact Registry และ Terraform roots ตาม deployment order |

เลือก region เบื้องต้น asia-southeast1 แต่ Pub/Sub topic/subscription ไม่ใช่ VM ใน regional subnet ต้องวาด service scope ตามจริง และกำหนด message storage policy หากโจทย์ต้องควบคุมที่อยู่ข้อมูล Worker ที่ต้องผ่าน IAM ไม่ใช่ private VPC ingress โดยอัตโนมัติ

Private IP เป็นเพียงเส้นทางเครือข่าย การยืนยัน DB identity/TLS และ connection pooling ต้องตัดสินใจให้ครบก่อนเขียน code ไม่ใช้ private IP แทนข้ออ้างว่าการเชื่อมต่อเข้ารหัสแล้ว

## ข้อตกลงความถูกต้องที่ต้องปิดใน Design

1. **API idempotency:** key มี scope ตาม owner และ fingerprint ของคำสั่งซื้อ คำขอซ้ำคืน order เดิม ส่วน key เดิมเปลี่ยนรายการต้อง conflict ไม่สร้างงานใหม่เมื่อไม่ทราบผล
2. **Transactional outbox:** order กับ canonical event เกิดใน transaction เดียว การ publish อยู่นอก SQL transaction คำตอบ publish หายอาจทำให้ส่งซ้ำได้ จึงต้องคง event ID เดิมและไม่ตีความว่าไม่มีข้อความแน่นอน
3. **Dispatcher claim:** drain มีเพดาน/lease/fencing และไม่ถือ SQL row lock ค้างระหว่าง network call ระบุวิธีกู้หลัง publish แล้วแต่ยัง mark ไม่สำเร็จ
4. **Business transaction:** ตรวจ payload binding, lock order และสินค้าในลำดับคงที่, จองครบทุก item หรือไม่จองเลย, บันทึก ledger/processed event/order result ใน transaction เดียว
5. **Deduplication:** unique business key และ payload fingerprint ต้องป้องกันทั้ง event ซ้ำและ event ID ต่างกันที่พยายามทำ order เดิมซ้ำ ความผิดปกติของ owner/items/ราคาไม่ถูกกลบด้วยการ ack ว่าเคยทำแล้ว
6. **Stock invariant:** available = stock ตั้งต้น − ผลรวม reservation ของ confirmed orders; rejected ไม่เหลือ partial reservation และจำนวนไม่ติดลบ
7. **Ack boundary:** SQL rollback/dependency failure ไม่ ack; commit แล้ว response หายต้องกู้ด้วย ledger ไม่ตัดสต็อกอีกรอบ Business rejection ต่างจากข้อความที่อ่านหรือประมวลผลตาม schema ไม่ได้
8. **Dead-letter:** กำหนดบน source subscription พร้อม service-agent IAM ที่ต้องใช้ จำนวน delivery attempts เป็นค่าประมาณ ไม่ใช้เป็น hard counter หรือรับประกันว่าจะเข้าคิวในวินาทีที่กำหนด
9. **Redrive:** อ่าน envelope ต้นทางแบบ bounded, ตรวจ order/outbox เดิม, บันทึก operator action และใช้ canonical event เดิม ไม่คัดลอกข้อความที่เสียแล้วเปลี่ยน owner/items เอง เมื่อ publish ตอบไม่แน่นอนต้อง resolve ก่อน ack หรือเปิดรอบใหม่
10. **Order state:** accepted/queued, confirmed, rejected และการแสดงสถานะ operational failure ต้องไม่ทำให้คำว่า dead-letter กลายเป็นผลธุรกิจว่าลูกค้าถูกปฏิเสธ ต้องปิด transition และวิธี reconcile ให้ชัด
11. **Observability:** order ID/event ID/outbox ID/message ID/request ID มีหน้าที่ต่างกัน ต้องตามเส้นทางได้โดยไม่มี credentials, session, JWT หรือ raw payload ใน logs
12. **Capacity:** pool size × instance/revision peak รวม Portal/dispatcher/worker/bootstrap ต้องไม่เกิน DB budget หลังหัก headroom ไม่เพิ่ม max instances โดยดูเฉพาะความเร็ว Queue

Pub/Sub push ใช้แบบ at-least-once และไม่รองรับ exactly-once delivery feature ของ pull จึงต้องพิสูจน์ผลธุรกิจไม่ซ้ำด้วย transaction/ledger ของ Solution นี้ ไม่ตั้งชื่อว่าเปิด exactly-once แล้วจบ

## Failure ที่ผู้เรียนต้องได้ฝึก

| สถานการณ์ | วิธีแยกสาเหตุ / ผลที่ต้องพิสูจน์ |
|---|---|
| Order บันทึกแล้ว แต่ publisher ติดต่อ Queue ไม่ได้ | ยังเห็น outbox เดิม; restore แล้วงานเดินต่อ ไม่มี order เพิ่ม |
| Publish สำเร็จ แต่ dispatcher ไม่ทันบันทึกผล | ส่ง event เดิมซ้ำได้; ledger จองสินค้าเพียงครั้งเดียว |
| Worker commit แล้วตอบไม่สำเร็จ | delivery ซ้ำตรวจผลเดิม; สต็อกและยอดสรุปไม่เปลี่ยนเพิ่ม |
| Worker ติดต่อ DB ไม่ได้ชั่วคราว | ไม่มี partial writes; backlog/age และ retry สัมพันธ์กับ fault/recovery |
| Poison schema | ไม่ประเมิน arbitrary payload; เข้า dead-letter ตามการทำงานจริง พร้อมข้อมูลอธิบายที่ปลอดภัย |
| Business stock ไม่พอ | rejected แบบ terminal และ ack ได้ ไม่ปะปนกับ poison/DLQ |
| Operator replay หรือ response หาย | คำขอเดิม resolve ได้; ข้อมูลธุรกิจเดิมไม่เปลี่ยน; ไม่ ack ก่อนทราบว่าจัดการรายการอย่างไร |
| เพิ่ม worker แล้ว DB เริ่มอิ่ม | ตรวจ connection/lock/error ก่อนแก้; backout capacity ไม่ลบ orders/ledger |

Fault controls ต้องเป็น sandbox revision/config ที่ปิดเป็นค่าเริ่มต้น ไม่เปิด endpoint ให้ลูกค้าสร้าง poison หรือสั่งทำ worker ล่ม การทดสอบแต่ละ fault มีจุดเริ่ม/จุดจบ/คืนค่าและช่วงสังเกตจำกัด

## Change Request

ทีมต้องการระบาย backlog ช่วงรับงานมากขึ้น ให้เสนอและทดลอง worker capacity จากหนึ่งเป็นสาม instance โดยคง event/order contract เดิม และกำหนด connection/concurrency budget ก่อน deploy

ใช้ bounded workload ชุดเดิมเปรียบเทียบ baseline/change/backout: จำนวน orders, input schedule, fixture/SHA, stock ก่อน–หลัง, confirmed/rejected, duplicate effects, outbox age, Queue age และเวลาจบตามนิยามเดียวกัน ไม่รับประกันว่าจะเร็วสามเท่าหรือใช้ผลสั้น ๆ อ้าง production capacity

เพดานตั้งต้นสำหรับออกแบบเครื่องมือ: ไม่เกิน 100 orders ต่อรอบ, 2 items ต่อ order, synthetic quantity ไม่เกิน 3 ต่อ item, producer ไม่เกิน 2 requests/วินาที และช่วงส่งไม่เกิน 60 วินาที ต้องเลือก seed/expected results ให้เพียงพอสำหรับรอบเทียบ โดยไม่ reset ฐานข้อมูลเดิมเงียบ ๆ

## สิ่งที่ต้องเตรียมเพื่อให้แล็บทำได้จริง

- Portal/catalog/order status UI พร้อมรหัสสังเคราะห์และ owner/role checks
- Schema/seed/migrations และ least-privilege DB roles ที่ติดตั้งได้จาก environment ใหม่
- Outbox dispatcher, push envelope parser, business worker และ operator DLQ/replay tooling
- ตัวสร้าง workload และตัวเทียบ stock/order/reservation snapshot แบบ read-only และ bounded
- Normal/negative/concurrent/failure tests กับ PostgreSQL จริงใน cloud CI ไม่ใช้ mock พิสูจน์ transaction
- Browser journey ผ่าน UI/API/DB จริงใน CI โดยติดป้าย Queue/signing doubles ให้ชัด
- Terraform/containers/health/logs พร้อมคำแนะนำ IAM/network/cost และภาพ architecture/recovery ที่ตรวจ render แล้ว
- README เดียวที่พาทำตั้งแต่ setup ถึง cleanup มี Expected/Actual และช่องหลักฐานข้างงาน ไม่ใช่เพียงคำสั่งสร้าง topic

## สิทธิ์ ต้นทุน และขอบเขตที่ยังไม่รวม

ต้องมี Billing/quotas และสิทธิ์จัดการ Cloud SQL, Cloud Run, Pub/Sub, IAM, VPC/private services access, Secrets, Artifact Registry และเครื่องมือเรียก dispatcher ของ sandbox ระบุ org-policy/public-login constraints ก่อน deploy

Cloud SQL, backups/storage, Queue retention/operations, network, images, logs และบริการตามเวลามีค่าใช้จ่าย Budget alert ไม่ใช่ hard cap ต้องกำหนดอายุการเปิดระบบ, instance/pool limits, retention, dead-letter inventory และลำดับหยุด producer ก่อน cleanup ไม่สร้างระบบจริงในงานจัดทำเอกสารนี้

ไม่รวม payment gateway, physical fulfillment, cross-region DR, service mesh, production SSO หรือการรับประกัน SLA แต่ระบุข้อจำกัดและสิ่งที่ต้องเพิ่มก่อนส่งให้ทีมใช้งานจริงได้

## ขั้นถัดไป

ปิด resource/identity/API/event/schema/state/transaction/outbox/DLQ contracts พร้อม acceptance test matrix และ task order ก่อนเริ่มเขียน Materials ระบุชนิด DB, runtime versions, TLS, IAM scopes, retention และ capacity ที่เลือกจริงพร้อมเหตุผล แล้วจึงทำ Diagram และคู่มือทีละขั้น

## แหล่งอ้างอิงที่ตรวจสำหรับ Brief

ตรวจเอกสารวันที่ 24 ตุลาคม 2026; รายละเอียด SDK/provider/location/ราคาและสิทธิ์ต้องตรวจอีกครั้งใน Design

- [Pub/Sub push delivery และ authentication](https://docs.cloud.google.com/pubsub/docs/push)
- [Exactly-once delivery: pull เท่านั้น และ publish-side duplicates](https://docs.cloud.google.com/pubsub/docs/exactly-once-delivery)
- [Dead-letter configuration, service-agent permissions และ approximate attempts](https://docs.cloud.google.com/pubsub/docs/dead-letter-topics)
- [Cloud Run เชื่อม Cloud SQL PostgreSQL ผ่าน private IP](https://docs.cloud.google.com/sql/docs/postgres/connect-run)
- [Cloud Run Direct VPC egress](https://docs.cloud.google.com/run/docs/configuring/vpc-direct-vpc)
