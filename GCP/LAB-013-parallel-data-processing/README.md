---
lab: LAB-013
platform: GCP
phase: design
guide_status: design
cloud_verification: not-run
last_verified: null
---

# Lab 13 — ระบบนำเข้าข้อมูลแบบขนาน

> **สถานะ: Design checkpoint** — เอกสารนี้ล็อกโจทย์ ข้อกำหนด และแบบสถาปัตยกรรม ยังไม่มีคู่มือ Task, application/worker, Terraform หรือผลทดสอบ Cloud

## สถานการณ์

ทีม data operations ได้รับไฟล์รายการสินค้าจำลองจากหลายแหล่งทุกวัน ชุดข้อมูลใหญ่ใช้เวลาประมวลผลบนเครื่องเดียว และเมื่อ worker บางส่วนล้มเหลว ทีมยังแยกไม่ออกว่าส่วนใดสำเร็จแล้ว ส่วนใดต้อง retry และผลที่มีอยู่ครบพอให้ระบบถัดไปใช้งานหรือยัง

ทีมต้องการระบบประมวลผลแบบขนานที่ตรวจสอบย้อนกลับได้ จำกัดการใช้ทรัพยากร และห้ามส่งผลบางส่วนให้ consumer เข้าใจผิดว่าเป็นข้อมูลครบชุด ข้อมูลใน Lab นี้เป็น synthetic product records เท่านั้น ห้ามใส่ข้อมูลลูกค้า ผู้ขายจริง หรือข้อมูลอ่อนไหว

**ผู้ใช้หลัก:** Cloud/Data Platform Engineer ที่รับผิดชอบการรัน batch และ on-call เมื่อข้อมูลนำเข้าบางส่วนล้มเหลว

**ผลลัพธ์เมื่อทำ Lab ครบ:** ส่งชุดข้อมูลเข้า → แบ่งเป็น shard ที่ตรวจ hash ได้ → ประมวลผลด้วย Cloud Batch แบบจำกัด concurrency → เทียบยอด input/output → ทดลอง retry และ partial failure → publish completion manifest เมื่อครบเท่านั้น → ทำ Change Request และเก็บหลักฐานจริง

## เป้าหมายและเกณฑ์ยอมรับ

| ID | Requirement | หลักฐานที่ต้องได้เมื่อทำ Lab |
|---|---|---|
| R1 | รับเฉพาะ synthetic input ที่มี manifest ระบุ shard, จำนวนแถว และ SHA-256; input bucket เป็น private | manifest, object metadata และผลตรวจ hash ก่อน submit |
| R2 | แบ่งหนึ่ง task ต่อ shard โดยกำหนดเพดาน parallelism และ task timeout ชัดเจน | Batch job configuration, task index ↔ shard mapping และเวลารันจริง |
| R3 | Worker ทำงานใน private subnet, ไม่มี external IP, ไม่ใช้ service-account key และใช้ image ที่ pin ด้วย digest | Terraform plan/state ที่ปกปิดข้อมูล, VM/job config และ image digest |
| R4 | Worker อ่านได้เฉพาะ input bucket และสร้าง output ได้เฉพาะ attempt-output bucket; publisher เขียน completion manifest ไปอีก bucket | IAM policy, object paths และ negative access checks ของ worker/publisher |
| R5 | ส่ง structured logs ไป Cloud Logging พร้อม run ID, shard/task index, retry attempt และผลลัพธ์ | Logs Explorer query/JSON log record และ job/task status |
| R6 | จำลอง transient failure ที่ retry ได้แบบมีขอบเขต และ malformed input ที่ fail แบบไม่ retry | lifecycle policy, task attempts และ error code/log ที่สอดคล้อง |
| R7 | เมื่อมี shard ล้มเหลว ให้สร้าง partial report ได้ แต่ห้ามสร้าง completion manifest | failed job status, partial report และยืนยันว่า published bucket ไม่มี manifest |
| R8 | Recovery ต้องเริ่ม run ใหม่และ reconcile ทุก shard จาก manifest ไม่ถือว่า retry เท่ากับ exactly-once | run IDs, reconciliation summary และ attempt handling evidence |
| R9 | ทำ Change Request จาก 8 shards × 1,000 records, parallelism 2 เป็น 16 × 1,000, parallelism 4; บันทึกเวลาจริง, attempts, resource shape และราคาอ้างอิง | ตาราง before/after จากผลที่รันจริงและ cost estimate พร้อมวันที่/สมมติฐาน |
| R10 | สร้าง summary เป็นไฟล์ HTML ในเครื่องผู้เรียนหรือ Cloud Shell โดยไม่ deploy website และทำ cleanup ได้ตาม inventory | HTML report, resource inventory ก่อน/หลัง cleanup และค่าใช้จ่ายที่อาจค้าง |

ตัวเลขใน R9 เป็น **ขนาด fixture และค่าตั้งต้นของโจทย์** ไม่ใช่ benchmark หรือผลลัพธ์ที่รับรองไว้ล่วงหน้า การเพิ่มจำนวน shard และ parallelism พร้อมกันทำให้ผลเทียบไม่สามารถสรุปว่าเปลี่ยนตัวแปรใดตัวแปรหนึ่งเป็นสาเหตุของเวลาที่ต่างกันได้ ผู้เรียนต้องบันทึกข้อจำกัดนี้ใน case study

## แบบ Solution

![สถาปัตยกรรมระบบประมวลผลข้อมูลแบบขนาน](assets/solution.svg)

ไฟล์ดูภาพแบบ standalone: [assets/solution.html](assets/solution.html)

### องค์ประกอบและขอบเขต

| องค์ประกอบ | หน้าที่ | ขอบเขตที่ต้องรักษา |
|---|---|---|
| Cloud Build | ทดสอบและ build worker container | build จาก source ใน repo; ไม่ถือว่า build ผ่านจนมีผลจริง |
| Artifact Registry | เก็บ worker image | worker อ้าง image ด้วย digest ไม่ใช้ mutable tag เป็นตัวระบุ deployment |
| Cloud Batch | จัดตาราง task, concurrency, timeout และ retry | จำกัดจำนวน task พร้อมกันและจำนวน retry; เก็บ task status แยกจาก report |
| Compute Engine VM ที่ Batch จัดการ | รัน container worker ใน private subnet | ไม่มี external IP; ใช้ custom runtime service account; ไม่สร้าง key |
| Input Cloud Storage bucket | เก็บ shards และ manifest ต้นฉบับ | private, immutable สำหรับ run; worker อ่านได้อย่างเดียว |
| Attempt-output Cloud Storage bucket | เก็บผลแยก run/shard/attempt | worker สร้าง object ได้; ไม่ลบหรือแก้ source/attempt อื่น |
| Published-manifest Cloud Storage bucket | เก็บ completion manifest สำหรับ consumer | publisher เป็นผู้สร้างหลัง reconcile ผ่าน; worker ไม่มีสิทธิ์เขียน |
| Cloud Logging | รวม log ของแต่ละ task | เปิด Cloud Logging destination ใน Batch logs policy และใส่ correlation fields ที่กำหนด |
| Operator CLI | submit/inspect job, reconcile และสร้าง HTML summary | ใช้ user identity ผ่าน gcloud; report เป็นไฟล์เฉพาะที่ ไม่เปิด public endpoint |

Cloud Storage buckets อยู่นอก VPC แต่จำกัดด้วย IAM และ bucket policy; worker เข้าถึง Google APIs ผ่าน Private Google Access. Cloud Logging เป็นบริการระดับ project จึงอยู่นอกกรอบ regional resources ใน Diagram. Compute Engine worker VMs อยู่ใน subnet; Cloud Batch เป็น control plane ที่จัดสรร VM ให้ job. Resource ที่ออกแบบเป็น regional ให้เริ่มที่ asia-southeast1; ตอนเขียน Guide ต้องตรวจ location support, quota และ project policy ล่าสุดอีกครั้ง

### Data และ execution flow

1. สร้าง synthetic records แบบ deterministic แล้วแบ่งเป็น shards; เขียน manifest ที่บันทึก run ID, object path, record count, schema version และ SHA-256 ของแต่ละ shard
2. ตรวจ hash/count ก่อน submit; วาง source objects ใน private input bucket และห้ามแก้ object ระหว่าง run
3. Cloud Build สร้าง worker image แล้ว push เข้า Artifact Registry; job ใช้ image digest ที่ตรวจกลับได้
4. Operator ส่ง Cloud Batch job โดย task index map ไปยัง shard index เดียวกัน พร้อมกำหนด max parallelism, task timeout, lifecycle policy, network และ runtime service account; BATCH_TASK_INDEX map ไปยัง shard ส่วน BATCH_TASK_RETRY_ATTEMPT บันทึก attempt ที่กำลังทำ
5. Worker ตรวจ shard ตาม manifest, validate/normalize records และเขียนผลไปยัง attempt-output path ที่รวม run ID, shard index และ retry attempt เพื่อไม่เขียนทับ attempt อื่น
6. Worker ส่ง structured log; operator ตรวจสถานะ job, task, attempts, output object hash และ row counts
7. ถ้ามี task ล้มเหลว ให้สร้าง partial report สำหรับวิเคราะห์ได้ แต่ห้ามออก completion manifest
8. เมื่อทุก shard ผ่านและ reconciliation ครบ publisher จึงสร้าง completion manifest เป็น gate ให้ consumer; downstream ต้องตรวจ manifest นี้ ไม่เดาว่า prefix ที่มีบาง object แปลว่าข้อมูลครบ

Batch retries มี semantics แบบ at-least-once; design นี้ **ไม่อ้าง exactly-once execution**. การแยก output ต่อ attempt ลดการเขียนทับ ส่วน publisher เลือกผลที่ผ่านการตรวจและประกาศชุดข้อมูลครบเพียงเมื่อ reconcile ผ่าน

### Identity และ IAM design

| Principal | สิทธิ์ที่ตั้งใจให้ | ขอบเขต/ข้อห้าม |
|---|---|---|
| Operator user | Batch Job Editor, Service Account User เฉพาะ runtime/publisher identities, Logging Viewer และสิทธิ์จัดการ input/output ที่คู่มือจะระบุ | ไม่ใช้ Owner/Editor ทั้ง Project โดยไม่จำเป็น |
| Cloud Build service account | เขียน image ไปยัง Artifact Registry repository ที่กำหนด | ไม่ได้สิทธิ์อ่าน input data หรือเขียนผล Batch |
| Runtime service account | Batch Agent Reporter, Logs Writer, Storage Object Viewer เฉพาะ input bucket, Storage Object Creator เฉพาะ attempt-output bucket | ไม่มีสิทธิ์ลบ/แก้ input หรือเขียน published manifest |
| Publisher identity | อ่านสถานะ job และ attempt outputs เพื่อ reconcile; Storage Object Creator เฉพาะ published-manifest bucket | ไม่ใช้เป็น worker identity และไม่รัน container |
| Cloud Batch service agent | service-agent role ที่ Google จัดการให้ | ไม่มอบ service-agent role ให้ worker |

การแยก bucket ทำให้ worker ไม่มีสิทธิ์สร้าง completion manifest โดยไม่ต้องพึ่ง prefix condition ภายใน bucket เดียว การตั้งค่า Terraform ต้องพิสูจน์ขอบเขตด้วย negative access check จริงใน Lab ส่วนการ grant role ที่จำเป็นต่อ service agent ให้เป็นไปตามขั้นตอน enable service/API ของ Google Cloud; ห้ามสร้าง key ให้ service account

ชื่อ role/permission, API, quota, Batch machine configuration, region support และราคาจะทวนกับเอกสารทางการอีกครั้งก่อนเขียนขั้นตอนละเอียด เพราะเปลี่ยนตามบริการและ project policy ได้

## Failure, Recovery และ Change Request

### Operational scenarios

- **Transient worker fault:** worker คืน exit code 75 สำหรับ transient fault; lifecycle policy ใช้ RETRY_TASK เฉพาะ code 75 และ maxRetryCount = 1 (retry ได้หนึ่งครั้งหลัง initial attempt); exit code อื่น เช่น code 65 สำหรับ malformed data ไม่ retry ตามเงื่อนไข FAIL_TASK/default; attempt ใหม่เขียนคนละ object path
- **Permanent data fault:** malformed shard คืน exit code ที่กำหนดเป็น non-retryable; lifecycle policy ระบุให้ fail โดยไม่ retry; partial report แสดง shard ที่ขาด
- **Partial output:** job ไม่สำเร็จหรือ object/hash/count ไม่ครบ; publisher ปฏิเสธการสร้าง completion manifest
- **Recovery:** แก้ synthetic source/config แล้วสร้าง run ID ใหม่; ตรวจทุก shard ใหม่จาก manifest; เปรียบเทียบ failed run กับ recovered run และเก็บหลักฐานทั้งคู่
- **Resource cleanup:** ตรวจ Batch jobs/VMs, buckets, image repository และ logs; เก็บเฉพาะหลักฐานที่จำเป็นก่อนลบ resource ที่สร้างใน Lab

exit code และวิธีฉีด fault จะยืนยันตอน implementation โดยต้องพิสูจน์ retry behavior ตาม Cloud Batch lifecycle policy จริง ไม่ถือว่าเลข exit code อย่างเดียวรับรองการ retry

### Change Request

ทีมเพิ่ม input จาก 8 เป็น 16 shards โดยยังคง 1,000 records ต่อ shard และขอเพิ่ม parallelism จาก 2 เป็น 4 เพื่อประเมินผลกระทบ ผู้เรียนต้องบันทึกเวลาเริ่ม/จบจาก job จริง, จำนวน task attempts, machine shape, จำนวน VM ที่สังเกตได้, ปริมาณ input/output และราคาอ้างอิงพร้อมวันที่/สมมติฐาน

ผลนี้เป็นการสังเกตใน environment ของผู้เรียน ไม่ใช่ load benchmark ทั่วไป และเพราะขนาดงานกับ concurrency เปลี่ยนพร้อมกัน จึงห้ามสรุป causal effect ของ parallelism จากตัวเลข before/after เพียงชุดเดียว

### Trade-offs ที่ต้องตัดสินใจ

- จำนวน shard มากขึ้นช่วยกระจายงานแต่เพิ่ม task scheduling, log และ object overhead
- parallelism สูงขึ้นอาจลด elapsed time แต่ใช้ VM พร้อมกันและค่าใช้จ่ายสูงขึ้น
- retry ช่วย fault ชั่วคราวแต่กินเวลา/ทรัพยากรเพิ่ม และต้องออกแบบ idempotency/output paths
- ไม่มี external IP ลดพื้นผิวเครือข่าย แต่ต้องยืนยัน Private Google Access, API enablement และการดึง image ผ่าน Google APIs
- attempt-scoped output เพิ่มความสามารถในการตรวจสอบ แต่ต้องมี cleanup/retention เพื่อป้องกัน object สะสม
- Cloud Batch ไม่มีค่าบริการ orchestration แยก แต่ VM, disk, Cloud Storage, Artifact Registry, network egress และ Cloud Logging อาจคิดค่าบริการ; ตรวจราคา/region และประมาณค่าใช้จ่ายก่อนรันทุกครั้ง

## หลักฐานที่จะบันทึกระหว่างทำ

Guide-ready version จะวางช่องบันทึกไว้ติดกับแต่ละ checkpoint ใน README เดียว: project/region (ปกปิด ID ตามเหมาะสม), run ID, image digest, manifest hash/count, Batch job/task status, attempts, machine shape, Cloud Logging query/result, input/output reconciliation, partial-failure proof, recovery run, Change Request measurements, cost estimate source/date, HTML summary และ cleanup inventory

**ห้ามกรอก Expected เป็น Actual แทนผลจริง.** ภาพหน้าจอ/Logs ต้องมาจากการรันของผู้เรียนและลบข้อมูลส่วนตัว/IDs ที่ไม่ต้องเผยแพร่ก่อน commit

## Scope ของ checkpoint นี้

- รวมโจทย์, acceptance criteria, architecture, data flow, identity boundary, fault/change/cost/evidence design และ official references
- ยังไม่มี Task guide, click-by-click instructions, scripts, app, Terraform หรือ GCP resource
- CI ที่เกี่ยวข้องตรวจ design contract, SVG/HTML, icon provenance และ diagram rendering; CI ไม่ได้ provision หรือยืนยันพฤติกรรม Cloud
- Cloud verification: **Not run**; checkpoint นี้ไม่ได้สร้าง GCP resources

## เอกสารทางการอ้างอิง

- [Cloud Batch: create a basic job](https://docs.cloud.google.com/batch/docs/create-run-basic-job)
- [Cloud Batch: automate task retries](https://docs.cloud.google.com/batch/docs/automate-task-retries)
- [Cloud Batch: analyze a job using Cloud Logging](https://docs.cloud.google.com/batch/docs/analyze-job-using-logs)
- [Cloud Batch: specify job network](https://docs.cloud.google.com/batch/docs/specify-job-network)
- [Cloud Batch locations](https://docs.cloud.google.com/batch/docs/locations)
- [Private Google Access](https://docs.cloud.google.com/vpc/docs/private-google-access)
- [Cloud Storage IAM roles and permissions](https://docs.cloud.google.com/iam/docs/roles-permissions/storage)
- [Cloud Batch pricing](https://cloud.google.com/batch/pricing)
- [Google Cloud icons](https://cloud.google.com/icons)

## Diagram attribution

Service glyphs are Google Cloud icons, mirrored from [AwesomeLogos/google-cloud-icons](https://github.com/AwesomeLogos/google-cloud-icons) at pinned commit 9fe9b31ddce5804ae4e6cf4d1bda5d5ee5ae6192; each source file and Git blob hash is recorded in [assets/diagram-provenance.json](assets/diagram-provenance.json). The icons are used as architecture labels, with Google Cloud attribution retained.
