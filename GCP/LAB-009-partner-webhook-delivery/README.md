---
lab: LAB-009
platform: GCP
phase: build-materials
guide_status: authoring
cloud_verification: not-run
last_verified: null
---
# Lab 09 — ระบบส่ง Webhook ให้ระบบคู่ค้า

**สถานะ:** Build materials in progress — Design ถูกปิดแล้ว. มี domain/API/ledger, Cloud Tasks/Reconciler, fenced Worker, HMAC simulator, create-only receipt, strict runtime composition, shared non-root container, Terraform root แบบ foundation/workload gate และ Operator CLI สำหรับตรวจ/receipt/redrive พร้อม audit. คู่มือ Tasks 00–12 ยังอยู่ระหว่างเขียนและทดสอบ. ไม่มี GCP provisioning และ Cloud verification ยังคง Not run.

## สถานการณ์

ระบบ Order ภายในต้องแจ้ง event ประเภท order.shipped ไปยัง endpoint ของคู่ค้าหลายราย แต่ปลายทางอาจช้า ตอบ 429/5xx หรือรับ event ไปแล้วแต่คำตอบกลับหาย ทีมต้องตอบผู้เรียกได้เร็ว ติดตามผลส่งย้อนหลังได้ และ redrive ได้โดยไม่ทำให้คู่ค้าเกิดผลทางธุรกิจซ้ำ

ใช้ข้อมูลสังเคราะห์และ partner simulator เท่านั้น ไม่เชื่อมระบบคู่ค้าจริง ไม่ส่ง PII หรือ credential และไม่อ้าง SLA ของ production.

## ผู้ใช้และผลลัพธ์

- **ทีมผู้ส่ง Event:** ส่ง event ที่ผ่าน schema และได้ event ID กลับ แม้คู่ค้ายังไม่พร้อม
- **Operator:** ตรวจสถานะและเหตุผลของ delivery แยกงานที่ retry อยู่จากงานที่ต้องตรวจสอบ และสั่ง redrive พร้อมเหตุผลได้
- **ทีม Platform/Security:** จำกัดผู้เรียกด้วย Cloud Run IAM แยก identity ของ workload และไม่ใส่ secret ใน log
- **Partner simulator:** ตรวจ HMAC จาก raw body และ timestamp ปฏิเสธข้อมูลที่ถูกแก้ไข และบันทึก event ID เพื่อ deduplicate

## Requirements และเกณฑ์รับมอบเบื้องต้น

| ID | Requirement | หลักฐานที่ต้องเก็บใน Guide |
|---|---|---|
| R1 | Event API รับ event สังเคราะห์ตาม schema/เพดานที่กำหนด และตอบรับเมื่อบันทึกเจตนาส่งอย่างถาวรแล้ว | request ID, event ID, response code, Firestore event/outbox record และขนาดข้อมูล |
| R2 | idempotency key เดิมกับ body เดิมคืน event ID/ผลเดิม; key เดิมแต่ body ต่างกันถูกปฏิเสธด้วย 409 | ผลเรียกซ้ำสองกรณี, payload hash และ ledger |
| R3 | การบันทึก event/outbox และการสร้าง task เป็นคนละระบบ; กู้กรณี process หยุดระหว่างสองขั้นได้ | จำลอง enqueue error, outbox ก่อน/หลัง reconcile, task name/generation และผล API |
| R4 | Cloud Tasks เรียก Delivery Worker ด้วย OIDC; Cloud Run IAM/ingress อนุญาตเฉพาะเส้นทางและ identity ที่กำหนด | authorized/unauthorized call, audience, IAM binding และ ingress setting |
| R5 | Worker ลงนามด้วย HMAC-SHA256 จาก timestamp และ raw body; simulator ตรวจลายเซ็น, freshness และ body ที่ถูกแก้ไข | positive/negative cases, event ID และ verdict; ไม่เก็บ secret/signature เต็มใน log |
| R6 | timeout, 408, 429 และ 5xx เป็น transient ตามนโยบาย; permanent 4xx ถูกบันทึกก่อนหยุด retry | attempt log, status classification, retry/backoff และ Firestore transition |
| R7 | กรณี partner รับสำเร็จแต่ response หายและ Cloud Tasks ส่งซ้ำไม่เกิดผลธุรกิจซ้ำ; retry ใช้ event ID/payload เดิม | receiver receipt, payload hash, task metadata และผล dedupe |
| R8 | retry exhaustion หรือ delivery ที่ยืนยันผลไม่ได้ยังตรวจย้อนหลังได้; redrive บันทึก actor, reason และ generation ใหม่ | ledger, queue/log evidence, partner receipt lookup, redrive audit และผลหลัง redrive |
| R9 | Change Request เพิ่ม partner รายที่สองด้วย queue rate limit และ HMAC key แยก; ไม่มี cross-partner leakage | Terraform plan, queue settings สองชุด, IAM/secret binding และ isolation tests |
| R10 | มี runbook สำหรับตรวจ incident, เปลี่ยนค่า, rebuild และ cleanup อย่างปลอดภัย | Expected/Actual/Evidence แยกกัน, resource inventory, cleanup result และ Cloud verification status |

เกณฑ์เหล่านี้เป็นสิ่งที่ผู้เรียนต้องพิสูจน์ใน Lab ไม่ใช่คำอ้างว่าได้รัน Cloud แล้ว. ตัวอย่างผลที่คาดหวังต้องติดป้าย Expected; Actual และหลักฐานให้กรอกหลังรันจริง.

## ขอบเขตตั้งต้น

- Event type เดียว: order.shipped; payload สังเคราะห์มี event ID, partner ID, เวลาเกิดเหตุ, order reference ปลอม และสถานะจัดส่ง ไม่มีชื่อ ที่อยู่ เบอร์โทร หรือข้อมูลชำระเงิน
- จำกัด payload, field count, string length และ event rate สำหรับ Lab; ตัวเลขสุดท้ายยืนยันใน Design พร้อม quota/cost check.
- Baseline มี partner simulator หนึ่งราย; Change Request เพิ่มรายที่สอง พร้อม queue rate และ secret แยก.
- Stack ที่เลือก: Cloud Run แยก Event API, Reconciler, Delivery Worker และ simulator; Operator ใช้ CLI ใน Cloud Shell; Cloud Tasks แยก queue ต่อ partner; Firestore เป็น durable event/outbox/delivery ledger; Cloud Scheduler เรียก Reconciler; Secret Manager เก็บ HMAC keys; Cloud Storage เก็บ durable receipt แบบ create-only.
- Event API และ Reconciler ต้องผ่าน IAM authentication; Worker รับ traffic จาก Cloud Tasks ด้วย OIDC และจำกัด ingress เมื่อยืนยัน topology แล้ว. Partner simulator เป็น HTTPS endpoint สาธารณะเพื่อเลียนแบบ dependency ภายนอก แต่รับเฉพาะข้อมูลสังเคราะห์และตรวจ HMAC.
- ผู้เรียนใช้ gcloud CLI และ Terraform บน project เฉพาะ Lab. เอกสารนี้ไม่สร้าง GCP resources.

## Solution flow

1. Producer ส่ง order.shipped พร้อม idempotency key ไปยัง Event API ที่ผ่าน Google IAM authentication.
2. API ตรวจ schema/ขนาด สร้าง payload hash และเขียน event กับ outbox record ใน Firestore transaction. API ตอบ 202 พร้อม event ID เมื่อบันทึก intent แล้ว; 202 ไม่ได้แปลว่าคู่ค้ารับ event แล้ว.
3. API พยายามสร้าง Cloud Task ใน queue ของ partner. หาก enqueue ไม่สำเร็จ outbox ยังคงอยู่; Reconciler ที่ Scheduler เรียกด้วย OIDC ค้นหา pending item แล้วซ่อมการ enqueue.
4. Cloud Tasks ส่งเฉพาะ event ID, delivery ID, partner ID และ generation ไปยัง Worker ผ่าน OIDC; Worker อ่าน payload canonical จาก ledger ไม่เชื่อ URL/secret ที่ผู้ส่งแนบมา.
5. Worker เลือก endpoint จาก partner allowlist, อ่าน HMAC key จาก Secret Manager, สร้าง timestamp/signature ใหม่ต่อ attempt แล้ว POST ผ่าน HTTPS. Event ID เป็น idempotency key คงที่ตลอด retries.
6. Simulator ตรวจ HMAC แบบ constant-time และ freshness แล้วบันทึก receipt ที่ผูก event ID กับ payload hash. การเขียน receipt ใช้ Cloud Storage generation precondition เพื่อกัน overwrite; ถ้าชน receipt เดิมต้องอ่านและเทียบ hash ก่อนยืนยันว่าเป็น duplicate เดิม.
7. Worker บันทึก attempt/terminal state ก่อนตอบ 2xx ให้ Cloud Tasks. Transient failure ตอบ non-2xx เพื่อให้ retry; permanent rejection ต้องบันทึก terminal state ก่อน acknowledge.
8. Operator ใช้ CLI ใน Cloud Shell ตรวจ ledger, task metadata, logs และ partner receipt ก่อน redrive. Redrive บันทึก actor/reason, เพิ่ม generation และตั้ง delivery กลับเป็น enqueue_pending; event ID/payload เดิมยังคงเดิมเพื่อให้ receiver deduplicate หากผลการส่งก่อนหน้าคลุมเครือ.

## Reliability constraints ที่ต้องคงไว้ใน implementation

- Cloud Tasks มี delivery แบบ at-least-once; Worker และ simulator จึงต้อง idempotent. ชื่อ task ช่วย dedupe ได้สูงสุด 24 ชั่วโมงหลัง task ถูกลบ ไม่ใช่ business idempotency ถาวร. Firestore ledger และ receiver receipt เป็นหลักฐานระยะยาว. [Cloud Tasks overview](https://docs.cloud.google.com/tasks/docs/dual-overview) · [task-name deduplication limit](https://docs.cloud.google.com/tasks/docs/quotas)
- Cloud Tasks ลบ task หลังสำเร็จหรือ retry หมด; task ที่ไม่อยู่ใน queue ไม่ใช่หลักฐานว่าคู่ค้ารับข้อมูล. หาก Worker ไม่เคยได้ attempt สุดท้าย ให้แสดง unknown/needs-review และให้ Operator ตรวจ ledger, queue/log และ partner receipt ก่อน redrive. [Manage queues and tasks](https://docs.cloud.google.com/tasks/docs/manage-queues-and-tasks)
- max attempts นับรวม attempt แรก; retry policy หยุดเมื่อทั้งจำนวน attempt และ retry duration ครบตามเงื่อนไข. Rate limit เป็นค่าต่อ queue และรวม first attempt กับ retry; Cloud Tasks อาจลด dispatch rate เพิ่มเมื่อปลายทางตอบ 429/503/5xx. ห้ามอ้างเวลา/throughput ที่ยังไม่ได้วัด. [queue rate/retry configuration](https://docs.cloud.google.com/tasks/docs/configuring-queues) · [retry behavior](https://docs.cloud.google.com/tasks/docs/common-pitfalls)
- Header X-CloudTasks-TaskRetryCount อาจนับ dispatch ที่ล้มก่อนถึง handler; X-CloudTasks-TaskExecutionCount นับคำตอบจาก handler. ใช้ร่วมกับ delivery attempt ledger ไม่ใช่แทนกัน. [HTTP target headers](https://docs.cloud.google.com/tasks/docs/creating-http-target-tasks)
- Cloud Tasks ใช้ OIDC กับ HTTP targets ได้; service account ที่สร้าง token ต้องอยู่ project เดียวกับ queue. ต้องแยก iam.serviceAccounts.actAs, Cloud Tasks service agent และ Cloud Run Invoker ตาม principal. Cloud Run internal ingress รู้จัก Cloud Tasks เมื่ออยู่ project/perimeter เดียวกันและใช้ default run.app URL; ต้องยืนยันกับ topology จริงก่อนเลือก. [HTTP target authentication](https://docs.cloud.google.com/tasks/docs/creating-http-target-tasks) · [Cloud Run ingress](https://docs.cloud.google.com/run/docs/securing/ingress)
- HMAC-SHA256 ใช้ยืนยันความถูกต้อง/ผู้ถือ shared secret ไม่ได้ปกปิดข้อมูล; HTTPS ยังจำเป็น. [RFC 2104](https://www.rfc-editor.org/rfc/rfc2104/)
- generation-match 0 ทำให้ Cloud Storage สร้าง object ได้เมื่อไม่มี live object ชื่อนั้น. หากชน object เดิม ต้องอ่านและเทียบ hash ไม่ถือว่า payload ซ้ำที่ถูกต้องทันที. [Cloud Storage request preconditions](https://docs.cloud.google.com/storage/docs/request-preconditions)

## Design — architecture และ decisions ที่ปิดแล้ว

![Topology ของ Partner Webhook Relay](assets/solution.svg)

![State, retry และ recovery flow](assets/delivery-flow.svg)

### Resource map และตำแหน่ง

ใช้ asia-southeast1 (Singapore) ใน project สำหรับ Cloud Run, Cloud Tasks, Firestore Native, Cloud Scheduler และ Cloud Storage เพื่อให้บริการหลักอยู่ใน region เดียวกัน. Cloud Scheduler มี Bangkok แล้ว แต่ Cloud Tasks ยังไม่แสดง asia-southeast3 ในรายการ region จึงเลือก Singapore เป็น common region สำหรับ solution นี้; Secret Manager ใช้ global API โดยกำหนด user-managed replication ไว้ Singapore. ตรวจ region ซ้ำก่อนเริ่ม เพราะความพร้อมและราคาอาจเปลี่ยนได้.

| Resource | ขอบเขตและหน้าที่ |
|---|---|
| Event API | Cloud Run, ingress all แต่บังคับ Cloud Run IAM; ตรวจ schema, ทำ idempotency และบันทึก event/outbox ก่อนตอบ 202 |
| Operations CLI | รันจาก Cloud Shell ด้วย IAM ของผู้ปฏิบัติการ; อ่านสถานะ/receipt และทำ redrive transaction โดยไม่เปิด admin endpoint สาธารณะเพิ่ม |
| Reconciler | Cloud Run internal + IAM; Cloud Scheduler เรียกทุก 1 นาทีผ่าน default run.app URL; ทำงานสูงสุด 25 records ต่อรอบ |
| Cloud Tasks | HTTP target queue หนึ่งชุดต่อ partner; task มีเฉพาะ IDs/generation และ OIDC identity |
| Delivery Worker | Cloud Run internal + IAM; claim lease, อ่าน payload/secret, ส่ง HTTPS+HMAC และบันทึก attempt/state ก่อน acknowledge |
| Partner Simulator | Cloud Run public test endpoint เพื่อจำลอง partner ภายนอก; รับ synthetic data เท่านั้น, บังคับ HMAC ในแอป |
| Firestore | Regional Native-mode database; เก็บ idempotency, event payload, delivery/outbox state, attempt history และ redrive audit |
| Secret Manager | key แยกราย partner; user-managed replication เฉพาะ asia-southeast1; ห้ามพิมพ์ secret/signature ลง output |
| Cloud Storage | bucket private แยกราย partner; simulator เขียน receipt แบบ create-only และอ่านเพื่อตรวจ duplicate |

Cloud Run สำหรับ Event API และ Cloud Shell client ใช้ ingress all เพราะผู้เรียนเรียกจากภายนอก VPC แต่ยังต้องผ่าน IAM; Reconciler/Worker ใช้ internal ingress และ IAM โดยใช้ default run.app URL. เอกสาร Cloud Run ระบุ Cloud Tasks และ Cloud Scheduler ใน project/perimeter เดียวกันเป็น internal source ได้. Simulator เป็นข้อยกเว้นเดียวที่ public เพราะเลียนแบบปลายทาง partner; ไม่ใช้ข้อมูลจริงและต้องคง HMAC check แม้ Cloud Run IAM จะปิดสำหรับ endpoint นี้.

### Event, idempotency และ durable model

- API รับ event type เดียว order.shipped และ partner_id จาก allowlist เท่านั้น. ผู้เรียกส่ง order_ref สังเคราะห์ตามรูปแบบ ORD- ตามด้วยอักขระ A–Z/0–9 จำนวนคงที่, occurred_at แบบ RFC3339 UTC และ shipping_status ที่ต้องเป็น shipped; server สร้าง event_id และ accepted_at เอง. ห้ามรับ URL, secret name หรือ callback host จาก producer.
- จำกัด request body ไม่เกิน 8 KiB, string/field ตาม schema และไม่เก็บ PII. Canonical body สร้างจาก field allowlist ที่ normalize แล้ว, sort key, compact JSON UTF-8; ไม่มี float. payload_sha256 คำนวณจาก byte sequence นี้ และ Worker ส่ง byte sequence เดิมทุก generation.
- Idempotency-Key เป็น required opaque value ขนาดจำกัด; เก็บเฉพาะ SHA-256 ของ key เป็น document ID. ขอบเขต uniqueness คือ project ของ Lab. key เดิม + payload hash เดิมคืน event_id/delivery เดิม; key เดิม + hash ต่างกันคืน 409. ไม่ใช้ key ดิบเป็น log field.
- Firestore transaction เดียวสร้าง events/{event_id}, idempotency/{key_hash} และ deliveries/{delivery_id} ในสถานะ enqueue_pending. Delivery document เป็น outbox และ state machine เดียวกัน; attempts เป็น immutable subcollection และ redrive audit เก็บเป็น records แยก. Lab เก็บหลักฐานไว้จน cleanup; ไม่ตั้ง TTL ที่อาจลบ record ระหว่าง task/receipt ยังต้องตรวจ.
- Cloud Tasks body มี event_id, delivery_id, partner_id และ generation เท่านั้น. ชื่อ task deterministic จาก delivery_id + generation; endpoint และ Secret ID มาจาก Terraform-controlled partner allowlist. API ตอบ 202 หลัง transaction สำเร็จ ไม่รอ partner; ถ้า Firestore ล้มเหลวตอบ error และไม่สร้าง task.

### State machine และการซ่อม outbox

| สถานะ | ความหมาย / การเปลี่ยน |
|---|---|
| enqueue_pending | มี durable event+delivery แล้ว แต่ยังไม่มี task ที่ยืนยันได้; API ลอง CreateTask ทันทีและ Reconciler ทำซ้ำแบบ deterministic |
| queued | CreateTask สำเร็จหรือ GetTask ยืนยันว่ามี task; ครอบคลุมช่วงรอและ retry |
| attempt_running | Worker claim ด้วย Firestore transaction, บันทึก generation/attempt number และ lease/fencing token ก่อนเรียก partner |
| delivered | simulator ตอบ 2xx และ Worker commit terminal state/attempt สำเร็จแล้ว จึงตอบ 2xx ให้ Cloud Tasks |
| permanent_failed | partner ตอบ 4xx ที่ไม่ใช่ 408/429; บันทึกเหตุผลก่อน Worker ตอบ 2xx เพื่อหยุด poison retry |
| retry_ended_unknown | Reconciler พบ GetTask NOT_FOUND แต่ delivery ยัง nonterminal; อาจเป็น retry exhaustion, การลบ หรือผลสำเร็จที่ ledger commit ไม่ครบ จึงห้ามตีความว่า partner ไม่ได้รับ |
| redrive | Operator ตรวจ logs/task/receipt แล้ว transaction เพิ่ม generation, เขียน actor/reason/evidence reference และตั้ง enqueue_pending; payload/event_id คงเดิม |

API fast path และ Reconciler ห้ามเขียนทับสถานะที่ Worker ทำให้ก้าวหน้าแล้ว: หลัง CreateTask สำเร็จ จะเปลี่ยนเป็น queued ได้เฉพาะเมื่อสถานะยังเป็น enqueue_pending. หาก CreateTask ตอบ AlreadyExists ให้ GetTask ชื่อเดิม; ถ้ามี task ให้คง generation เดิม, ถ้า NOT_FOUND แต่ ledger ยัง nonterminal ให้ตั้ง retry_ended_unknown เพื่อให้คนตรวจ แทนการสร้างชื่อเดิมซ้ำหลังช่วง dedup. enqueue_pending ที่ค้างเกิน 15 นาทีเข้าคิว needs-review และไม่ auto-enqueue ต่อโดยไม่จำกัด.

Reconciler ทำงานทุกนาทีแบบ bounded page ≤25 และแบ่งหน้าอ่านระหว่าง enqueue_pending, queued และ attempt_running. มันซ่อม pending ล่าสุด, ตรวจ GetTask ของ queued ที่ยัง nonterminal, และตรวจ attempt_running ที่ lease หมดอายุ: ถ้า Cloud Task หายให้เปลี่ยนเป็น retry_ended_unknown แต่ถ้ายังมี task ให้รอ Cloud Tasks retry. Transaction ตรวจ generation/state/lease อีกครั้งก่อนเปลี่ยน; task ที่หายไม่ใช่หลักฐานว่าคู่ค้ารับ event แล้ว. งาน terminal จะไม่ถูก redrive อัตโนมัติ. Cloud Tasks ลบ task หลัง successful response หรือ retry exhaustion; task name กันซ้ำได้เพียงช่วงสั้น จึงไม่ใช่ business idempotency.

Worker ใช้ transaction/lease และ fencing ป้องกัน worker เก่าบันทึกทับ generation ใหม่. Duplicate task ที่พบ lease ยัง active ตอบ non-2xx เพื่อให้ Cloud Tasks ลองใหม่ ไม่ตอบ 2xx แล้วทิ้งงาน. Worker commit delivered/permanent_failed ก่อนตอบ 2xx ให้ Cloud Tasks; หากไม่สามารถบันทึก state ให้ตอบ non-2xx. Reconciler และ Operator ตรวจและแก้ ambiguous outcome; ไม่มี exactly-once claim.

### Retry, webhook signing และ fault scenarios

- Baseline queue ตั้ง maxAttempts=5 (นับ attempt แรก), maxRetryDuration=0s (ไม่จำกัดเวลา แต่ maxAttempts ยังมีผล), minBackoff=5s, maxBackoff=20s, maxDoublings=2, maxDispatchesPerSecond=1 และ maxConcurrentDispatches=1 ต่อ partner. ใช้ไม่เกิน 10 synthetic events ในหนึ่ง run. Queue rate limit ใช้กับ first attempt และ retry; timing/throughput จริงไม่รับประกัน.
- Cloud Tasks retry count อาจรวม 5xx ที่ไม่ถึง handler; execution count บอกจำนวน handler responses. Worker บันทึก outbound attempt number ของตนเองใน Firestore ก่อน POST และใช้ค่านั้นกับ simulator scenario; ห้ามอนุมานจำนวน partner calls จาก Cloud Tasks header เพียงอย่างเดียว.
- Worker timeout 20 วินาที, HTTP dispatch deadline 30 วินาที, partner connect/read timeout 5 วินาที. 408/429/5xx/timeout เป็น transient; สำหรับ 429/503 Worker ส่ง Retry-After ที่ parse ได้กลับไปยัง Cloud Tasks โดยจำกัดค่าสูงสุด 60 วินาที. 4xx อื่นเป็น permanent และต้องแก้ config แล้ว Operator จึงค่อย redrive.
- Signature เป็น HMAC-SHA256 บน UTF-8 bytes ของ canonical string: v1, HTTP method/path, Unix timestamp, generation, outbound attempt number และ raw request body ตามลำดับที่กำหนดคงที่; คั่นด้วย newline. ส่ง timestamp/signature เป็น headers. Simulator ยอมรับ timestamp ภายใน ±300 วินาที, เทียบ MAC แบบ constant-time, และใช้ HTTPS. signature เปลี่ยนทุกรอบ แต่ event_id/body คงเดิม.
- Simulator modes เป็น Terraform-controlled enum เท่านั้น ไม่มี public scenario endpoint และ producer เปลี่ยน fault mode ไม่ได้: normal; transient-503-first-two (attempt 1–2 ตอบ 503, attempt 3 บันทึก receipt/ตอบ 200); permanent-400; accept-then-503-on-first (บันทึก receipt ก่อนตอบ 503 เพื่อจำลอง ambiguous acknowledgement; retry เห็น receipt/hash เดิมแล้วตอบ 200). attempt number อยู่ใน HMAC canonical string จึงใช้เป็น test signal ได้เฉพาะเมื่อ request ลงนามถูกต้อง.
- Receipt object key ผูกกับ partner_id/event_id; create ใช้ ifGenerationMatch=0. ถ้าชน object เดิมให้อ่านและเทียบ payload hash: hash เดิมคือ duplicate ที่ตอบ 2xx แบบเดิม, hash ต่างกันคือ 409 และ incident. Simulator A runtime identity อ่าน/เขียนได้เฉพาะ bucket A; Worker เข้าถึงเฉพาะ secret ที่จำเป็น. Change Request เพิ่ม B พร้อม queue, secret, simulator service account/service และ receipt bucket แยก.

### IAM, trust boundary และการทำงานผู้ปฏิบัติการ

| Principal | สิทธิ์ที่จำเป็น |
|---|---|
| Producer | roles/run.invoker บน Event API เท่านั้น |
| Event API runtime SA | Firestore user; Cloud Tasks enqueuer บน queue ที่เกี่ยวข้อง; iam.serviceAccounts.actAs บน task OIDC SA เพื่อแนบ OIDC token |
| Cloud Scheduler caller SA | roles/run.invoker บน Reconciler; Google-managed Scheduler service agent ใช้ตาม service default |
| Reconciler runtime SA | Firestore user; Cloud Tasks viewer + enqueuer บน queue; actAs บน task OIDC SA |
| Cloud Tasks service agent | roles/iam.serviceAccountUser บน target OIDC SA; target SA ต้องอยู่ project เดียวกับ queue |
| Task OIDC SA | roles/run.invoker บน Delivery Worker เท่านั้น |
| Worker runtime SA | Firestore user; secretAccessor เฉพาะ partner secrets ที่ Worker ต้องใช้ |
| Simulator A runtime SA | secretAccessor เฉพาะ key A; storage.objectCreator และ storage.objectViewer เฉพาะ bucket A; ไม่มีสิทธิ์ลบ receipt |
| Operator ใน Cloud Shell | Firestore user สำหรับ inspect/redrive transaction; Cloud Tasks viewer สำหรับ metadata; objectViewer เฉพาะ receipt buckets; ไม่มี enqueuer หรือ secret access |
| Terraform/bootstrap principal | ใช้เฉพาะการสร้าง APIs/resources/IAM ตาม dedicated Lab project; final role list ต้องผูกกับ resource inventory ใน Guide |

IAM ของ Firestore มาตรฐานเป็นระดับ project/database มากกว่าระดับ collection จึงให้แต่ละ Lab ใช้ dedicated project และแยก service accounts/secret/bucket per partner. Operator script บันทึก account จาก gcloud active configuration, reason ที่บังคับกรอก, generation เดิม/ใหม่ และเวลา; Cloud Audit Logs เป็นหลักฐาน authoritative สำหรับ principal ที่เรียก API. Logs ของแอปบันทึก request/correlation ID, event/delivery/partner ID, generation, attempt number, task name, response class, duration และ state transition เท่านั้น; ห้าม log body, key, access token หรือ HMAC เต็ม.

### Test limits, task order และ cost gate

Cloud Run min instances=0; ตั้ง max instances ตาม role ให้ต่ำ (API/worker/reconciler 2, simulator 1), ใช้ CPU เฉพาะ request และไม่สร้าง load test ไม่จำกัด. Guide-run probe จำกัดไม่เกิน 10 events ต่อรอบ, 8 KiB/event, หนึ่ง partner, สูงสุด 5 Cloud Tasks attempts; Change Request ทดสอบ partner B แบบแยก queue. ตัวเลข 10 events เป็นขอบเขตของ guide/probe ไม่ใช่ project-level quota; ตั้ง budget alert แต่จำไว้ว่า alert ไม่ใช่ spending cap; ก่อน apply ผู้เรียนประเมิน Singapore region, Artifact Registry/Cloud Build, Cloud Run, Firestore ops, Tasks, Scheduler, Secret Manager, Storage, egress และ logs ใน Pricing Calculator. ไม่มีการ provision โดยผู้จัดทำ.

Build Materials จะทำตามลำดับนี้ก่อนเขียนคู่มือ Task:
1. ล็อก schema vectors, payload canonicalization, response codes และ idempotency contract.
2. ทำ state/Firestore domain module พร้อม lease, fencing, generation และ attempt ledger.
3. ทำ Event API, Operator CLI และ Reconciler/Cloud Tasks adapters พร้อม unit tests.
4. ทำ HMAC signer/verifier, partner simulator, fault modes และ create-only receipt store.
5. ทำ Docker image/health endpoints/structured logs และ bounded probes.
6. ทำ Terraform foundation/workload switch ใน root เดียว: apply foundation เพื่อ APIs, identities, Firestore, queues, buckets, secrets และ Artifact Registry; build/push image; จากนั้นเปิด workload phase เพื่อสร้าง Cloud Run/Scheduler โดยใช้ digest ไม่ใช้ mutable tag.
7. ทดสอบ service doubles/emulator และ fault matrix โดยไม่มี cloud credentials; ระบุส่วนที่ emulator/double ไม่พิสูจน์.
8. เขียน README Tasks 00–12 พร้อม Expected/Actual/Evidence ใกล้จุดตรวจ, change request partner B, troubleshoot, cleanup และ rebuild.
9. CI/render/review ทั้ง artifacts ก่อนย้าย Lab09 ไป Guide-ready; Cloud status ยังคง Not run จนกว่าจะทดสอบใน project จริง.

## คู่มือปฏิบัติการ — จาก Event ถึง Webhook ที่ตรวจสอบย้อนหลังได้

คู่มือนี้สร้างระบบสังเคราะห์ใน project เฉพาะ Lab ด้วย Terraform และ Cloud Shell ตาม diagram ด้านบน ทุกผล Cloud ที่เกิดจากการทำตามคู่มือต้องบันทึกเป็น Actual ของผู้เรียนเอง ส่วนตัวอย่างในข้อความนี้คือ Expected เท่านั้น

### Task 00 — ตั้ง Sandbox, ยืนยันตัวตน และผ่าน Cost Gate

1. สร้างหรือเลือก Google Cloud project เฉพาะสำหรับ Lab 09 ที่เปิด Billing แล้ว ห้ามใช้ Production project หรือ project ที่มี Firestore default database/ทรัพยากรของทีมอื่น เพราะ Lab ใช้ Firestore database ชื่อ (default) และ Terraform จะจัดการ IAM ระดับ project
2. ใน Google Cloud Console เลือก project นั้น แล้วเปิด Cloud Shell จากปุ่ม Activate Cloud Shell
3. ตรวจ active account และตั้ง project ให้ตรงกัน:

```bash
gcloud auth list
export PROJECT_ID="ใส่-project-id-จริง"
export REGION="asia-southeast1"
gcloud config set project "$PROJECT_ID"
gcloud config get-value project
docker version
terraform version
```

ถ้า Cloud Shell ยังไม่มี Terraform ให้ติดตั้งรุ่นเดียวกับ CI และตรวจ checksum ก่อน:

```bash
sudo apt-get update && sudo apt-get install -y unzip
curl -fsSLO "https://releases.hashicorp.com/terraform/1.9.8/terraform_1.9.8_linux_amd64.zip"
curl -fsSLO "https://releases.hashicorp.com/terraform/1.9.8/terraform_1.9.8_SHA256SUMS"
grep "terraform_1.9.8_linux_amd64.zip" terraform_1.9.8_SHA256SUMS | sha256sum -c -
sudo unzip -o terraform_1.9.8_linux_amd64.zip -d /usr/local/bin
terraform version
```

Cloud Shell มี Docker และ gcloud CLI; หากคำสั่ง docker ใช้งานไม่ได้ ให้หยุดและแก้สภาพแวดล้อมก่อนเริ่ม build.

4. เปิด Billing → Budgets & alerts แล้วตรวจว่ามี budget alert ที่เหมาะกับ project. Alert ไม่ใช่ spending cap. ประเมินค่าใช้จ่ายตาม region และจำนวนรอบใน Google Cloud Pricing Calculator ก่อนสร้าง resources. Lab จำกัดการส่งไว้ไม่เกิน 10 synthetic events ต่อ run และไม่ทำ load test.
5. ยืนยันว่าผู้รัน Terraform มีสิทธิ์เปิด API, สร้าง Cloud Run/Firestore/Cloud Tasks/Storage/Secret Manager/Scheduler/Artifact Registry และตั้ง project IAM. สำหรับ project ทดลองที่แยกขาด ให้ใช้ผู้ดูแล project ตามนโยบายของคุณ; อย่าให้สิทธิ์เพิ่มที่ Organization หรือ folder เพื่อให้ Lab ผ่าน. หากองค์กรห้าม public Cloud Run invoker, อย่าปรับ Org Policy เอง ให้ขอ project ที่อนุญาตสำหรับ sandbox.

**Expected:** active project ตรงกับ project สำหรับ Lab, Billing เปิดอยู่, region เป็น asia-southeast1, และไม่มีข้อมูลหรือ database ของงานจริงใน project นี้.

**Actual / Status / UTC:** ______  
**Evidence:** ______ (เก็บ project ID, account แบบปกปิดบางส่วน, ผล Cost Gate และชื่อภาพหน้าจอ; ห้ามเก็บ token)

### Task 01 — รับ Source และเตรียมค่า Terraform ที่ไม่ใช่ความลับ

1. Clone branch ของ Lab และเข้าโฟลเดอร์ solution:

```bash
git clone --branch docs/gcp-solution-labs https://github.com/somkid-s5/Portfolio-Lab.git
cd Portfolio-Lab/GCP/LAB-009-partner-webhook-delivery
```

2. สร้าง virtual environment สำหรับ Operator CLI และติดตั้ง dependencies ที่ pin ไว้:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

3. เปิด Cloud Resource Manager และ Service Usage API ซึ่ง Terraform ต้องใช้เพื่ออ่าน project/เปิด API ที่เหลือ:

```bash
gcloud services enable serviceusage.googleapis.com cloudresourcemanager.googleapis.com --project "$PROJECT_ID"
```

4. เตรียมไฟล์ค่าที่ถูก ignore จาก Git แล้วแก้เฉพาะค่าตัวอย่างที่ระบุ:

```bash
cp infra/terraform.tfvars.example infra/terraform.tfvars
openssl rand -hex 4
gcloud auth list --filter=status:ACTIVE --format="value(account)"
nano infra/terraform.tfvars
```

ใน nano ให้ใส่ project ID จริง, bucket_suffix เป็นค่าจาก openssl จำนวน 8 ตัวอักษร/ตัวเลข, และ operator_member/producer_member เป็น principal ของผู้ใช้ที่กำลังทำ Lab เช่น user:อีเมลของคุณ. คง region, partner-a, fault_mode transient-503-first-two, secret_version 1, enable_workloads=false, pause_scheduler=true และ allow_destroy=false. บันทึกด้วย Ctrl+O, Enter, ออกจาก nano ด้วย Ctrl+X. ห้ามใส่ secret/HMAC key ในไฟล์นี้ และห้าม commit terraform.tfvars หรือ terraform.tfstate.

5. ตรวจรูปแบบ/ความถูกต้องและดูแผนก่อนสร้าง:

```bash
terraform -chdir=infra init
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra validate
terraform -chdir=infra plan -out=foundation.tfplan
terraform -chdir=infra show foundation.tfplan
```

อ่านแผน resource ต่อ resource. ขั้นแรกควรมี API/IAM, Firestore (default), queue, Secret metadata, private receipt bucket และ Artifact Registry; ต้องยังไม่มี Cloud Run services หรือ Scheduler job เพราะ enable_workloads=false. ถ้าเห็น resource ที่ไม่รู้จักหรือ project ID ผิด ให้หยุดก่อน apply.

ทุกครั้งที่คู่มือให้แก้ค่าใน tfvars ให้ใช้ขั้นตอนเดียวกันนี้หลังแก้ไฟล์: ทำ plan, อ่าน diff, แล้ว apply เฉพาะ plan ที่ตรวจแล้ว. ถ้าเปิด Cloud Shell session ใหม่ ให้ตั้ง PROJECT_ID/REGION ใหม่ และอ่าน EVENT_URL/RECEIPT_BUCKET/REPOSITORY จาก Terraform output อีกครั้ง.

```bash
terraform -chdir=infra plan -out=change.tfplan
terraform -chdir=infra show change.tfplan
terraform -chdir=infra apply -input=false change.tfplan
```

**Expected:** Terraform validate ผ่าน; plan แสดง foundation เท่านั้นและไม่แสดงการอ่าน/สร้าง secret value. ไฟล์ tfvars และ state ไม่อยู่ใน git status.

**Actual / Status / UTC:** ______  
**Evidence:** ______ (Terraform version, plan summary และ git status ที่ไม่แสดงไฟล์ลับ)

### Task 02 — สร้าง Foundation และตรวจขอบเขตทรัพยากร

เมื่ออ่าน plan จบและยืนยัน project/ค่าใช้จ่ายแล้ว จึง apply แผน foundation:

```bash
terraform -chdir=infra apply -input=false foundation.tfplan
terraform -chdir=infra output
gcloud firestore databases describe --database="(default)" --project "$PROJECT_ID"
gcloud tasks queues describe partner-a --location "$REGION" --project "$PROJECT_ID"
```

เปิด Console ตรวจ Cloud Tasks → Queues, Firestore → Databases, Secret Manager → Secrets, Cloud Storage → Buckets และ Artifact Registry → Repositories. ตรวจว่า bucket เป็น private/public access prevention enforced และ bucket แยกตาม partner. เก็บรายการ resource name/region ไว้เป็น inventory; อย่าถ่ายหรือเผยแพร่หน้า IAM ที่แสดงอีเมลเต็มโดยไม่จำเป็น.

**Expected:** Firestore เป็น Native mode ใน region ที่ออกแบบ, queue partner-a มี max dispatch/concurrency 1 และ maxAttempts 5, และยังไม่มี Cloud Run/Scheduler workload. Terraform output แสดงชื่อ secret/bucket และ service accounts เท่านั้น.

**Actual / Status / UTC:** ______  
**Evidence:** ______ (plan/apply summary, resource inventory และภาพหน้าจอที่ redact แล้ว)

### Task 03 — เพิ่ม HMAC key สังเคราะห์โดยไม่ส่งผ่าน Terraform

สร้าง key สำหรับ partner-a ใน Cloud Shell. คำสั่งนี้ไม่พิมพ์ค่าลับบนหน้าจอ:

```bash
umask 077
HMAC_FILE="$(mktemp)"
openssl rand -out "$HMAC_FILE" 48
gcloud secrets versions add lab009-partner-a-hmac --project "$PROJECT_ID" --data-file="$HMAC_FILE"
rm -f "$HMAC_FILE"
unset HMAC_FILE
gcloud secrets versions list lab009-partner-a-hmac --project "$PROJECT_ID" --format="table(name,state)"
```

ตรวจจาก metadata ว่ามี version ENABLED. ค่าเริ่มต้นใน tfvars pin version 1; ถ้าคุณเคยเพิ่ม version ไว้ก่อนแล้ว ให้แก้ secret_version เป็นหมายเลข version ที่ต้องการใช้ก่อน deploy. ห้ามใช้ --data-file=- กับ string ที่พิมพ์ลง command line, ห้าม cat/read ค่า secret, และห้ามบันทึกค่า key ลงหลักฐาน.

**Expected:** Secret มี numbered version ที่ ENABLED; output แสดงชื่อ/สถานะ version ได้ แต่ไม่แสดง secret bytes.

**Actual / Status / UTC:** ______  
**Evidence:** ______ (เฉพาะชื่อ secret, หมายเลข version และ state; ไม่เก็บค่า secret)

### Task 04 — Build image, pin digest และเปิด Workloads

1. สร้าง image จาก Dockerfile ของ Lab ใน Cloud Shell และ push ไปยัง Artifact Registry ส่วนตัว:

```bash
REPOSITORY="$(terraform -chdir=infra output -raw artifact_registry_repository)"
gcloud auth configure-docker asia-southeast1-docker.pkg.dev --quiet
IMAGE_TAG="$REPOSITORY/partner-relay:lab09-$(date -u +%Y%m%d%H%M%S)"
docker build --pull --tag "$IMAGE_TAG" .
docker push "$IMAGE_TAG"
IMAGE_DIGEST="$(gcloud artifacts docker images describe "$IMAGE_TAG" --project "$PROJECT_ID" --format='value(image_summary.digest)')"
printf '%s\n' "$IMAGE_DIGEST"
```

ตรวจว่า IMAGE_DIGEST ขึ้นต้น sha256: และมี digest ครบ. Tag ใช้ค้น image; Terraform ต้องใช้ digest เพื่อให้ revision ทำซ้ำได้.

2. แก้ไฟล์ infra/terraform.tfvars ด้วย nano: ตั้ง image_uri เป็น path ของ image เดิมแต่ใช้ @sha256: แทน tag เช่น asia-southeast1-docker.pkg.dev/PROJECT/lab009-images/partner-relay@sha256:DIGEST; ตั้ง enable_workloads=true และคง pause_scheduler=true/allow_destroy=false. ห้ามใส่ tag ที่เปลี่ยนได้และห้ามเปิด scheduler พร้อม deploy รอบแรก.
3. ดูแผนและ apply:

```bash
terraform -chdir=infra plan -out=workloads.tfplan
terraform -chdir=infra show workloads.tfplan
terraform -chdir=infra apply -input=false workloads.tfplan
terraform -chdir=infra output
```

ตรวจว่า Cloud Run services มี Event API, Worker, Reconciler และ Simulator ของ partner-a; Scheduler job ถูกสร้างแต่ Paused. หาก deploy ไม่สำเร็จเพราะ Secret version ไม่พบ ให้ตรวจหมายเลข version/สิทธิ์ Secret Accessor ของ runtime identity ก่อน ไม่ต้องสร้าง secret ซ้ำโดยไม่ตรวจรายการ version.

**Expected:** image_uri ถูก pin ด้วย digest, Cloud Run ทุก service ใช้ image digest เดียวกัน, min instances เป็น 0, Scheduler Paused และ Terraform state ไม่มี HMAC bytes.

**Actual / Status / UTC:** ______  
**Evidence:** ______ (image digest, revision names, plan/apply summary; redact project details ตามต้องการ)

### Task 05 — ตรวจ Health, Authentication และ Trust Boundary

กำหนด URL จาก Terraform output:

```bash
EVENT_URL="$(terraform -chdir=infra output -raw event_api_url)"
SIMULATOR_URL="$(terraform -chdir=infra output -json workload_urls | python3 -c 'import json,sys; print(json.load(sys.stdin)["simulators"]["partner-a"])')"
```

1. ตรวจ Event API ว่าปิดกั้นผู้ไม่มีสิทธิ์ และเข้าถึงได้ด้วย identity ของผู้เรียน:

```bash
curl -sS -o /dev/null -w 'unauthenticated HTTP %{http_code}\n' "$EVENT_URL/healthz"
TOKEN="$(gcloud auth print-identity-token)"
curl -sS -H "Authorization: Bearer $TOKEN" -w '\nauthenticated HTTP %{http_code}\n' "$EVENT_URL/healthz"
unset TOKEN
curl -sS -o /tmp/lab009-simulator-health.json -w 'HTTP %{http_code}\\n' "$SIMULATOR_URL/healthz" && cat /tmp/lab009-simulator-health.json
```

คาดว่า unauthenticated ถูกปฏิเสธและ authenticated ได้ HTTP 200. gcloud ID token สำหรับทดสอบผู้พัฒนาไม่มี audience claim; ใช้เฉพาะ sandbox และอย่านำวิธีนี้ไปแทน service-to-service OIDC ในระบบจริง.

2. ตรวจ public simulator health endpoint และ IAM/ingress ของ Worker/Reconciler ใน Cloud Run → Services → เลือก service → Security/Networking. Simulator เปิด public เฉพาะเพื่อแทน endpoint ภายนอก แต่ทุก webhook ต้องผ่าน HMAC; Event API ยังต้องผ่าน Cloud Run IAM; Worker/Reconciler ต้อง internal ingress และมี invoker เฉพาะ task/scheduler service account.
3. ตรวจ Cloud Tasks queue และ Scheduler job ว่ายังตรงค่าที่ deploy. ถ้า simulator ถูก policy องค์กรห้าม public invoker, หยุดและเลือก sandbox ที่ได้รับอนุมัติ ห้ามเปิด policy ระดับองค์กร.

**Expected:** /healthz ของ Event API ตอบ 200 เมื่อมีสิทธิ์และถูกปฏิเสธเมื่อไม่มี; simulator health ตอบ 200; Worker/Reconciler ไม่ได้เปิดเป็น public endpoint.

**Actual / Status / UTC:** ______  
**Evidence:** ______ (HTTP status, service ingress/IAM principal แบบปกปิดอีเมล)

### Task 06 — ส่ง Event, พิสูจน์ Idempotency และ Conflict

เตรียม payload สังเคราะห์ 1 รายการและ key ใหม่; คำสั่งนี้สร้าง timestamp ปัจจุบันเป็น UTC:

```bash
OCCURRED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
PAYLOAD="$(printf '{"partner_id":"partner-a","order_ref":"ORD-LAB00001","occurred_at":"%s","shipping_status":"shipped"}' "$OCCURRED_AT")"
IDEMPOTENCY_KEY="lab09-$(openssl rand -hex 16)"
TOKEN="$(gcloud auth print-identity-token)"
HTTP_CODE="$(curl -sS -o /tmp/lab009-response.json -w '%{http_code}' -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -H "Idempotency-Key: $IDEMPOTENCY_KEY" -d "$PAYLOAD" "$EVENT_URL/v1/events")"
printf 'HTTP %s\n' "$HTTP_CODE"
cat /tmp/lab009-response.json
```

Expected status คือ 202. บันทึก event_id และ delivery_id จาก JSON ลงช่อง Actual ของ Task นี้; อย่าใช้ idempotency key เดิมกับ event คนละเรื่อง.

1. ส่งคำขอเดิมซ้ำด้วย key และ body เดิม; ต้องได้ event_id/delivery_id เดิมและ duplicate=true:

```bash
curl -sS -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -H "Idempotency-Key: $IDEMPOTENCY_KEY" -d "$PAYLOAD" "$EVENT_URL/v1/events"
```

2. เปลี่ยน order_ref แต่คง key เดิม; API ต้องปฏิเสธด้วย HTTP 409:

```bash
CONFLICT_PAYLOAD="$(printf '{"partner_id":"partner-a","order_ref":"ORD-LAB00002","occurred_at":"%s","shipping_status":"shipped"}' "$OCCURRED_AT")"
curl -sS -o /tmp/lab009-conflict.json -w 'HTTP %{http_code}\n' -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -H "Idempotency-Key: $IDEMPOTENCY_KEY" -d "$CONFLICT_PAYLOAD" "$EVENT_URL/v1/events"
cat /tmp/lab009-conflict.json
unset TOKEN
```

ตรวจ ledger ด้วย Operator CLI ใน Task 07. HTTP 202 หมายถึง durable intent ถูกเขียนแล้ว ไม่ได้ยืนยันว่าคู่ค้ารับ event แล้ว.

**Expected:** ครั้งแรก 202, replay ได้ ID เดิมพร้อม duplicate=true, และ key เดิมกับ payload ต่างตอบ 409.

**Actual / Status / UTC:** ______  
**Evidence:** ______ (event_id, delivery_id, HTTP codes และ response ที่ไม่มี token)

### Task 07 — ติดตาม Retry และตรวจ Receipt ของคู่ค้า

ใช้ delivery_id จาก Task 06 ตรวจสถานะโดยไม่เปิด payload:

```bash
python -m app.operator_cli inspect --project "$PROJECT_ID" --delivery-id "วาง-delivery-id"
gcloud tasks queues describe partner-a --location "$REGION" --project "$PROJECT_ID"
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="lab009-worker"' --project "$PROJECT_ID" --limit=30 --format='value(timestamp,textPayload,jsonPayload.message)'
```

fault mode เริ่มต้น transient-503-first-two: attempt 1 และ 2 ของ simulator ตอบ 503; attempt ถัดไปที่ถูกต้องบันทึก receipt และตอบ 200. Cloud Tasks retry เป็น asynchronous และไม่มีเวลาสำเร็จที่รับประกัน; ตรวจซ้ำด้วย inspect จน status เป็น delivered หรือจนพบ error ที่ต้องแก้. อย่าส่ง business event ใหม่เพื่อแก้ retry.

เมื่อ status delivered แล้วอ่าน bucket จาก Terraform และค้น receipt เฉพาะ event นี้:

```bash
RECEIPT_BUCKET="$(terraform -chdir=infra output -json receipt_buckets | python3 -c 'import json,sys; print(json.load(sys.stdin)["partner-a"])')"
python -m app.operator_cli receipt --project "$PROJECT_ID" --bucket "$RECEIPT_BUCKET" --partner-id partner-a --event-id "วาง-event-id"
```

receipt แสดง event ID, partner, payload hash, เวลาได้รับครั้งแรก และ attempt แรก; ไม่แสดง raw body หรือ HMAC. การไม่พบ receipt เพียงอย่างเดียวไม่พิสูจน์ว่าคู่ค้าไม่เคยได้รับ request.

**Expected:** delivery จบ delivered, outbound attempts สอดคล้องกับ fault mode (คาดว่า 3 เมื่อแต่ละ response ไปถึง handler), และมี receipt hash ที่ตรง event.

**Actual / Status / UTC:** ______  
**Evidence:** ______ (สถานะ/attempt count, receipt hash, log timestamps; ไม่คัดลอก payload หรือ signature)

### Task 08 — พิสูจน์กรณีรับสำเร็จแต่ Response หาย

เปลี่ยนเฉพาะ fault_mode ของ partner-a ใน infra/terraform.tfvars เป็น accept-then-503-on-first แล้วรัน plan/apply ปกติ. สร้าง key ใหม่และ order_ref ใหม่ตาม Task 06; เก็บ event_id/delivery_id ใหม่ไว้. Simulator จะบันทึก receipt ก่อนตอบ 503 ใน attempt แรก; retry ถัดไปต้องพบ receipt ที่มี hash เดิมและตอบสำเร็จแบบ duplicate. รอและตรวจด้วย Operator CLI:

```bash
python -m app.operator_cli inspect --project "$PROJECT_ID" --delivery-id "วาง-delivery-id-ใหม่"
python -m app.operator_cli receipt --project "$PROJECT_ID" --bucket "$RECEIPT_BUCKET" --partner-id partner-a --event-id "วาง-event-id-ใหม่"
```

หลังทดสอบให้เปลี่ยน fault_mode กลับเป็น transient-503-first-two และ apply อีกครั้ง เพื่อให้ baseline config สะอาดก่อนงานถัดไป. ไม่ลบ receipt เพื่อให้ idempotency evidence ยังคงอยู่จนถึง cleanup.

**Expected:** simulator receipt บันทึก first_attempt_number=1; delivery จบ delivered หลัง retry และ event ID/payload hash ไม่เปลี่ยน. นี่พิสูจน์ receiver dedupe ใน simulator เท่านั้น ไม่ใช่ exactly-once guarantee.

**Actual / Status / UTC:** ______  
**Evidence:** ______ (first attempt/result, retry result, receipt hash และ Terraform diff)

### Task 09 — เปิด Reconciliation และทดสอบการทำงานตามรอบ

ก่อนเปิด Scheduler ตรวจว่า Task 06–08 ไม่มี delivery ที่ยังต้องตรวจและ Terraform configuration ถูกต้อง. ใน tfvars ตั้ง pause_scheduler=false แล้ว plan/apply:

```bash
terraform -chdir=infra plan -out=scheduler.tfplan
terraform -chdir=infra show scheduler.tfplan
terraform -chdir=infra apply -input=false scheduler.tfplan
gcloud scheduler jobs describe lab009-reconcile-every-minute --location "$REGION" --project "$PROJECT_ID"
```

Scheduler เรียก Reconciler ทุกนาทีใน UTC. รออย่างน้อยหนึ่งรอบและดู Cloud Scheduler → Jobs → job → Logs. อ่าน summary ที่ service บันทึกแบบไม่ใส่ payload/secret จาก Cloud Run logs:

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="lab009-reconciler"' --project "$PROJECT_ID" --limit=20 --format='value(timestamp,textPayload,jsonPayload.message)'
```

ตรวจ pending_seen/queued_seen/running_seen ว่ารวมต่อรอบไม่เกิน 25; log นี้แสดงเฉพาะ bounded counters. จะสั่ง run ทันทีได้ด้วย:

```bash
gcloud scheduler jobs run lab009-reconcile-every-minute --location "$REGION" --project "$PROJECT_ID"
```

หากต้องการยืนยันการซ่อม outbox ให้ใช้ event จาก fault test ที่มี status enqueue_pending หลังเกิด enqueue error ที่ตรวจสอบได้; อย่าลบหรือแก้ Firestore record ด้วยมือเพื่อสร้างอาการ. หลังตรวจเสร็จให้คง Scheduler ไว้เฉพาะเวลาทดลอง และ pause กลับหากยังไม่ทำ Task ต่อ.

**Expected:** Scheduler เป็น ENABLED, ใช้ OIDC identity ที่มีสิทธิ์ invoke Reconciler, response 200 เมื่อรอบไม่มี error; Reconciler ไม่รับ control fields จาก request และทำงานแบบ bounded.

**Actual / Status / UTC:** ______  
**Evidence:** ______ (job state/last attempt, run summary และ Cloud Run log ที่ redact แล้ว)

### Task 10 — Incident: Permanent Rejection และ Audited Redrive

1. เปลี่ยน fault_mode ของ partner-a ใน tfvars เป็น permanent-400 แล้ว apply. ส่ง event ใหม่ตาม Task 06 ด้วย idempotency key ใหม่; คาดว่า delivery กลายเป็น permanent_failed และไม่มี receipt เพราะ simulator ปฏิเสธก่อนรับข้อมูล.
2. ใช้ inspect ตรวจ status, HTTP status/error code และ delivery_id. แก้ fault_mode กลับเป็น normal แล้ว apply ให้ simulator พร้อมก่อน redrive.
3. ตรวจ receipt ก่อน: ถ้าเป็น permanent failure ที่ยืนยันว่าไม่มี receipt ให้ดำเนิน redrive; ถ้าเป็น retry_ended_unknown ให้ตรวจ logs, Cloud Tasks metadata และ receipt ก่อนเสมอ. ถ้าหาหลักฐานไม่ได้ ให้หยุดและบันทึก unknown—อย่า redrive แบบเดา.

```bash
python -m app.operator_cli receipt --project "$PROJECT_ID" --bucket "$RECEIPT_BUCKET" --partner-id partner-a --event-id "วาง-event-id"
```
4. บันทึก redrive ผ่าน Operator CLI ซึ่งเขียน actor, reason, evidence reference และ generation ใหม่แบบ transaction; CLI ไม่มีสิทธิ์ enqueue task โดยตรง, Reconciler จะสร้าง task generation ใหม่:

```bash
ACTIVE_EMAIL="$(gcloud auth list --filter=status:ACTIVE --format='value(account)')"
python -m app.operator_cli redrive --project "$PROJECT_ID" --region "$REGION" --delivery-id "วาง-delivery-id" --actor-email "$ACTIVE_EMAIL" --reason "ยืนยัน permanent 400 จาก synthetic simulator; เปลี่ยน mode เป็น normal แล้ว" --evidence-ref "evidence/LAB09/task-10-incident"
python -m app.operator_cli inspect --project "$PROJECT_ID" --delivery-id "วาง-delivery-id"
```

ตรวจ audit record ใน Firestore และ Cloud Audit Logs; รอให้ Reconciler สร้าง task และตรวจผลสุดท้ายเป็น delivered. ถ้า Scheduler paused ให้ run job หนึ่งครั้งหรือเปิดกลับชั่วคราวก่อนรอ.

**Expected:** terminal failure เดิมยังตรวจย้อนหลังได้; redrive เพิ่ม generation โดยไม่เปลี่ยน event ID/payload, บันทึก actor/reason/evidence, และผล generation ใหม่ส่งสำเร็จหลังแก้สาเหตุ.

**Actual / Status / UTC:** ______  
**Evidence:** ______ (generation ก่อน/หลัง, audit metadata, receipt/log ใหม่; redact email ก่อนเผยแพร่)

### Task 11 — Change Request: เพิ่ม Partner-B แบบแยกขอบเขต

Requirement ใหม่: เพิ่มคู่ค้าสังเคราะห์ partner-b โดยต้องได้ queue, HMAC secret/version, public simulator และ receipt bucket ของตนเอง; rate limit เท่ากับ partner-a; ห้าม partner-a อ่าน secret หรือ receipt ของ partner-b.

แก้เฉพาะค่า `partners` ใน `infra/terraform.tfvars` ให้เป็นดังนี้ โดยคงค่า project/region/identity อื่นไว้:

```hcl
partners = {
  "partner-a" = {
    fault_mode     = "transient-503-first-two"
    secret_version = "1"
  }
  "partner-b" = {
    fault_mode     = "permanent-400"
    secret_version = "1"
  }
}
```

1. เพิ่ม block partner-b ใน map partners ของ tfvars โดยตั้ง fault_mode=permanent-400 และ secret_version=1. สร้างเฉพาะ Secret metadata ก่อน เพราะ simulator อ่าน secret ตอนเริ่มต้น:

```bash
terraform -chdir=infra plan -target='google_secret_manager_secret.partner["partner-b"]'
terraform -chdir=infra apply -target='google_secret_manager_secret.partner["partner-b"]'
```

Targeted apply ใช้ครั้งเดียวสำหรับ prerequisite นี้เท่านั้น; Terraform แสดง warning ได้. ต่อไปให้ใช้ plan/apply ปกติ.
2. เพิ่ม secret version แยกให้ partner-b โดยใช้ขั้นตอน Task 03 แต่เปลี่ยน secret ID เป็น lab009-partner-b-hmac. อย่าใช้ key ของ partner-a ซ้ำ.
3. รัน full plan; ตรวจว่ามี partner-b queue/secret IAM/simulator identity/simulator service/private bucket และ Event API/Worker/Reconciler config update แต่ไม่มีการเปลี่ยน resource ที่ไม่เกี่ยวข้อง. Apply แล้วตรวจผล:

```bash
terraform -chdir=infra plan -out=partner-b.tfplan
terraform -chdir=infra show partner-b.tfplan
terraform -chdir=infra apply -input=false partner-b.tfplan
gcloud tasks queues describe partner-b --location "$REGION" --project "$PROJECT_ID"
terraform -chdir=infra output -json receipt_buckets
terraform -chdir=infra output -json workload_urls
```

4. ส่ง event ใหม่ไป partner-b ด้วย key ใหม่และ body ของ partner-b:

```bash
OCCURRED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
PAYLOAD="$(printf '{"partner_id":"partner-b","order_ref":"ORD-LAB00003","occurred_at":"%s","shipping_status":"shipped"}' "$OCCURRED_AT")"
IDEMPOTENCY_KEY="lab09-partner-b-$(openssl rand -hex 12)"
TOKEN="$(gcloud auth print-identity-token)"
curl -sS -o /tmp/lab009-partner-b.json -w 'HTTP %{http_code}\n' -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -H "Idempotency-Key: $IDEMPOTENCY_KEY" -d "$PAYLOAD" "$EVENT_URL/v1/events"
cat /tmp/lab009-partner-b.json
unset TOKEN
EVENT_ID_B="$(python3 -c 'import json; print(json.load(open("/tmp/lab009-partner-b.json"))["event_id"])')"
DELIVERY_ID_B="$(python3 -c 'import json; print(json.load(open("/tmp/lab009-partner-b.json"))["delivery_id"])')"
RECEIPT_BUCKET_B="$(terraform -chdir=infra output -json receipt_buckets | python3 -c 'import json,sys; print(json.load(sys.stdin)["partner-b"])')"
python -m app.operator_cli inspect --project "$PROJECT_ID" --delivery-id "$DELIVERY_ID_B"
```

Expected จะเป็น permanent_failed จาก fault mode. ใช้ receipt lookup ของ partner-b; ข้อความ receipt_missing พร้อม exit code 4 เป็นผลที่คาดจากการปฏิเสธก่อนรับข้อมูล ส่วน permission/API error ไม่ใช่ผลเดียวกัน. คำสั่ง lookup:

```bash
python -m app.operator_cli receipt --project "$PROJECT_ID" --bucket "$RECEIPT_BUCKET_B" --partner-id partner-b --event-id "$EVENT_ID_B"
```

ตรวจ bucket B ใน Cloud Storage ว่าไม่มี receipt ของ event นี้และไม่เห็น receipt ของ A. เปลี่ยน fault_mode B เป็น normal แล้ว apply.
5. สั่ง redrive แบบ audited หลังเปลี่ยน fault mode และตรวจผล generation ใหม่:

```bash
ACTIVE_EMAIL="$(gcloud auth list --filter=status:ACTIVE --format='value(account)')"
python -m app.operator_cli redrive --project "$PROJECT_ID" --region "$REGION" --delivery-id "$DELIVERY_ID_B" --actor-email "$ACTIVE_EMAIL" --reason "ยืนยัน permanent 400 ของ partner-b simulator; เปลี่ยน mode เป็น normal แล้ว" --evidence-ref "evidence/LAB09/task-11-partner-b"
python -m app.operator_cli inspect --project "$PROJECT_ID" --delivery-id "$DELIVERY_ID_B"
python -m app.operator_cli receipt --project "$PROJECT_ID" --bucket "$RECEIPT_BUCKET_B" --partner-id partner-b --event-id "$EVENT_ID_B"
```

ยืนยัน generation ใหม่ delivered. ใน Cloud Storage → Buckets และ Secret Manager → Secrets ตรวจว่า identity/secret/bucket mapping แยกกันตาม partner. ห้ามใช้คำว่า “ไม่มี cross-partner access” เป็นผลพิสูจน์จาก Terraform plan อย่างเดียว; เก็บ IAM/negative test ถ้าทำตามได้ด้วย identity ที่จำกัด.

**Expected:** มีสอง queue แยกต่อ partner, rate limit เดิม, secret และ receipt bucket แยก, event ของ B ไม่ถูก route ไป endpoint A, และ redrive B มี audit trail.

**Actual / Status / UTC:** ______  
**Evidence:** ______ (plan diff, queue config, bucket/secret metadata, event IDs และ redrive audit; ไม่เก็บ secret)

### Task 12 — Cleanup, Rebuild Notes และ Portfolio Evidence Closeout

การ cleanup ลบงานสังเคราะห์, secret metadata/versions, Firestore database, image และ infrastructure; เป็นการลบข้อมูลที่ย้อนคืนไม่ได้. บันทึกหลักฐาน/เวลาที่ต้องใช้ก่อนเริ่ม และตรวจ project ซ้ำทุกครั้ง.

1. ตั้ง pause_scheduler=true ใน tfvars แล้ว apply; ตรวจ Scheduler เป็น Paused.
2. Pause queue แต่ละตัวและตรวจงานที่กำลังรัน/สถานะ ledger ก่อน purge:

```bash
gcloud tasks queues pause partner-a --location "$REGION" --project "$PROJECT_ID"
gcloud tasks queues pause partner-b --location "$REGION" --project "$PROJECT_ID"
gcloud tasks queues describe partner-a --location "$REGION" --project "$PROJECT_ID"
```

ถ้ายังไม่ได้สร้าง partner-b ให้ข้ามบรรทัดของ partner-b. รอ in-flight attempts ให้จบหรือบันทึกสถานะก่อน; purge เป็นการลบ task แบบถาวรและงานอาจยัง dispatch ได้ระหว่างที่ purge ใช้เวลาถึงประมาณหนึ่งนาที.

3. เมื่อยืนยันว่าไม่ต้องการ task/receipt อีกแล้ว ให้ purge queue ที่มีอยู่:

```bash
gcloud tasks queues purge partner-a --location "$REGION" --project "$PROJECT_ID"
```

ทำซ้ำเฉพาะ queue ที่สร้างจริง และรออย่างน้อยหนึ่งนาทีพร้อมตรวจ state ก่อนเดินต่อ.
4. ตั้ง allow_destroy=true ใน tfvars แล้ว apply ขณะที่ enable_workloads=true และ pause_scheduler=true เพื่อปิด deletion protection ก่อน. จากนั้นเปลี่ยน enable_workloads=false แล้ว apply ปกติ เพื่อเอา Cloud Run/Scheduler ออก. ตรวจหน้า Cloud Run และ Scheduler ว่าไม่มี Lab09 workload เหลือ.
5. ใน Artifact Registry เปิด repository lab009-images → image partner-relay → เลือก versions/tags ของ Lab 09 และลบ. ตรวจและลบเฉพาะ package ของ Lab ด้วยคำสั่งนี้; การลบ image ย้อนคืนไม่ได้:

```bash
gcloud artifacts docker images list "$REPOSITORY/partner-relay" --project "$PROJECT_ID"
gcloud artifacts docker images delete "$REPOSITORY/partner-relay" --delete-tags --quiet --project "$PROJECT_ID"
```

ใน Cloud Storage เปิด receipt buckets ที่ Terraform output ระบุ, ตรวจว่าชื่อเป็นของ Lab 09 เท่านั้น, ลบ objects ทั้งหมดให้ bucket ว่าง; อย่าลบ bucket ด้วยคำสั่ง object-recursive.
6. ตรวจแผน destroy ก่อนยืนยัน:

```bash
terraform -chdir=infra plan -destroy -out=cleanup.tfplan -var='allow_destroy=true'
terraform -chdir=infra show cleanup.tfplan
```

ยืนยันว่า project/รายการที่จะลบถูกต้องและไม่มี resource อื่นปน แล้วจึงสั่ง:

```bash
terraform -chdir=infra destroy -var='allow_destroy=true'
```

7. ตรวจ Console และ Terraform state ว่า Lab09 resources ถูกลบ; เก็บเฉพาะหลักฐานที่ redact แล้ว, CI link, Terraform version, image digest, test IDs, timestamps, incident/change-request records และผล cleanup. เติม Case-study summary ด้านล่างด้วยผล Actual ของคุณ; CI ไม่ใช่ Cloud verification. หากยังไม่ได้ทำ Cloud ให้ระบุ Cloud verification: Not run.

**Expected:** Scheduler paused, queues ไม่มี task ก่อน destroy, Cloud Run/Firestore/Secrets/queues/buckets/repository ของ Lab ถูกลบตาม plan; Google APIs ที่เปิดให้ project ยังคง enabled เพราะ Terraform ตั้ง `disable_on_destroy = false`. ไม่มี resource ของ project อื่นถูกแตะ และไฟล์หลักฐานไม่เปิดเผย token/secret/PII.

**Actual / Status / UTC:** ______  
**Evidence:** ______ (destroy plan/apply, รายการ resource หลัง cleanup, ชื่อไฟล์ภาพ/บันทึกที่ redact แล้ว)

## Case-study summary — เติมหลังทำ Lab

- **บริบท/ปัญหา:** ______
- **ข้อกำหนดและข้อจำกัด:** ______
- **สถาปัตยกรรมที่เลือกและเหตุผล:** ______
- **สิ่งที่ลงมือทำ:** ______
- **ผลทดสอบที่เกิดขึ้นจริง:** ______ (ระบุ synthetic only; แยก Expected ออกจาก Actual)
- **ความล้มเหลว/การวินิจฉัย/การแก้ไข:** ______
- **Reliability, security และ cost trade-offs:** ______
- **Change Request partner-b:** ______
- **หลักฐานที่เปิดเผยได้:** ______ (ภาพ/คำสั่ง/CI/diagram ที่ redact แล้ว)
- **ข้อจำกัดและสิ่งที่จะทำต่อ:** ______
- **Cloud verification:** Not run / Verified on ______ โดย ______ (เลือกและกรอกเฉพาะเมื่อผู้เรียนรันทดสอบจริง)

## Prerequisites และต้นทุนที่ต้องประเมิน

ผู้เรียนต้องมี project ฝึกที่เปิด billing และสิทธิ์สร้าง APIs, IAM bindings/service accounts, Cloud Run, Cloud Tasks, Firestore Native, Scheduler, Secret Manager, Storage และ Terraform state. Role matrix แบบ least privilege จะทำใน Design/Guide. ต้องตรวจ availability/quota ของ services ใน region ก่อน apply; ยังไม่จำเป็นต้องใช้ VPC connector, Cloud SQL, GKE, public load balancer หรือ partner account จริง.

ต้นทุนที่อาจเกิด: Cloud Run requests/compute, Cloud Tasks, Firestore reads/writes, Scheduler invocations, Secret Manager access, Cloud Storage operations/storage, network egress และ log retention. ตั้ง min instances เป็นศูนย์และจำกัด synthetic events/attempts; ก่อน apply ให้ประเมิน region/ปริมาณ/retention ใน Pricing Calculator และตรวจ budget. Budget alert ไม่ใช่ spending cap. ไม่มีการสร้าง resources หรือ deploy โดยผู้จัดทำ.

## ยังไม่รวม

- partner API จริง, production order data/PII, payment, multi-region DR หรือ SLA claim
- exactly-once delivery หรือใช้ task-name dedupe แทน durable ledger
- automatic payload rewrite/แก้ event เดิมแล้ว redrive ทับข้อมูล; การแก้ payload ต้อง audit และนิยามใน Design
- การอ้าง Cloud verification จาก unit/CI/emulator test หรือการคาดเดาผล Console

## คู่มืออ้างอิงสำหรับทำตามขั้นตอน

- [Use Cloud Shell and its preinstalled tools, including Docker](https://docs.cloud.google.com/shell/docs/how-cloud-shell-works)
- [Authenticate developers to Cloud Run for test requests](https://docs.cloud.google.com/run/docs/authenticating/developers)
- [Add Secret Manager secret versions without command-line plaintext](https://docs.cloud.google.com/secret-manager/docs/add-secret-version)
- [Pause and purge Cloud Tasks queues](https://docs.cloud.google.com/tasks/docs/manage-queues-and-tasks)
- [Delete Cloud Storage objects](https://docs.cloud.google.com/storage/docs/deleting-objects)
- [Delete Artifact Registry image versions](https://docs.cloud.google.com/artifact-registry/docs/docker/manage-images)
- [Install Terraform from HashiCorp releases](https://developer.hashicorp.com/terraform/install)

## References used for design

- [Authentication for Terraform in Cloud Shell](https://docs.cloud.google.com/docs/terraform/authentication)
- [Lab 09 ใน Roadmap](../ROADMAP.md#lab-09)
- [Cloud Tasks locations](https://docs.cloud.google.com/tasks/docs/locations) · [Cloud Scheduler locations](https://docs.cloud.google.com/scheduler/docs/locations) · [Firestore locations](https://docs.cloud.google.com/firestore/native/docs/locations) · [Cloud Run locations](https://docs.cloud.google.com/run/docs/locations) · [Cloud Storage locations](https://docs.cloud.google.com/storage/docs/locations) · [Secret Manager locations](https://docs.cloud.google.com/secret-manager/docs/locations)
- [Cloud Tasks overview และ at-least-once behavior](https://docs.cloud.google.com/tasks/docs/dual-overview)
- [Cloud Tasks HTTP target headers และ OIDC](https://docs.cloud.google.com/tasks/docs/creating-http-target-tasks)
- [Cloud Tasks queue rate limits และ retry policy](https://docs.cloud.google.com/tasks/docs/configuring-queues)
- [Cloud Tasks queues/tasks operations](https://docs.cloud.google.com/tasks/docs/manage-queues-and-tasks)
- [Cloud Run ingress restrictions](https://docs.cloud.google.com/run/docs/securing/ingress)
- [HMAC RFC 2104](https://www.rfc-editor.org/rfc/rfc2104/)
- [Cloud Storage request preconditions](https://docs.cloud.google.com/storage/docs/request-preconditions)
