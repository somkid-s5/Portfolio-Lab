---
lab: LAB-007
platform: GCP
guide_status: design
cloud_verification: not-run
last_verified: null
---
# Lab 07 — รับคำสั่งซื้อผ่าน Queue และจองสต็อกโดยไม่เกิดผลซ้ำ

## สถานการณ์

ทีมขายต้องรับคำสั่งซื้อได้โดยไม่บังคับให้ลูกค้ารอการประมวลผลทั้งหมด เมื่อ worker หยุดชั่วคราว งานต้องไม่หาย และเมื่อ Queue ส่งข้อความซ้ำ ระบบต้องไม่จองสินค้าซ้ำ ลูกค้าต้องกลับมาดูผลของคำสั่งซื้อเดิมได้ ส่วนทีมดูแลต้องรู้ว่างานค้างอยู่ที่การส่งเข้า Queue, การประมวลผล หรือ dead-letter

Solution นี้ชื่อ **Order Queue Desk** ผลสำเร็จทางธุรกิจคือจองสต็อกและเปลี่ยนคำสั่งซื้อเป็น confirmed ไม่ใช่การตัดเงิน ส่งสินค้า หรือรับประกัน exactly-once ของบริการภายนอก

**สถานะ:** Design — กำหนดโจทย์และสัญญาระบบแล้ว ขั้นถัดไปสร้าง Materials และทดสอบตามลำดับด้านล่าง ยังไม่ใช่คู่มือพร้อมทำและไม่มีผลทดสอบ GCP จริง

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

## Design — สัญญาที่ใช้สร้างระบบ

### 1. ทรัพยากรและวิธีเชื่อมต่อที่เลือก

| ส่วน | ค่าที่ใช้เป็น baseline |
|---|---|
| Runtime | Python 3.12, Flask/Gunicorn; Cloud Run second generation ใน asia-southeast1; min instances 0 |
| Portal | lab007-portal; max 2 instances/revision, concurrency 4, request timeout 30s, memory 512 MiB |
| Dispatcher | lab007-dispatcher; IAM-required, max 1/revision, concurrency 1, request timeout 60s |
| Worker | lab007-worker; IAM-required, max 1/revision → change 3, concurrency 1, request timeout 60s, memory 512 MiB |
| Dispatcher trigger | Cloud Scheduler HTTP POST ทุกหนึ่งนาทีตาม UTC ใช้ OIDC; audience เป็น dispatcher origin และ target เป็น /internal/outbox/drain |
| Queue | lab007-orders topic; lab007-orders-worker push subscription → worker /events/orders; explicit push identity/audience |
| Dead-letter | lab007-orders-dead topic + lab007-orders-dead-inspect pull subscription; max delivery attempts 10 แบบ best-effort ไม่ใช่ hard counter |
| Retry/retention | source retry backoff 10–60s, ack deadline 60s, retention 1 วัน; DLT topic/subscription retention 1 วัน; ไม่เปิด retain acknowledged messages โดยไม่จำเป็น |
| Database | PostgreSQL 16, Enterprise, ZONAL, dedicated db-custom-2-7680; database order_queue; ไม่เปิด public IP |
| Network | lab007-vpc, regional Direct VPC subnet 10.77.10.0/26, PSA range 10.77.240.0/24; ไม่ใช้ subnet CIDR ซ้ำกับระบบอื่น |
| DB transport | Cloud SQL Python Connector + pg8000, private IP ผ่าน Direct VPC egress; connector จัดการ TLS/instance identity; attached SA สำหรับ Google API และ DB password แยก role |
| Delivery assets | Artifact Registry lab007-orders, image@sha256, Secret versions แบบตัวเลข; Terraform 1.9.x/provider Google 6.50.0 เป็นจุดตั้งต้นที่ต้อง validate ใน CI |

ตั้ง Direct VPC egress แบบ private-ranges-only เพื่อส่ง SQL private traffic เข้า VPC โดยไม่บังคับ Pub/Sub/Secret APIs ทั้งหมดผ่าน NAT ไม่สร้าง Cloud NAT เพียงเพื่อให้ Diagram เต็ม Cloud Run ใช้ resource นอก subnet แต่มี Direct VPC network attachment ส่วน Cloud SQL อยู่ managed producer network ที่เชื่อมด้วย PSA ไม่ใช่ VM ใน subnet ของ Portal

Pub/Sub topics เป็นทรัพยากรที่ไม่ผูกกับ regional subnet ตั้ง allowed persistence region เป็น asia-southeast1 ทั้ง source และ dead-letter topic ไม่ตีความว่า resource กลายเป็น regional VM

ขนาด DB ที่เลือกมีต้นทุนสูงกว่า shared-core แต่ให้พื้นที่สำหรับทดลอง connection/lock และ capacity โดยไม่ตั้งต้นด้วย DB เล็กจนแยก bottleneck ไม่ได้ นี่ไม่ใช่ HA Lab หรือ benchmark tier ต้องบันทึกเวลาที่เปิดและ cleanup หลังทดสอบ รุ่น dependencies ของ connector/driver/PubSub จะล็อกพร้อม real-package API checks ใน Materials ไม่ใช้ชื่อ latest ใน image หรือคำสั่งติดตั้งของคู่มือ

### 2. Identity, Secret และ DB role

| Identity | Google Cloud permissions | DB / App permissions |
|---|---|---|
| Portal SA | Cloud SQL Client; อ่าน auth/portal-DB Secrets ของตัวเอง | order_api: อ่าน catalog, สร้าง order/items/outbox ผ่าน transaction interface, อ่านสถานะ/operational view และขอ replay ผ่าน interface ที่จำกัด |
| Dispatcher SA | Cloud SQL Client; อ่าน dispatcher-DB Secret; publisher เฉพาะ source topic | outbox_dispatcher: claim/finish/release outbox; ไม่แก้ stock หรือ order result |
| Worker SA | Cloud SQL Client; อ่าน worker-DB Secret | order_worker: lock/อ่าน order, transaction จองสินค้า/ledger/processed events และ terminal result; ไม่สร้าง/แก้ catalog price หรือ DDL |
| Push SA | run.invoker เฉพาะ worker | ไม่มี DB/Secret/publisher role |
| Scheduler SA | run.invoker เฉพาะ dispatcher | ไม่มี DB/Secret/publisher role |
| Pub/Sub service agent | สร้าง OIDC token สำหรับ Push SA ตาม resource scope; DLT publisher และ source-subscription subscriber ตามเอกสาร | ไม่ใช้เป็น App runtime SA |
| Bootstrap SA / Job | Cloud SQL Client และอ่าน bootstrap/admin+initial-role Secrets เฉพาะช่วงติดตั้ง | admin สำหรับ schema/role/grants/seed ครั้งแรก ไม่ใช้ใน serving services |
| ผู้ดูแล DLQ | subscriber เฉพาะ dead-inspect subscription; login operator ใน Portal | ไม่รับ DB admin หรือสิทธิ์แก้ business payload โดยตรง |

แยก Cloud IAM ออกจาก DB login: role Cloud SQL Client ไม่ได้ให้สิทธิ์อ่านตารางเอง แต่ละ DB role เป็น LOGIN/NOSUPERUSER/NOCREATEDB/NOCREATEROLE ไม่มีสิทธิ์ DDL/delete ledger และไม่เป็นเจ้าของ schema การออกแบบ SQL interface ต้องใช้ explicit schema/search_path และ grants ไม่ให้ PUBLIC เรียก privileged functions

Foundation สร้าง Secret containers เท่านั้น การตั้ง admin password และ initial credentials ต้องใช้ private bundle/API workflow ที่ไม่ใส่ payload ใน Terraform/state/image/arguments ที่พิมพ์ออก log จากนั้น bootstrap Job ใช้ private IP ไม่เปิด public DB หรืออนุญาต laptop IP เพื่อ bootstrap ติดตั้งซ้ำต้องตรวจ schema version/seed identity และไม่ reset รหัสหรือยอดคงเหลือของระบบที่มีข้อมูลอยู่แล้ว

Portal เปิด login ผ่าน App auth แต่ทุก business mutation ต้องตรวจ session/role/CSRF และ owner จาก session ไม่รับ owner จาก request ลูกค้าไม่เข้าถึง DB หรือ Pub/Sub โดยตรง Bootstrap identity/Secret access ไม่คงไว้ใน runtime ของ Portal/worker

### 3. ข้อมูลและ API contract

สินค้าเริ่มต้น: BOOK-01/USB-01 อย่างละ 200 หน่วย และ LAST-01 หนึ่งหน่วย เก็บ seed fingerprint/version ราคาเป็น integer satang snapshot ลง order items ตอนรับงาน 1–2 SKU ที่ไม่ซ้ำต่อ order, quantity 1–3 ต่อ item, ไม่รับ client price, SKU allowlist และ canonical item order ตาม SKU

IDs เป็น UUID hex32 จาก server ส่วน idempotency key ที่ client สร้างต้องมีรูปแบบ/ความยาวจำกัด เก็บ hash(owner+key), request fingerprint และ order reference ไว้ใน transaction เดียว ไม่เอา raw key ไปเป็น log field ไม่ลบ idempotency/ledger ก่อน Queue/DLQ และ replay window สิ้นสุด

| Endpoint | สัญญา |
|---|---|
| GET /api/session; POST /api/login,/api/logout | Secure/HttpOnly/SameSite cookie, hashed demo credentials, CSRF สำหรับ mutations, bounded JSON body |
| GET /api/catalog | login required; คืน SKU/ราคา ไม่ให้ client ตั้ง stock หรือราคาขาย |
| POST /api/orders | owner จาก session, body มี items และ idempotency key เท่านั้น; commit order/items/outbox แล้วตอบ 202 พร้อม order ID |
| GET /api/orders; GET /api/orders/{id} | owner-filtered pagination ≤20; foreign owner 404; คืน business state แยกจาก dispatch state |
| GET /api/operator/orders; GET /api/operator/outbox | operator only; safe operational projection ไม่คืน credentials/raw message |
| POST /api/operator/outbox/{event_id}/replay | operator+CSRF+request key; audit/prepare replay แบบ idempotent และ bounded ไม่รับ replacement payload |
| POST dispatcher /internal/outbox/drain | IAM ก่อน App; bounded empty/configured body ไม่มี arbitrary topic/SQL/URL จาก caller |
| POST worker /events/orders | IAM ก่อน App; wrapped Pub/Sub push JSON ≤64 KiB, strict base64 decoding, decoded data ≤4 KiB, exact subscription binding |
| GET /livez; GET /healthz | process readiness แยกจาก bounded DB query; ไม่เขียนข้อมูลหรือไล่อ่าน order ทุกตัว |

Canonical event มีเพียง schema_version=1, event_id, order_id, order_fingerprint โดย UUID/order data มาจาก DB ไม่แนบราคา/owner ที่แก้เองได้จาก message Worker ต้องเทียบ event ID และ fingerprint กับ canonical outbox ก่อนทำงาน ไม่เชื่อ Pub/Sub attributes แทน SQL binding และไม่ติดตาม URL ใน payload

Business state มี accepted → confirmed หรือ rejected และไม่ย้อนกลับ confirmed หมายถึงจองครบทุก item; rejected มี safe reason เช่น insufficient_stock

Dispatch state แยกเป็น pending/publishing/published/exhausted; published หมายถึง Pub/Sub ตอบรับ publish ไม่ใช่ worker สำเร็จ Worker อาจทำงานเสร็จก่อน dispatcher mark published ได้ ต้องไม่เขียน state ของ order ย้อนเป็น queued ภายหลัง ส่วน dead-letter เป็น transport observation ที่ต้อง reconcile ไม่ใช่ business rejection

### 4. Schema และ transaction boundaries

| ตาราง | Invariant สำคัญ |
|---|---|
| products | PK SKU, seed stock/available ≥0, unit price satang ≥0, seed version |
| orders | PK order ID, owner, unique(owner,key_hash), request fingerprint, accepted/confirmed/rejected, safe reason/timestamps |
| order_items | PK(order ID,SKU), quantity/price snapshot/line total; FK ไป order/product |
| outbox | PK event ID, unique order ID, canonical event bytes/hash, dispatch state, lease token/until, attempts/epoch, safe last outcome |
| processed_events | unique event ID และ unique order ID; canonical fingerprint, confirmed/rejected outcome; ไม่มีคำว่าเคยทำแล้วโดยไม่เทียบ binding |
| reservations | unique(order ID,SKU), units/price snapshot; FK; มีเฉพาะ confirmed orders และไม่แก้หรือลบระหว่างทำ Lab |
| operator_actions | unique(operator,request_key_hash), event ID/source digest/epoch, reason/result; ไม่เก็บ JWT/ack token |

**Create:** normalize/fingerprint → lookup idempotency → read catalog/price → insert order/items/canonical outbox ใน SQL transaction เดียว หากคำตอบ commit หายให้ lookup คำขอเดิม ไม่เรียก publish ใน transaction นี้

**Dispatch:** claim ด้วย row lock/SKIP LOCKED และ token/lease120s → commit ก่อน network → publish canonical event → finish เฉพาะ token ปัจจุบัน ถ้าคำตอบหายให้ release หรือรอ lease แล้วส่ง event ID เดิม; stale dispatcher ห้าม mark ตามผล network ของรอบเก่า

หนึ่ง drain รับได้สูงสุด 20 events และมี cooperative budget 40s โดยเริ่ม operation ใหม่เฉพาะเมื่อเหลือเวลาพอสำหรับ bounded call; publish call timeout5s/retryปิด, ไม่ต่อ lease ไม่จำกัด Scheduler overlap/responseหายอาจเรียก drain ซ้ำ จึงไม่ใช้ Scheduler เป็น lock หลัก

Dispatch attempt limit 10 ต่อ epoch เมื่อเกินให้ exhausted พร้อมเหตุผล operational แต่ไม่แก้ order เป็น rejected Operator เปิดเพิ่มได้ไม่เกินสอง epochด้วย request key เดิมที่ resolve ได้ หาก order จบแล้วให้แสดง already-resolved แทน publish เพื่อทำธุรกิจใหม่

**Process:** parse/auth envelope → begin → lock order → verify canonical event/items → ตรวจ processed result เดิม → lock product rows ตาม SKU → ตรวจทุก SKU พอ → จองทั้งหมด+insert reservations+processed result+terminal order state → commit → ack204 หากสินค้าไม่พอ commit rejected/processed outcome โดยไม่แตะ stock

SQL exception/dependency/lock timeout ต้อง rollback และคืน retryable response ส่วน schema/binding ที่ไม่ถูกต้องไม่ ack แบบ success ต้องแยก poison reason เพื่อส่งต่อ DLT ไม่อ่าน arbitrary table/path จาก event การ commitสำเร็จแต่responseหายปลอดภัยเพราะรอบใหม่ตรวจ immutable binding และ terminal ledgerก่อนทำ stock change

ใช้ row constraints/unique keys/transactions เป็นหลัก ไม่ใช้ check-then-act ใน Pythonอย่างเดียว SQL tests ต้องตรวจ race กับ connections จริงและ stock snapshot ไม่ใช่ดูแค่ HTTP status

### 5. Dead-letter inspect/replay

ใช้ Cloud Shell bounded tool กับ operator session และ subscriber permission เฉพาะ dead-inspect ไม่ให้ Portal ดึง DLQ payload สำหรับลูกค้าทั่วไป เครื่องมือ pull ครั้งละไม่เกิน 5 รายการ ไม่ auto-ack และจำกัดขนาด envelope/nesting/base64 decode ต้อง parse รูปแบบ forwarded message จริงจากเอกสาร/fixtureที่ตรวจแล้ว

ลำดับต่อหนึ่งรายการ:

1. ตรวจ source subscription/digest และ lookup canonical outbox ผ่าน operator API ไม่ใช้ raw payload มาเขียนธุรกิจ
2. บันทึก private journal ของ action key/event/source digest และ audit reference ก่อน prepare replay ไม่มี password/JWT/ack ID ในหลักฐานเผยแพร่
3. ถ้า order accepted ให้ operator API prepare pending epoch เดิมแบบ idempotent รอ Scheduler/dispatcher ส่ง canonical event ไม่รับ payload ที่แก้เอง
4. ถ้าคำตอบหาย ให้ resolve action key เดิมและอ่าน order/outbox/ledger ไม่เปิด epoch ใหม่ ถ้า order confirmed/rejectedอยู่แล้วและbindingตรง ให้บันทึก already-resolved
5. Ack เฉพาะ dead-letter รายการที่ตรวจผล terminal/canonical binding แล้ว ห้าม ack batch ทั้ง subscription หรือถือ publish response เป็นผลธุรกิจ หาก ack token หมดอายุให้ pull/ตรวจรายการเดิมใหม่ ไม่สร้างงานธุรกิจเพิ่ม

การ replay ไม่ลบหรือ seek source subscription ทั้งก้อน และไม่รับประกันว่า deliveryAttempt เท่ากับสิบเป๊ะ ต้องแยก application dispatch budget ออกจาก broker best-effort delivery attempts

Poison fault สำหรับฝึกจะเปลี่ยนเฉพาะ schema version ของ event ที่ระบุใน outbound test path โดย canonical outbox/orderไม่เปลี่ยน เมื่อปิด faultให้ replayจากcanonical versionเดิม มี finite target/event markerและคืนbaselineชัดเจน ไม่เปิดfaultให้ลูกค้าเลือกจากAPI

### 6. Connection budget และการเปลี่ยน capacity

ใช้หนึ่ง process ต่อ container, pool overflow=0, pool size Portal2/worker2/dispatcher1, bootstrap1 ตั้ง connect/pool wait/statement/lock timeout แบบจำกัด และใช้ transaction สั้น ไม่มี network I/O ขณะถือ product locks

Change จาก worker1→3 โดยคง concurrency1/pool2 ที่เหลือเดิม สมมติฐาน rollout สอง revision พร้อมกันให้ budget Portal4×2 +worker6×2 +dispatcher2×1 +bootstrap1 =23 connections; เผื่อ inspection/maintenanceอย่างน้อย7และheadroomเพิ่มเติม ไม่อ้างว่า Cloud Run max instances เป็น hard DB connection cap

ตั้ง DB role connection limits ตาม budget: API8/worker12/dispatcher2/bootstrap1 และตรวจ DB actual max_connections/ผู้ใช้ระบบก่อนเริ่ม หาก Cloud Run transient burst/หลายrevisionเกินแผน DBอาจปฏิเสธ connection ต้องเกิด bounded error/backoffไม่สร้างผลซ้ำ ไม่รับประกัน zero errorsระหว่างrollout

ฐาน DBไม่autoscaleตามQueueจึงต้องเทียบ stock correctness/Queue age/DBlocks/connectionsร่วมกัน ไม่เพิ่มpublisherหรือใช้blindloadจนquotaเต็มเพื่อทำให้กราฟสวย

### 7. Test matrix และลำดับ Materials

| ชั้น | สิ่งที่ต้องตรวจจริง |
|---|---|
| Domain/protocol | exact input/schema/fingerprint/integer bounds; duplicate JSON/base64/body limits; owner/binding; safe reasons |
| PostgreSQL16 | create/replay/conflict, concurrent LAST-01 race, all-or-nothing multi-item, duplicate/new message IDs, commit-before-ack recovery, stale publish token, ambiguous publish/reclaim, exhausted/redrive/action idempotency และ DB grants |
| HTTP/browser | real Portal login/catalog/order/status/unknown-create resolution; bob404/operator403/CSRF; queue transport/signing doubles ติดป้ายชัด |
| SDK contracts | real installed Pub/Sub publisher/Cloud SQL connector APIs, timeout/retry/IP/TLS contracts; no paid cloud calls |
| Containers/IaC | explicit roles/Secrets/image digest, non-root/exclusions, Terraform fmt/init-backendfalse/validate, bootstrap no-reset |
| Guide/diagrams | commands parse, links/Taskcoverage, real-width render/visual review, R1–R9evidence, bounded fault/backout/cost/cleanup |

ลำดับทำ: domain/event contractsและfixtures → SQLschema/roles/transactionsกับrealDBtests → outboxclaim/publisher/worker → HTTP/runtime/Secrets/bootstrap → browser+operatorDLQtools → Terraform → diagrams → Tasksพร้อมrecords/runbook/change/cleanup → self-review/Guide-ready แต่ละชั้นต้องแก้ข้อผิดพลาดที่ตรวจได้ก่อนเพิ่มชั้นถัดไป

แผน Tasks จะเริ่มproject/budget/private state → foundation/privateDB → privatecredentials/bootstrap → images/services/queue/schedule → business/owner/stock tests → outbox/push/crash/DLQ faults → throughput change → evidence/cleanup/rebuild ไม่เขียนผล Cloud PASS ล่วงหน้า

### 8. Deployment และ cleanup boundaries

แยก Terraform foundation (APIs/VPC/PSA/SQL/Secretcontainers/SAs/AR), bootstrap (one-off DB installation job) และ workloads (services/topics/subscriptions/identitybindings/Scheduler) เพื่อให้แต่ละเฟสมีค่าที่ต้องใช้และreviewก่อนเปิดtraffic Schema/Secretpayloadอยู่นอกTerraformstate

Bootstrap Jobล้มต้องวินิจฉัย/รันซ้ำแบบไม่reset ไม่แก้roleหรือseedผ่านPortal ส่วน runtime migrationsไม่ทำตอนรับrequesthealth

Cleanupต้องpauseScheduler/หยุดordersและdispatcherก่อน, resolveoutbox/DLQ/unknownoutcomeและเก็บsanitizedsnapshots, ลบworkloads/Queueหลังตัดสินใจเรื่องข้อมูล, ปลดDBprotectionด้วยreviewedplan, ตรวจbackups/retention/images/Secrets/SA/IAM/PSAและnetworkที่เหลือ ไม่ลบproject/sharedAPI/backendหรือdefaultDBของงานอื่น

SQLbackup retentionไม่ใช่การรับประกันrestoreที่ทดลองแล้ว และ rebuild seedไม่ใช่คืนorders/ledgerที่ลบ ต้องระบุสิ่งที่ยังเก็บและค่าใช้จ่ายที่อาจตามหลังinventory

### แหล่งอ้างอิง Design

- [Cloud SQL Python Connector: private IP/TLS/pg8000 และ refresh strategy](https://github.com/GoogleCloudPlatform/cloud-sql-python-connector)
- [Pub/Sub authenticated push และ service agent](https://docs.cloud.google.com/pubsub/docs/authenticate-push-subscriptions)
- [Cloud Scheduler HTTP target authentication](https://docs.cloud.google.com/scheduler/docs/http-target-auth)
- [Cloud Run scheduled invocation](https://docs.cloud.google.com/run/docs/triggering/using-scheduler)

**Design checkpoint:** นี่คือสัญญาที่ Materials ต้องทำให้เป็นจริง ยังไม่มีApp/schema/infraสำเร็จหรือผล GCP ขั้นถัดไปเริ่มdomain+SQLtestsตามลำดับข้างต้น หากSDK/providerมีข้อจำกัดให้ปรับDesignพร้อมเหตุผลก่อนเขียนTask
