---
lab: LAB-010
platform: GCP
phase: brief
guide_status: brief
cloud_verification: not-run
last_verified: null
---
# Lab 10 — ลดภาระอ่าน Catalog ด้วย Cache-aside

**สถานะ:** Brief — กำหนด business problem, ขอบเขตข้อมูล, acceptance และแนวทาง solution แล้ว; ยังไม่มี Task คู่มือ, Terraform, App หรือผลการรัน Cloud.

## สถานการณ์

ร้านค้าออนไลน์มีหน้ารายการสินค้าและหน้ารายละเอียดที่ถูกอ่านซ้ำจำนวนมาก ขณะที่การอัปเดตข้อมูลสินค้ามีน้อยกว่า การ query PostgreSQL ซ้ำทุก request เพิ่ม connection และภาระฐานข้อมูล ทีมต้องการลดการอ่านซ้ำ แต่ไม่ต้องการให้ cache กลายเป็นแหล่งข้อมูลจริง หรือทำให้หน้า Catalog แสดงข้อมูลค้างโดยไม่มีขอบเขต

ผู้เรียนจะสร้างระบบ Catalog แบบ synthetic ที่มีฐานข้อมูลเป็น source of truth, API/UI สำหรับอ่าน, เส้นทางแก้ข้อมูลที่ต้องยืนยันตัวตน และ managed Redis cache แบบ cache-aside แล้ววัดผลจาก workload ชุดเดิมก่อนและหลังเปิด cache โดยไม่ตั้งสมมติฐานว่าค่า latency จะดีขึ้นเสมอ

Solution นี้ไม่ใช้ข้อมูลลูกค้า ราคา หรือ stock สำหรับ checkout. ข้อมูลใน cache เป็น metadata ที่ยอมรับ freshness bound ได้ เช่น ชื่อ คำอธิบาย หมวดหมู่ และภาพสินค้า

## ผู้ใช้และผลลัพธ์

- ลูกค้าเปิดหน้า Catalog และอ่านรายการ/รายละเอียดสินค้าได้โดยไม่ต้องล็อกอิน
- Operator ที่ผ่าน Cloud Run IAM authentication แก้ metadata และตรวจผล invalidation ได้
- Platform operator ตรวจ cache hit/miss/error, database query count, request/error/latency และขอบเขต connection ได้
- ผู้เรียนอธิบายได้จากข้อมูลจริงว่า Cache ช่วยลด database reads หรือไม่, trade-off ที่เห็นคืออะไร และระบบตอบสนองอย่างไรเมื่อ Redis ใช้งานไม่ได้

## Requirements

| ID | Requirement | วิธีพิสูจน์ที่จะใส่ใน Guide |
|---|---|---|
| R1 | PostgreSQL เป็นแหล่งข้อมูลจริง; API อ่าน product detail และ category listing ได้ และ UI แสดง synthetic catalog | API/UI happy path, ตรวจ record/version ใน DB |
| R2 | Public service เปิดเฉพาะ read flow; การแก้ metadata ผ่าน Cloud Run service ที่ IAM-protected เท่านั้น | anonymous GET สำเร็จ, anonymous admin request ถูกปฏิเสธ, operator token ผ่าน |
| R3 | Redis ใช้ cache-aside และ key แยกตาม product/query; entry มี TTL ไม่เกิน 60 วินาที | cold request เป็น MISS, request ซ้ำเป็น HIT, ตรวจ TTL และ cache key |
| R4 | หลัง write ที่ commit สำเร็จให้ invalidate product key และ category keys ที่เกี่ยวข้อง; ถ้า invalidation ล้มเหลวต้องบันทึกผลและไม่อ้างว่า cache สอดคล้องทันที | เปลี่ยน metadata แล้ว GET สะท้อน version ใหม่; ฉีด Redis error และตรวจผล/ขอบเขต freshness |
| R5 | Redis เป็น optional dependency: connection timeout มีขอบเขต; เมื่อใช้ไม่ได้ให้อ่าน DB โดยตรงและส่งสัญญาณ BYPASS/ERROR โดยไม่รั่วข้อมูลภายใน; ถ้า DB ก็ใช้ไม่ได้ให้ตอบ 503 อย่างปลอดภัย | ทดสอบ client error, latency/error, sanitized logs, recovery |
| R6 | Cloud SQL และ Redis ไม่มี public endpoint; Cloud Run ใช้ Direct VPC egress ไปยัง VPC เดียวกัน | ตรวจ Terraform/Console config, private address และ Cloud Run revision networking |
| R7 | Cloud Run scaling และ DB connection pool มีเพดานที่วัดได้; load generator จำกัดจำนวน request และ concurrency | คำนวณ connection ceiling, ทดสอบ workload ที่ประกาศไว้, ตรวจไม่เกิน cap |
| R8 | ทดสอบ baseline แบบ cache-bypass, cold cache และ warm cache ด้วยข้อมูลและ request distribution เดียวกัน | บันทึก request count, errors, p50/p95, hit ratio และจำนวน SQL reads; แยก Expected จาก Actual |
| R9 | Change Request ปรับ policy สำหรับ category ที่เปลี่ยนบ่อย โดยเปลี่ยน TTL/invalidation อย่างมีเหตุผลและวัดผลซ้ำ | ทำ change, ตรวจ plan/revision, freshness และ trade-off เทียบ baseline |
| R10 | มี cleanup ที่ระบุ resource/data ที่ลบได้และสิ่งที่อาจยังคิดเงิน | ตรวจ destroy plan, ลบ Lab resources, บันทึกผลจริง |

## Acceptance criteria เบื้องต้น

เกณฑ์เหล่านี้เป็นเป้าหมายสำหรับออกแบบ test harness ไม่ใช่ผลที่ทดสอบแล้ว:

1. Seed data สังเคราะห์ได้ซ้ำและมี version; UI, API และ admin update แสดงค่าที่สัมพันธ์กับ DB.
2. Request ชุด baseline และ cache ใช้ seed, dataset, concurrency และจำนวน request เท่ากัน; ไม่มีการสร้าง load ที่ไม่กำหนดขอบเขต.
3. เมื่อ warm cache แล้ว hit ratio และจำนวน SQL reads เปลี่ยนไปตาม request distribution ที่กำหนด; บันทึก p50/p95 และ error rate แม้ latency จะไม่ดีขึ้น.
4. Redis connect/command error ทำให้ request ของ metadata อ่านต่อจาก DB ได้ภายใน timeout budget; ไม่มีการเสิร์ฟ stale cache โดยอ้างว่าเป็นข้อมูลปัจจุบัน.
5. Product update ปกติทำให้รายละเอียดและ category listing เห็น version ใหม่หลัง invalidation; เมื่อ Redis ขัดข้อง ให้แสดง invalidation status และระบุ stale bound ไม่เกิน TTL ที่ยังเหลือของ entry เดิม.
6. การเปลี่ยน cache policy ผ่าน change request มีผลทดสอบก่อน/หลังและอธิบายผลต่อ freshness, hit rate และ database load.

ค่าที่เสนอสำหรับ Design: 2,000 products, hot set 20 รายการรับ 80% ของ read requests, fixed-seed 500 requests, concurrency 10, timeout ของ Redis ≤ 250 ms, TTL ปกติ 60 วินาที. ต้องทวนกับ query shape, Cloud Run/DB limits และงบก่อนเขียน Task; ไม่ใช้ตัวเลขเหล่านี้เป็น performance claim.

## Architecture direction

- **Public Catalog service:** Cloud Run รับ GET/UI, runtime identity อ่าน PostgreSQL และ cache เท่านั้น; ไม่เปิด write endpoint ให้ anonymous callers.
- **Operator service:** Cloud Run แยก service, ต้องมี IAM invoker; runtime identity แยกจาก public serviceและทำ metadata update/invalidation.
- **Data tier:** Cloud SQL for PostgreSQL private IP เป็น source of truth; Memorystore for Redis เป็น cache ที่ทิ้งแล้วสร้างใหม่ได้.
- **Network:** VPC เดียวกับ subnet สำหรับ Direct VPC egress; Cloud Run route เฉพาะ private ranges เข้า VPC. Cloud SQL ใช้ private connectivity; Redis ใช้ authorized VPC/private IP.
- **Observability:** response header บอก HIT/MISS/BYPASS, structured application logs ไม่มี payload/secret, bounded load result และ Cloud Monitoring/Cloud Logging ประกอบการวิเคราะห์.
- **Region/cost starting point:** asia-southeast1 (Singapore), Cloud SQL single-zone และ Memorystore Basic Tier 1 GB เป็น baseline เพื่อศึกษา cache ที่ยอมรับ cold restart/cache flush ได้. ทั้ง SQL และ Redis มีต้นทุนตามเวลา/ขนาดแม้ไม่มี traffic; ต้องทำ Pricing Calculator/cost gate ก่อน Guide จะสั่งสร้าง.
- **HA boundary:** ไม่อ้าง HA, multi-region, durability ของ Redis หรือ production SLA. ถ้า requirement ภายหลังต้องการ Redis failover ให้เปรียบเทียบ Standard Tier และค่าใช้จ่ายเป็น extension.

## Design decisions ที่ต้องปิดก่อนเขียน Tasks

1. Cloud SQL private connectivity จะใช้ PSA หรือ PSC; เปรียบเทียบความซับซ้อนของ lab sandbox และ provider/API ที่ใช้ได้จริง.
2. Cloud Run เข้าถึง Cloud SQL ด้วย connector/IAM database authentication หรือ TCP private IP กับ credentials ที่เก็บใน Secret Manager; แยก DB roles ระหว่าง reader/operator และกำหนด pool × max instances.
3. Memorystore connection mode, Redis version, AUTH/TLS และการเก็บ CA/credential; ตั้ง network boundary และ client timeout/reconnect ให้ทำตามได้จริง.
4. กำหนด schema/index, API/UI contracts, deterministic seed, cache key naming, TTL, invalidation, cache stampede protection และ version/freshness semantics.
5. กำหนดวิธีวัด SQL reads/hit ratio/latency ที่ไม่เพิ่มภาระ logging จนบิดผล; ระบุว่า metric ใดมาจาก App, database และ Cloud Monitoring.
6. กำหนด outage exercise ที่ย้อนกลับได้และแยกการจำลอง client connection failure ออกจากการอ้างว่า Memorystore service ล่มจริง.
7. กำหนด Terraform foundation/workload gate, safe defaults, image digest, public/private IAM boundary, deletion protection, quotas และ cleanup order.
8. ตรวจ region availability, Redis minimum size, Cloud SQL machine/storage floor, cost estimate และ APIs/IAM ที่ผู้เรียนต้องมี ก่อนล็อก Task sequence.

## สถานการณ์ทดสอบที่ต้องอยู่ใน Lab

- **Normal:** seed, public browse, hot-key reads, inspect hit/miss, compare DB reads/latency.
- **Cache cold/expired:** clear namespace แบบจำกัดขอบเขตหรือรอ TTL, ตรวจ MISS แล้วเติม cache.
- **Invalidation:** operator update product/category, ตรวจ affected keys และ version ใหม่.
- **Redis connection failure:** ใช้ failure injection ที่ระบุชัดและคืน config เดิม; verify DB fallback, timeout, logs และ recovery. ห้ามลบ/stop resource เพื่อสร้าง outage โดยไม่มีแผนย้อนกลับ.
- **Database failure/connection pressure:** ใช้ test double/CI สำหรับ hard outage; ใน Cloud ใช้ safe bounded connection/availability probe โดยไม่ทำให้ instance หมด connection จริง.
- **Change Request:** category ที่อัปเดตบ่อยลด TTL จาก baseline; ทดสอบ freshness, hit ratio และ SQL reads ซ้ำ.
- **Cleanup/rebuild:** destroy เฉพาะ Lab project resources, สร้างจาก clean state ได้ และไม่ลบ resources นอก Lab.

## หลักฐานที่ผู้เรียนจะบันทึกใน README

- Architecture/region/resource versions และค่าใช้จ่ายที่คาดก่อนเริ่ม
- Terraform plan/apply summary ที่ไม่แสดง secret, Cloud Run revision และ private endpoint inventory
- seed version, request count, seed/concurrency, cache policy และ test timestamps
- baseline/cold/warm/load outputs: hit/miss/bypass, SQL reads, p50/p95, errors และ Cloud Monitoring time range
- admin IAM deny/allow, product version ก่อน/หลัง update และ invalidation result
- cache-failure fallback/recovery, sanitized logs และผล connection cap
- Change Request decision, trade-offs, cleanup verification และ case-study summary

## ขอบเขตที่ไม่รวม

- ราคาสินค้า/ยอดคงเหลือที่ใช้ยืนยันการซื้อ; checkout/order/payment
- PII, customer account, recommendation engine, CDN, global load balancing
- Redis เป็นระบบ durable หรือ source of truth; exactly-once invalidation ข้าม database/cache
- การกล่าวว่า cache ลด latency/ค่าใช้จ่ายได้เท่าใดก่อนมีผลวัดจริง
- การทดสอบ Redis service-level outage/failover จริงในงานเอกสารที่ยังไม่มี Cloud provisioning

## References used for the brief

- [Connect to a Redis instance from Cloud Run using Direct VPC egress](https://docs.cloud.google.com/memorystore/docs/redis/connect-redis-instance-cloud-run)
- [Cloud Run Direct VPC egress](https://docs.cloud.google.com/run/docs/configuring/vpc-direct-vpc)
- [Cloud SQL from Cloud Run and database connection limits](https://docs.cloud.google.com/sql/docs/postgres/connect-run)
- [Cloud SQL private IP options](https://docs.cloud.google.com/sql/docs/postgres/private-ip)
- [Private services access overview for Cloud SQL](https://docs.cloud.google.com/sql/docs/postgres/about-private-services-access)
- [Memorystore for Redis Basic and Standard tiers](https://docs.cloud.google.com/memorystore/docs/redis/redis-tiers)
- [Memorystore for Redis regions](https://docs.cloud.google.com/memorystore/docs/redis/regions)
- [Memorystore for Redis instances and capacity](https://docs.cloud.google.com/memorystore/docs/redis/instances)
- [Memorystore Redis AUTH](https://docs.cloud.google.com/memorystore/docs/redis/about-redis-auth)
- [Memorystore Redis in-transit encryption](https://docs.cloud.google.com/memorystore/docs/redis/about-in-transit-encryption)
- [Memorystore pricing](https://cloud.google.com/memorystore/docs/redis/pricing)
- [Cloud SQL pricing](https://cloud.google.com/sql/pricing)
- [Terraform google_redis_instance resource](https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/redis_instance.html)
