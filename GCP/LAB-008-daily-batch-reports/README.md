---
lab: LAB-008
platform: GCP
guide_status: brief
cloud_verification: not-run
last_verified: null
---
# Lab 08 — รายงานยอดขายรายวันและ Batch ที่รันย้อนหลังได้

## สถานการณ์

ทีมปฏิบัติการและการเงินต้องได้รับรายงานสรุปยอดขายของวันทำการก่อนเริ่มงานเช้า ข้อมูลต้นทางอาจมาช้า, Scheduler อาจเรียกซ้ำ, Job อาจล้มหลังเขียนไฟล์แล้ว หรือมีคนสั่งรันวันเดิมพร้อมกัน ทีมต้องเห็นว่าวันใดสำเร็จ/ขาดหาย แยกความล้มเหลวของรอบงานออกจากข้อมูลธุรกิจ และรันย้อนหลังได้โดยไม่สร้างรายงานหรือแจ้งเตือนซ้ำอย่างเงียบ ๆ

Solution นี้ชื่อ **Daily Sales Close** ใช้ข้อมูลสังเคราะห์ ไม่เชื่อมระบบบัญชีหรือรับชำระเงินจริง เป้าหมายคือรายงานที่ผูกกับ business date และ source version ที่พิสูจน์ย้อนกลับได้ ไม่อ้าง SLA หรือความตรงเวลาที่ไม่ได้วัด

**สถานะ:** Brief — กำหนดโจทย์และเกณฑ์รับมอบแล้ว; Architecture, App, Infrastructure, Diagram และ Tasks ยังไม่เริ่ม จนกว่าจะปิด Design. ไม่มี GCP resources ถูกสร้าง และ Cloud verification เป็น Not run.

## ผู้ใช้และผลลัพธ์ที่ต้องได้

- ทีม Finance เปิดรายงานตาม business date และตรวจจำนวนรายการ/ยอดรวมกับข้อมูลต้นทางได้
- Operator เห็นสถานะและสาเหตุของรอบที่สำเร็จ, ล้มเหลว, ค้าง หรือยังไม่มีรายงาน และสั่ง backfill วันที่ระบุได้
- Platform team แยกผู้เรียก Scheduler, coordinator, Job และ notification consumer ตามหน้าที่
- ทีม downstream รับสัญญาณ report-ready พร้อม report ID ที่ใช้ deduplicate ได้

## Requirements และเกณฑ์รับมอบ

| ID | Requirement | หลักฐานที่ต้องเก็บ |
|---|---|---|
| R1 | Daily schedule ใช้ timezone และ logical business date ที่กำหนด ไม่คำนวณวันจากเวลาที่ Job เริ่มจริง | scheduled timestamp, timezone, business date; ทดสอบขอบวัน/เดือน/ปีและ invocation ซ้ำ |
| R2 | รับเฉพาะ synthetic CSV ตาม schema และเพดานที่ประกาศ | source object generation/hash, row count, invalid-row result, input size |
| R3 | สรุป count/ยอดเงินแบบจำนวนเต็มและสร้าง output ซ้ำได้จาก source version เดิม | input/output hashes, total rows, amount totals, reconciliation |
| R4 | Overlap, Scheduler retry และ Cloud Run task retry ไม่สร้างผลรายงานซ้ำหรือเขียนทับไฟล์ที่ไม่ตรงกัน | duplicate execution, lease/state history, object generation/precondition และผลก่อน/หลัง retry |
| R5 | ตรวจพบ source ที่มาช้า, scheduled run ที่ไม่มีรายงาน และ job failure; Operator ทำ backfill วันที่เดิมได้ | ledger/status, execution/log IDs, late-source recovery และการตรวจ output ก่อน/หลัง backfill |
| R6 | ส่ง report-ready event หลัง report ถูกจัดเก็บ; event ที่ตอบรับไม่แน่นอนต้อง recover ได้โดยใช้ event identity เดิม | topic/message attributes, report ID, notification state และ duplicate-consumer scenario |
| R7 | จำกัด IAM ตาม role: Scheduler เรียก coordinator; coordinator สั่งรันเฉพาะ Job; Job อ่าน input/เขียน output/ledger/notification เท่าที่ต้องใช้ | principal/role matrix, unauthorized/authorized calls, bucket/database scope |
| R8 | จำกัด rows, bytes, execution time, retry และ backfill concurrency ก่อนทดสอบ | configured limits, expected upper bounds, billing/cost notes และ backout |
| R9 | ส่งมอบ runbook, case-study evidence และ cleanup/rebuild ที่ไม่อ้างผล Cloud หากไม่ได้รัน | sanitized logs/evidence, known limitations, cleanup inventory และ Not run fields |

## ขอบเขตตั้งต้น

- หนึ่งรายงานต่อ business date ใน timezone Asia/Bangkok; schedule ตั้งต้น 01:15 และรายงานวันปฏิทินก่อนหน้า เมื่อ source data พร้อมก่อน cutoff ที่ Design กำหนด.
- ข้อมูลสังเคราะห์ CSV เท่านั้น; เพดานตั้งต้น 5 MiB และ 5,000 แถวข้อมูลต่อวัน, ไม่ใส่ PII, ใช้จำนวนเต็มสตางค์และ fail closed เมื่อ schema/ตัวเลขผิด.
- Run หลักเป็น Cloud Run Job งานเดียวต่อ business date; เปลี่ยนเป็น backfill หลายวันแบบ bounded concurrency เป็น Change Request ไม่เริ่มด้วยการประมวลผลขนานไม่จำกัด.
- ไม่มี BigQuery, data warehouse, external email API หรือการเชื่อมระบบ production จริงใน baseline; มี report-ready event สำหรับ downstream และแจ้งเหตุผ่าน monitoring ที่ปิดขอบเขตได้.
- แยก run retry, schedule retry, backfill และ business date ออกจากกัน; ไม่มีข้ออ้างว่าการ retry ของบริการทำให้ exactly-once.

## แนวทาง Solution ที่จะปิดใน Design

1. วาง Cloud Scheduler แบบ authenticated OIDC ให้เรียก coordinator ที่ IAM-protected; coordinator ใช้ timestamp ของรอบ Scheduler ที่มากับ request เพื่อหาวันรายงานใน timezone ที่กำหนด แล้วส่ง business date เป็น argument ให้ Cloud Run Job.
2. เตรียม source object แยกตาม business date ใน Cloud Storage. Job อ่าน object generation ที่ตรวจแล้วและคำนวณรายงานแบบ deterministic.
3. ใช้ Firestore ledger ต่อ business date เพื่อ claim/lease/fence งานและติดตามขั้นตอน; output เขียนเป็น object แบบ create-only. ถ้ามี output อยู่แล้วต้องอ่าน/ตรวจ source binding และ hash ก่อน reuse; ห้ามเขียนทับความขัดแย้ง.
4. บันทึกสถานะ notification-pending หลัง report ถูกยืนยัน แล้ว publish Pub/Sub report-ready event ด้วย report ID คงที่ก่อน mark complete. หาก publish/response ไม่ทราบผล ให้ retry ด้วย identity เดิม; consumer ต้อง deduplicate และไม่มี exact-once claim.
5. Operator ตรวจ scheduled timestamp, business date, source/output generation, ledger และ Job execution ได้; หาก source มาช้าหรือรอบหาย ให้เติม input ที่ถูกต้องและสั่ง backfill เฉพาะ business date เดิม.

รายละเอียดเหล่านี้เป็นทิศทางตั้งต้น ไม่ใช่การยืนยันว่า API/IAM/state transition ถูกปิดแล้ว Design ต้องตัดสินใจเรื่อง Cloud Run Job override permission, Scheduler retry contract, lease expiry/fencing, notification recovery, retention และ alarm ก่อนเขียนโค้ดหรือคู่มือ Tasks.

## Failure และ Change Request

| สถานการณ์ | สิ่งที่ต้องพิสูจน์ |
|---|---|
| Source มาหลังเวลาตัดรอบ | รายงานไม่ปลอมว่าเป็น empty; status แสดง missing input และ backfill หลัง upload สร้างผลที่ผูก generation ได้ |
| Schedule ถูก retry หรือ header/timezone ผิด | logical date มาจาก schedule time ที่ตรวจรูปแบบและ timezone ไม่ใช่ wall clock ตอนประมวลผล |
| Job ตายหลังเขียน report แต่ก่อน notification | retry ตรวจ artifact เดิม, ไม่เขียนทับ และกู้ pending notification ด้วย report ID เดิม |
| Job วันที่เดียวกันทำงานซ้อน | มีผู้ claim ที่ถูกต้องเพียงรายเดียว; contender บันทึก already-running/completed ตาม state ที่พิสูจน์ได้ |
| CSV ผิด schema หรือเกินเพดาน | หยุดแบบ fail-closed, ระบุ reason code ที่ปลอดภัย และไม่ปล่อย report-ready event |
| Change Request: รายงานย้อนหลังหลายวัน | เพิ่ม backfill window ที่จำกัดจำนวนวันและ concurrency, แสดง partial success, หยุด/ต่อได้ และประเมินต้นทุนก่อนเริ่ม |

## จุดบันทึกผลงาน

ผู้เรียนจะบันทึก timezone/cron และเหตุผล, service identity matrix, input fixture/hash, run ID และ business date, output generation/hash และ reconciliation, ledger transitions, retry/overlap/fault/backfill outcomes, notification event identity, metric/log windows, ค่าใช้จ่ายโดยประมาณและข้อจำกัด. ห้ามบันทึก credentials, access tokens หรือข้อมูลผู้ใช้จริง.

## ประเด็นที่ต้องปิดก่อนเริ่ม Materials

1. Schedule timezone/date contract รวมถึง manual Scheduler invocation และวิธีไม่พึ่งเวลาปัจจุบันของ coordinator.
2. Cloud Run Job API call แบบมี overrides, least-privilege `run.jobs.runWithOverrides` และการตอบกลับ/unknown operation ของ coordinator.
3. Firestore ledger state machine, transaction/lease/fence, attempt budget และ recovery เมื่อ lease หมด.
4. Cloud Storage input generation และ output create-only verification, conflict policy และ lifecycle/retention.
5. Notification outbox/event recovery และวิธีทดสอบ duplicate/unknown publish โดยไม่พึ่ง service doubles เป็นหลักฐาน Cloud.
6. Scheduler retry vs Cloud Run Job task retry: ขอบเขต, จำนวน, backoff, duplicate executions และ operator actions.
7. Status/alert path สำหรับ missed run, source missing และ failed execution; กำหนด metric/log/notification ที่ทำได้จริง.
8. Batch/Backfill concurrency, size/time limits, cost ceiling, cleanup ordering และ resource protection.

## เอกสารอ้างอิงสำหรับ Design

- [Cloud Scheduler cron และ timezone](https://docs.cloud.google.com/scheduler/docs/configuring/cron-job-schedules), [HTTP target headers](https://docs.cloud.google.com/python/docs/reference/cloudscheduler/latest/google.cloud.scheduler_v1.types.HttpTarget), [OIDC authentication](https://docs.cloud.google.com/scheduler/docs/http-target-auth), [retry policy](https://docs.cloud.google.com/scheduler/docs/configuring/retry-jobs)
- [Cloud Run Jobs](https://docs.cloud.google.com/run/docs/create-jobs), [execute/override job arguments](https://docs.cloud.google.com/run/docs/execute/jobs), [Cloud Run IAM permissions](https://docs.cloud.google.com/run/docs/reference/iam/permissions)
- [Cloud Storage request preconditions](https://docs.cloud.google.com/storage/docs/request-preconditions), [Firestore transaction contention](https://docs.cloud.google.com/firestore/native/docs/transaction-data-contention), [Pub/Sub delivery model](https://docs.cloud.google.com/pubsub/docs/subscription-overview)

ก่อนเขียน Materials/Tasks ให้ตรวจเอกสาร official ซ้ำกับ API/IAM/region ที่เลือก และจัดทำ Diagram จาก implementation design ที่ปิดแล้ว; Brief นี้ยังไม่ใช่คู่มือให้ deploy.