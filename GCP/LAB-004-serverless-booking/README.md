---
lab: LAB-004
platform: GCP
guide_status: design
cloud_verification: not-run
last_verified: null
---
# Lab 04 — Booking บน Cloud Run ที่ข้อมูลคงอยู่และไม่จองเกินความจุ

ทีมบริการต้องให้ผู้ใช้ดูช่วงเวลา จอง และยกเลิกการจองได้ผ่าน HTTPS เมื่อ Deploy revision ใหม่ข้อมูลต้องยังอยู่ และการเพิ่ม concurrency ต้องไม่ทำให้จองเกินจำนวนที่รับได้หรือเปิด DB connections จนเต็ม

## Requirements และ Acceptance

| ID | ความต้องการ | วิธีพิสูจน์ / หลักฐาน |
|---|---|---|
| R1 | ผู้ใช้ login และทำ booking journey ผ่าน HTTPS | Browser login → list slots → reserve → view own booking → cancel; HTTP/status/request IDs และ DB rows จริง |
| R2 | แยก App user ออกจาก Cloud IAM | ไม่มี session ได้401, ผู้ใช้หนึ่งอ่าน/ยกเลิกของอีกคนไม่ได้, role operator ตาม scope; runtime SA/deployer/invoker มีหน้าที่คนละส่วน |
| R3 | ไม่จองเกิน capacity และ retry ไม่ซ้ำ | ยิงคำขอพร้อมกันแบบจำกัด, retry keyเดิม, ตรวจ confirmed bookings ต่อ slot ไม่เกิน capacity และ cancellation คืนที่นั่งครั้งเดียว |
| R4 | ข้อมูลอยู่ข้าม revision และ rollback | จองบน v1 → Deploy v2 → อ่านรายการเดิม → ชี้ traffic กลับ v1 → อ่าน/ยกเลิกได้ โดย schema ยังเข้ากัน |
| R5 | DB private และ Secret เข้าถึงเฉพาะ runtime | Cloud SQL ไม่มี public IP; Cloud Run ต่อ private IP ผ่าน Direct VPC + connector; SA ไม่เกี่ยวข้องอ่าน secret ไม่ได้; ไม่ใส่ password ใน image/Repo/logs |
| R6 | หมุน DB credential อย่างควบคุม | เตรียม login B/grantsเท่ากัน + secret versionใหม่, deploy revisionใช้B, verify, ถอนAหลังไม่เหลือtraffic/connection; บันทึก rollback boundary ไม่สัญญาว่า old credential ยังใช้ได้หลัง revoke |
| R7 | เพิ่ม concurrency โดยคง data/connection safety | เปลี่ยน8→16, pool4/instance, max instanceตามขอบเขต; วัด request/error/latency + active DB connections และ business invariants ก่อน/หลัง |
| R8 | Dependency fault/recovery และ Cleanup | ตั้ง config/DB access ที่ผิดแบบจำกัดบน no-traffic revision, ตรวจhealth/logs แล้วแก้; ลบ Run/SQL/secrets/images/VPC/PSA ตาม inventory และบันทึก rebuild commit |

## Architecture และขอบเขตที่เลือก

- Singapore region, Cloud Run service เดียวให้ UI/API ด้วย managed run.app HTTPS endpoint ไม่ต้องมี domain หรือ LB เพิ่ม
- Cloud SQL PostgreSQL 16, Enterprise edition, private services access (PSA), **ไม่มี public IP**; baseline single-zone ไม่อ้าง database HA ซึ่งจะเจาะใน Lab 05
- Custom VPC และ regional subnet สำหรับ Direct VPC egress; PSA allocated range เป็น service-producer allocation ไม่ใช่ subnet ของ VM
- Cloud SQL Python Connector ใช้ private IP และจัดการ TLS/instance identity; connector ไม่สร้าง network path ให้เอง ต้องมี Direct VPC/PSA จริง
- Runtime service account เฉพาะ Lab มี Cloud SQL Client และ Secret Accessor เฉพาะ secret ที่ต้องใช้ ไม่ใช้ default Compute SA หรือ project-wide Editor
- Secret Manager เก็บ DB login configuration, demo user password hashes และ session signing key ใช้ versionที่ pin ชัดสำหรับแต่ละ revision ไม่ใช้ latest แบบอธิบายผล rotation ไม่ได้
- Container images ใน Artifact Registry; Dockerfile/runtime code/schema/seed/probes อยู่ใน Lab นี้ ไม่พึ่ง resource ของ Lab ก่อน

## Identity และ Browser flow

เลือก public Cloud Run entry สำหรับหน้า login แต่ทุก business endpoint ต้องผ่าน App session/role/ownership checks Public invoker ไม่ใช่การเปิดข้อมูล booking และไม่ใช่หลักฐานว่า IAM ยืนยัน end user ให้

App ใช้ demo users/booker/operator, password hashes, HttpOnly Secure SameSite cookies, session expiry และ CSRF สำหรับ state-changing requests บน HTTPS แยก deployer IAM, runtime service identity และ App identity อย่างชัดเจน ไม่อ้างว่า demo login เป็น enterprise SSO หาก organization ห้าม public invoker ให้หยุด baselineและออกแบบทางเข้าใหม่โดยไม่ปิด policy

ไม่ทำ UI ที่เก็บ DB password หรือ privileged token ใน browser, URL query, localStorage หรือ screenshot หลักฐานต้อง redact cookie/secret values

## Business data และ App contract

เตรียม slots อย่างน้อย5ช่วงพร้อม capacity, usersสองคนและoperator, bookings/status/idempotency/audit fields มี transaction/row lock หรือ conditional mutationที่พิสูจน์ invariantได้ UI รองรับ list/reserve/cancel และแสดง booking reference/request ID ไม่ให้ผู้เรียนไปคิด App ใหม่

มี /livez ตรวจ process, /healthz ตรวจDB/schema และ structured request/dependency logs แบบไม่เผย credentials การ pool ต้องปิด connectionกลับpoolครบเมื่อexception มี bounded wait/statement timeouts ไม่สร้างunbounded reconnect loop

v1/v2 ใช้ schema compatible กันใน baseline ไม่ยัด destructive migration ลง rollback demo การเปลี่ยน schemaในอนาคตต้องแยก expand/contract และบอก boundary ก่อน deploy

## Connection budget และต้นทุนก่อนลงมือ

เริ่ม concurrency8, application poolสูงสุด4ต่อinstanceและ max instance2 เป็นค่าฝึก ไม่ใช่ capacity recommendation สำหรับ production ระหว่าง rollout อาจมีหลาย revision/instanceและแพลตฟอร์มอาจเกินเป้าชั่วคราว จึงคำนวณเผื่อ old+new revisions, admin connections และ monitor pg_stat_activity ไม่อ้าง max-instances เป็น hard cap ของ DB connections

Cloud SQL คิดค่าใช้จ่ายแม้ Run scale-to-zero; มี storage/backup/PSA/Artifact Registry/Secret/egress/logs ตามใช้ เลือกmachine/region/edition/quotaและเวลาปิดใน Guide ก่อนสร้าง Budgetเป็นalert ไม่ใช่hard cap งานจัดทำเอกสารนี้ไม่ provision GCP resources

## Rotation และ Failure drill ที่ต้องออกแบบให้ครบ

DB credential rotation ใช้สอง loginชั่วคราว A/B เพื่อให้ revisionเก่ากับใหม่ทำงานคู่กันได้โดยไม่ reset passwordของloginที่ยังรับงานทันที หลัง verifyB แล้วค่อย retireA หาก revokeAแล้วต้องกู้ด้วยlogin/secretที่ยังvalid ไม่ใช่blind traffic rollback

Fault ใช้ revisionที่ไม่รับ production traffic ใน sandboxและมีtagสำหรับทดสอบจำกัด ไม่ทำลายDBเพื่อให้มีincident ต้องบันทึกerror/สาเหตุ/การแก้/retestจริง พร้อมลบfault revisionตอนปิดงาน

## ลำดับหลัง Brief

ยืนยัน identity/network/schema/rotation/connection budget → working App + PostgreSQL integration tests + container → deployment/IaC materials → Diagramตามscopeจริง → READMEพาทำครบjourney/negative/ops/change/cleanup → Review/render/Guide-ready

สถานะ Design / Materials: มี App UI/API, schema/seed/invariants, bounded pool, secret generator, bootstrap/grants และ Dockerfile พร้อม PostgreSQL integration tests กำลังตรวจ cloud CI ยังไม่มีคู่มือ Deploy เต็มหรือผล GCP จริง

ไฟล์ประกอบ: [App](app/main.py), [DB pool/connector](app/database.py), [UI](app/templates/index.html), [schema](db/schema.sql), [seed](db/seed.sql), [grants](db/grants.sql), [invariants](db/check-invariants.sql), [secret generator](scripts/create-secrets.py), [bootstrap](scripts/init-db.py), [tests](tests/test_booking.py)

App pool4/max_overflow0, pool wait3s, statement5s, lock3s ใช้ Gunicorn1worker/16threads ทำให้จำนวน pool ต่อ instanceชัด ไม่เพิ่ม workers โดยไม่คูณ connection budget Runtime DB logins booking_a/booking_b ไม่มี superuser/DDL/delete-ledger ส่วน admin bootstrap เป็น jobแยก ไม่ใช้ credentialเดียวกับ App

## แหล่งอ้างอิงขอบเขต

- [Cloud Run Direct VPC egress](https://docs.cloud.google.com/run/docs/configuring/vpc-direct-vpc)
- [Cloud SQL private services access](https://docs.cloud.google.com/sql/docs/postgres/configure-private-services-access)
- [Cloud Run Secret Manager integration](https://docs.cloud.google.com/run/docs/configuring/services/secrets)
