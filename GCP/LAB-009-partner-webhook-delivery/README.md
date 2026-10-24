---
lab: LAB-009
platform: GCP
phase: brief
guide_status: brief
cloud_verification: not-run
last_verified: null
---
# Lab 09 — ระบบส่ง Webhook ให้ระบบคู่ค้า

**สถานะ:** Brief complete — กำหนดโจทย์ ผู้ใช้ Requirements เกณฑ์รับมอบ และแนวทาง Solution แล้ว ขั้นถัดไปคือปิด Design ให้ครบก่อนสร้าง App, Terraform หรือ Tasks. ไม่มี GCP provisioning และ Cloud verification ยังคง Not run.

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
- Candidate stack: Cloud Run สำหรับ Event API, Reconciler, Delivery Worker และ simulator; Cloud Tasks หนึ่ง queue ต่อ partner; Firestore สำหรับ event/outbox/delivery ledger; Cloud Scheduler เรียก Reconciler; Secret Manager เก็บ HMAC keys; Cloud Storage เก็บ durable receipt ของ simulator แบบ create-only.
- Event API และ Reconciler ต้องผ่าน IAM authentication; Worker รับ traffic จาก Cloud Tasks ด้วย OIDC และจำกัด ingress เมื่อยืนยัน topology แล้ว. Partner simulator เป็น HTTPS endpoint สาธารณะเพื่อเลียนแบบ dependency ภายนอก แต่รับเฉพาะข้อมูลสังเคราะห์และตรวจ HMAC.
- ผู้เรียนใช้ gcloud CLI และ Terraform บน project เฉพาะ Lab. เอกสารนี้ไม่สร้าง GCP resources.

## Candidate solution flow

1. Producer ส่ง order.shipped พร้อม idempotency key ไปยัง Event API ที่ผ่าน Google IAM authentication.
2. API ตรวจ schema/ขนาด สร้าง payload hash และเขียน event กับ outbox record ใน Firestore transaction. API ตอบ 202 พร้อม event ID เมื่อบันทึก intent แล้ว; 202 ไม่ได้แปลว่าคู่ค้ารับ event แล้ว.
3. API พยายามสร้าง Cloud Task ใน queue ของ partner. หาก enqueue ไม่สำเร็จ outbox ยังคงอยู่; Reconciler ที่ Scheduler เรียกด้วย OIDC ค้นหา pending item แล้วซ่อมการ enqueue.
4. Cloud Tasks ส่ง event ID, partner ID และ delivery generation ไปยัง Worker ผ่าน OIDC; Worker อ่าน payload canonical จาก ledger ไม่เชื่อ URL/secret ที่ผู้ส่งแนบมา.
5. Worker เลือก endpoint จาก partner allowlist, อ่าน HMAC key จาก Secret Manager, สร้าง timestamp/signature ใหม่ต่อ attempt แล้ว POST ผ่าน HTTPS. Event ID เป็น idempotency key คงที่ตลอด retries.
6. Simulator ตรวจ HMAC แบบ constant-time และ freshness แล้วบันทึก receipt ที่ผูก event ID กับ payload hash. การเขียน receipt ใช้ Cloud Storage generation precondition เพื่อกัน overwrite; ถ้าชน receipt เดิมต้องอ่านและเทียบ hash ก่อนยืนยันว่าเป็น duplicate เดิม.
7. Worker บันทึก attempt/terminal state ก่อนตอบ 2xx ให้ Cloud Tasks. Transient failure ตอบ non-2xx เพื่อให้ retry; permanent rejection ต้องบันทึก terminal state ก่อน acknowledge.
8. Operator ใช้ ledger และ partner receipt lookup ก่อน redrive. Redrive เพิ่ม generation และ audit actor/reason; event ID/payload เดิมยังคงเดิมเพื่อให้ receiver deduplicate หากผลการส่งก่อนหน้าคลุมเครือ.

## Reliability และข้อควรระวังที่ต้องรักษาใน Design

- Cloud Tasks มี delivery แบบ at-least-once; Worker และ simulator จึงต้อง idempotent. ชื่อ task ช่วย dedupe ได้สูงสุด 24 ชั่วโมงหลัง task ถูกลบ ไม่ใช่ business idempotency ถาวร. Firestore ledger และ receiver receipt เป็นหลักฐานระยะยาว. [Cloud Tasks overview](https://docs.cloud.google.com/tasks/docs/dual-overview) · [task-name deduplication limit](https://docs.cloud.google.com/tasks/docs/quotas)
- Cloud Tasks ลบ task หลังสำเร็จหรือ retry หมด; task ที่ไม่อยู่ใน queue ไม่ใช่หลักฐานว่าคู่ค้ารับข้อมูล. หาก Worker ไม่เคยได้ attempt สุดท้าย ให้แสดง unknown/needs-review และให้ Operator ตรวจ ledger, queue/log และ partner receipt ก่อน redrive. [Manage queues and tasks](https://docs.cloud.google.com/tasks/docs/manage-queues-and-tasks)
- max attempts นับรวม attempt แรก; retry policy หยุดเมื่อทั้งจำนวน attempt และ retry duration ครบตามเงื่อนไข. Rate limit เป็นค่าต่อ queue และรวม first attempt กับ retry; Cloud Tasks อาจลด dispatch rate เพิ่มเมื่อปลายทางตอบ 429/503/5xx. ห้ามอ้างเวลา/throughput ที่ยังไม่ได้วัด. [queue rate/retry configuration](https://docs.cloud.google.com/tasks/docs/configuring-queues) · [retry behavior](https://docs.cloud.google.com/tasks/docs/common-pitfalls)
- Header X-CloudTasks-TaskRetryCount อาจนับ dispatch ที่ล้มก่อนถึง handler; X-CloudTasks-TaskExecutionCount นับคำตอบจาก handler. ใช้ร่วมกับ delivery attempt ledger ไม่ใช่แทนกัน. [HTTP target headers](https://docs.cloud.google.com/tasks/docs/creating-http-target-tasks)
- Cloud Tasks ใช้ OIDC กับ HTTP targets ได้; service account ที่สร้าง token ต้องอยู่ project เดียวกับ queue. ต้องแยก iam.serviceAccounts.actAs, Cloud Tasks service agent และ Cloud Run Invoker ตาม principal. Cloud Run internal ingress รู้จัก Cloud Tasks เมื่ออยู่ project/perimeter เดียวกันและใช้ default run.app URL; ต้องยืนยันกับ topology จริงก่อนเลือก. [HTTP target authentication](https://docs.cloud.google.com/tasks/docs/creating-http-target-tasks) · [Cloud Run ingress](https://docs.cloud.google.com/run/docs/securing/ingress)
- HMAC-SHA256 ใช้ยืนยันความถูกต้อง/ผู้ถือ shared secret ไม่ได้ปกปิดข้อมูล; HTTPS ยังจำเป็น. [RFC 2104](https://www.rfc-editor.org/rfc/rfc2104/)
- generation-match 0 ทำให้ Cloud Storage สร้าง object ได้เมื่อไม่มี live object ชื่อนั้น. หากชน object เดิม ต้องอ่านและเทียบ hash ไม่ถือว่า payload ซ้ำที่ถูกต้องทันที. [Cloud Storage request preconditions](https://docs.cloud.google.com/storage/docs/request-preconditions)

## ต้องปิดให้ครบใน Design ก่อนเขียน Tasks

1. กำหนด schema/canonicalization, idempotency scope, retention และข้อมูลที่อนุญาตใน API/Firestore.
2. วาด state machine สำหรับ accepted, enqueue-pending, queued, delivering, delivered, permanent-failure, retry-exhausted/unknown และ redrive; ระบุ transaction/lease/fencing และวิธีกู้ enqueue ที่ตอบไม่แน่นอน.
3. ระบุ worker deadline, queue attempts/duration/backoff, handling Retry-After และวิธีระบุ terminal attempt โดยไม่สมมติว่า retry count เท่ากับ worker executions.
4. ปิด HMAC canonical string, timestamp window, secret rotation, receipt dedupe, และ fault controls สำหรับ timeout/429/503/4xx/accept-then-drop; fault control ต้องไม่พึ่งค่าที่ producer สาธารณะส่งมา.
5. ระบุ resource map, region, Terraform roots, OIDC audience, ingress และ IAM matrix ของ Producer, Scheduler, API, Reconciler, Cloud Tasks, Worker, simulator และ Operator.
6. กำหนด metrics/log fields/alerts, redrive audit, retention, upper bounds ของ event/attempt/size/time และ cost estimate ก่อนผู้เรียน apply.
7. สร้าง topology และ event/retry/recovery diagrams ด้วย official GCP icons ตาม [diagram-style.md](../../docs/diagram-style.md); จัดเส้นตาม connectivity และแสดง trust boundary ของ simulator ให้ชัด.

## Prerequisites และต้นทุนที่ต้องประเมิน

ผู้เรียนต้องมี project ฝึกที่เปิด billing และสิทธิ์สร้าง APIs, IAM bindings/service accounts, Cloud Run, Cloud Tasks, Firestore Native, Scheduler, Secret Manager, Storage และ Terraform state. Role matrix แบบ least privilege จะทำใน Design/Guide. ต้องตรวจ availability/quota ของ services ใน region ก่อน apply; ยังไม่จำเป็นต้องใช้ VPC connector, Cloud SQL, GKE, public load balancer หรือ partner account จริง.

ต้นทุนที่อาจเกิด: Cloud Run requests/compute, Cloud Tasks, Firestore reads/writes, Scheduler invocations, Secret Manager access, Cloud Storage operations/storage, network egress และ log retention. ตั้ง min instances เป็นศูนย์และจำกัด synthetic events/attempts; ก่อน apply ให้ประเมิน region/ปริมาณ/retention ใน Pricing Calculator และตรวจ budget. Budget alert ไม่ใช่ spending cap. ไม่มีการสร้าง resources หรือ deploy โดยผู้จัดทำ.

## ยังไม่รวม

- partner API จริง, production order data/PII, payment, multi-region DR หรือ SLA claim
- exactly-once delivery หรือใช้ task-name dedupe แทน durable ledger
- automatic payload rewrite/แก้ event เดิมแล้ว redrive ทับข้อมูล; การแก้ payload ต้อง audit และนิยามใน Design
- การอ้าง Cloud verification จาก unit/CI/emulator test หรือการคาดเดาผล Console

## Reference ที่ใช้ปิด Brief

- [Lab 09 ใน Roadmap](../ROADMAP.md#lab-09)
- [Cloud Tasks overview และ at-least-once behavior](https://docs.cloud.google.com/tasks/docs/dual-overview)
- [Cloud Tasks HTTP target headers และ OIDC](https://docs.cloud.google.com/tasks/docs/creating-http-target-tasks)
- [Cloud Tasks queue rate limits และ retry policy](https://docs.cloud.google.com/tasks/docs/configuring-queues)
- [Cloud Tasks queues/tasks operations](https://docs.cloud.google.com/tasks/docs/manage-queues-and-tasks)
- [Cloud Run ingress restrictions](https://docs.cloud.google.com/run/docs/securing/ingress)
- [HMAC RFC 2104](https://www.rfc-editor.org/rfc/rfc2104/)
- [Cloud Storage request preconditions](https://docs.cloud.google.com/storage/docs/request-preconditions)
