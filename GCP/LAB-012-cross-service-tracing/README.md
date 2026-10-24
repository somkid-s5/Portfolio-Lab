---
lab: LAB-012
platform: GCP
phase: design
guide_status: design
cloud_verification: not-run
last_verified: null
---
# Lab 12 — ระบบ Microservices ที่ติดตามปัญหาข้ามบริการได้

**สถานะ:** Design checkpoint — ยืนยันโจทย์และ architecture ก่อนเริ่มเขียน Tasks/คู่มือปฏิบัติ. ยังไม่มี Cloud deployment หรือผลทดสอบจริง.

## สถานการณ์

ทีม Commerce พบว่า checkout บางช่วงช้าและตอบ error แต่ log ของ Storefront, Order, Catalog และ Payment mock แยกจากกัน ทีมต้องระบุให้ได้ว่า request หนึ่งวิ่งผ่านบริการใด ใช้เวลาที่ไหน และ failure เริ่มจาก dependency ตัวไหน โดยไม่เปิดสิทธิ์ Cloud ให้ทุก service และไม่ retry แบบไม่จำกัด

Lab นี้สร้าง checkout แบบ synthetic บน GKE. ผู้เรียนจะ deploy services, instrument HTTP boundaries ด้วย OpenTelemetry, ส่ง W3C trace context ผ่านทุก hop, ดู trace ใน Cloud Trace และเชื่อม structured log ใน Cloud Logging ด้วย trace ID. จากนั้นจำลอง dependency timeout/503, วัดผลการ retry ที่มีเพดาน, กู้ service และเปลี่ยน contract แบบ backward-compatible ทีละชั้น.

## ผู้ใช้และผลลัพธ์ที่ต้องพิสูจน์

Client เรียก POST /v1/checkout ผ่าน HTTPS พร้อม demo bearer token ด้วย SKU และจำนวนชิ้น. Storefront เรียก Order service; Order อ่าน Catalog และขออนุมัติจาก Payment mock. เมื่อสำเร็จ API ตอบ checkout_id, total_thb และ trace_id. Payment mock ไม่เชื่อม payment provider, ไม่มีการตัดเงินจริง และไม่มี customer PII.

**เกณฑ์ยอมรับ**

| ID | Requirement | หลักฐาน |
|---|---|---|
| R1 | HTTPS entry point พร้อม demo bearer-token check ไปยัง Storefront; backend services ไม่ถูกเปิด public | Gateway/HTTPRoute, service inventory, token allow/deny และ request success |
| R2 | หนึ่ง checkout มี distributed trace ที่เชื่อม Storefront → Order → Catalog และ Payment mock ด้วย traceparent | trace ID/parent-child spans ใน Cloud Trace |
| R3 | ทุก service ระบุ service.name, operation, status และ duration; failure span แยกจาก successful span | trace details และ span attributes ที่ผู้เรียนบันทึก |
| R4 | Payment fault ถูกควบคุมจาก deployment config และ Order retry ได้สูงสุด 2 attempts | fault config, trace attempts และ HTTP result |
| R5 | เมื่อเอา fault ออก ระบบกลับ success โดยไม่ต้องเปลี่ยน client contract | config diff, rollout และ retest |
| R6 | Structured application logs เชื่อมกับ trace/span ID; logs ไม่ใส่ token, PII หรือ payload เกินจำเป็น | Cloud Logging query และ trace correlation |
| R7 | Workload identity แยก Collector จาก App; เฉพาะ collector identity ส่ง trace ได้ | KSA/IAM binding และ denied/allowed probe |
| R8 | Service ingress มีขอบเขตและ resource/probe values ชัดเจน; bounded traffic/fault test มีเพดาน | manifests, policy inspection, load/test summary |
| R9 | เพิ่ม field ใน Catalog response โดยไม่ลบ field เดิม แล้ว rollout provider ก่อน consumer พร้อม rollback path | v1/v2 contract diff, rollout order และ compatibility retest |

Expected เป็นเกณฑ์ตรวจ ไม่ใช่ผลจริง. ห้ามสร้าง trace screenshot, PASS, latency หรือ Cloud result ไว้ล่วงหน้า.

## Solution design

![Architecture diagram: Microservices with cross-service tracing](assets/solution.svg)

[เปิด Diagram แบบ standalone HTML](assets/solution.html) · [ดู SVG source](assets/solution.svg) · [ดู icon provenance](assets/diagram-provenance.json)

### Request path

Client → regional external GKE Gateway → Storefront → Order service → Catalog + Payment mock. Gateway ใช้ HTTPS termination; backend เป็น ClusterIP ภายใน private regional GKE Autopilot. Gateway data plane ใช้ regional proxy-only subnet และ route ชี้เฉพาะ Storefront. NetworkPolicy จำกัด app ingress ตาม upstream relationship; egress ใช้ GKE/VPC routes ไปยัง service/Collector และ Google APIs. คู่มือจะไม่อ้างว่า Kubernetes NetworkPolicy จำกัด FQDN egress.

### Trace และ log path

แต่ละ service สร้าง server/client spans ด้วย OpenTelemetry Python SDK และ HTTP instrumentation. W3C traceparent ต้องถูก inject/extract โดยอัตโนมัติ; business spans ใส่ operation, dependency, attempt และ error type โดยไม่ใส่ข้อมูลส่วนบุคคล. Services ส่ง OTLP/gRPC ไปยัง Collector ภายใน cluster; Collector ใช้ KSA + Workload Identity Federation for GKE ส่ง traces ผ่าน Telemetry (OTLP) API ไป Cloud Trace. Cloud Telemetry ต้องใช้ quota project และสิทธิ์ serviceusage.services.use; จึงให้ collector เท่านั้นรับ roles/telemetry.tracesWriter และ roles/serviceusage.serviceUsageConsumer. App KSAs ไม่มี Google Cloud IAM roles.

App logs เป็น JSON ไป stdout/stderr; GKE ส่งไป Cloud Logging. ใส่ logging.googleapis.com/trace และ logging.googleapis.com/spanId ที่สัมพันธ์กับ active span เพื่อค้น log จาก trace โดยไม่ duplicate payload. Pipeline trace และ log แยกกัน; app ไม่ส่ง log ผ่าน Collector ใน design นี้.

### Components และ boundary

| Component | Role | Boundary |
|---|---|---|
| Regional external Gateway | รับ TLS/route ไป Storefront เท่านั้น | Public edge; proxy-only subnet อยู่ใน VPC |
| Storefront | client-facing checkout endpoint; ตรวจ demo bearer token จาก Kubernetes Secret | KSA เฉพาะ; ไม่มี Google Cloud IAM role |
| Order service | orchestration และ retry cap | เรียก Catalog/Payment mock ผ่าน ClusterIP |
| Catalog | synthetic SKU/price contract v1/v2 | ไม่มี database หรือข้อมูลจริง |
| Payment mock | synthetic approval; controlled 503/latency | ไม่เชื่อม provider/เงินจริง |
| OpenTelemetry Collector | รับ OTLP แล้ว export traces | KSA เฉพาะมี IAM trace-write/quota |
| Cloud Trace / Cloud Logging | trace analysis และ log correlation | project-level observability |
| Cloud Build / Artifact Registry | build และเก็บ image; deploy by digest | dedicated lab repository |

### Change request ที่ออกแบบไว้

Catalog v1 ตอบ sku, unit_price_thb และ available. Change request เพิ่ม currency และ catalog_revision แต่คง field เดิมและ semantics ไว้. Stage 1 ปล่อย Catalog v2 ก่อน แล้ว retest กับ Order consumer รุ่นเดิม. Stage 2 ปล่อย Order รุ่นที่อ่าน currency แบบ optional พร้อม fallback THB; ตรวจ rollout และ rollback ก่อนปิด change. ไม่มีการเปลี่ยน public checkout request/response ที่จำเป็นต่อ client.

### Cost, security และข้อจำกัด

ใช้ dedicated project, budget alert และการประเมินราคาก่อน apply. Regional Autopilot, external regional Gateway, Cloud Build/Artifact Registry, Cloud Trace และ Cloud Logging อาจมีค่าใช้จ่าย; จำกัด duration/requests ของ load/fault tests และ cleanup หลังจบ. ไม่ถือว่า budget alert เป็น spending cap. รายละเอียดราคาให้คำนวณใหม่ใน Google Cloud Pricing Calculator วันที่จะรัน.

GKE nodes เป็น private; control-plane access ใช้ DNS endpoint และ IAM-authenticated Cloud Shell. Storefront ตรวจ token สำหรับ lab ที่เก็บเป็น Kubernetes Secret; token ไม่ใช่ customer identity และไม่แทน production authentication. ไม่เปิด 0.0.0.0/0 เพื่อแก้ปัญหา access. TLS test cert เป็น self-signed สำหรับ lab hostname. ไม่มี database, durable order state, real payment gateway, customer identity, multi-region DR หรือ production SLO; ผล latency เป็น observation ของ run เดียว ไม่ใช่ SLA.

### ขอบเขต Task Guide ที่จะลงมือเขียน

หลัง brief/design ผ่าน review จะเขียน Tasks 00–19 ใน README นี้: cost/access → Terraform plan/apply → build/publish image → cluster access/TLS → Collector และ app deploy → baseline trace/log proof → controlled fault, retry, recovery → bounded traffic → backward-compatible Catalog/Order rollout → rollback → cleanup/evidence handoff. ทุก Task จะมี Expected, Actual และ Evidence fields; Guide CI จะตรวจ Bash syntax/link/config. Cloud verification จะคง Not run จนกว่าจะมีการรันจริงโดยผู้เรียน.

## References for this design

- [Cloud Trace: instrument for Cloud Trace](https://cloud.google.com/trace/docs/setup)
- [Python OpenTelemetry instrumentation sample](https://cloud.google.com/trace/docs/setup/python-ot)
- [Google Cloud Observability: OTLP support](https://cloud.google.com/stackdriver/docs/otlp/overview)
- [Migrate Collector exports to the Telemetry API](https://cloud.google.com/stackdriver/docs/otlp/migrate-collector-to-otlp-exporters)
- [GKE: deploy Google-Built OpenTelemetry Collector](https://cloud.google.com/stackdriver/docs/instrumentation/opentelemetry-collector-gke)
- [GKE: Workload Identity Federation](https://cloud.google.com/kubernetes-engine/docs/concepts/workload-identity)
- [Deploying regional Gateways on GKE](https://cloud.google.com/kubernetes-engine/docs/how-to/deploying-gateways)
