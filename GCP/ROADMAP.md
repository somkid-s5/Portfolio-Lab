# แผนภาพใหญ่ — GCP 20 Solution Labs

**สถานะ:** แผนภาพใหญ่ 20 Labs; Lab 01–12 Guide-ready; Lab 13 design baseline ผ่าน CI [#333](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/40099200779) และ [#334](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/40099464528); revision เรื่อง retry lifecycle policy, image-pull IAM และ input/publisher bucket roles กำลังตรวจ CI. Lab 12 ผ่าน repository CI [#330](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/40097377975) ครบ 43/43 jobs; CI ไม่ใช่ผล Cloud run และไม่มี Cloud verification จริง.

## แนวทางที่ยึดร่วมกัน

หนึ่ง Lab คือหนึ่ง Solution ที่ทำจบเป็นเรื่องเดียว: **เข้าใจโจทย์ → ออกแบบ → สร้าง → Deploy → ทดสอบ → ดูแล/แก้ปัญหา → รับการเปลี่ยนแปลง → สรุป → Cleanup**

ส่วน Build และ Operate อยู่ใน Lab เดียว ไม่แยกไปอีกหมายเลขหนึ่ง ลำดับช่วยให้ทักษะเติบโต แต่การเปิด Lab ต้องมี code/config/ข้อมูลตั้งต้นที่เพียงพอ ไม่ต้องกลับไปสร้างทรัพยากรจาก Lab อื่นให้เรื่องปัจจุบันจบ

แผนนี้แทนรายการเดิมที่แยก IAM, Terraform, Secrets หรือ Operations ออกเป็นหัวข้อเดี่ยว โดยนำทักษะเหล่านั้นกลับไปอยู่ใน Solution ที่ต้องใช้งานจริง มีทั้งบริการธุรกิจและแพลตฟอร์มภายในที่ทีม Cloud รับผิดชอบ

## ระดับการวางแผน

| ระดับ | สิ่งที่ต้องตัดสินใจ | ทำเมื่อไร |
|---|---|---|
| 1 / ภาพใหญ่ | 20 โจทย์ ขอบเขต จุดต่าง และทักษะที่ครอบคลุม | รอบนี้ |
| 2 / Lab brief | สถานการณ์ Requirements, acceptance, architecture, trade-offs, cost/access prerequisites | ทีละ Lab ก่อนเขียน Guide |
| 3 / Task design | ลำดับ setup/deploy/check, fault scenarios, app behavior, หลักฐานแต่ละจุด | หลัง brief ของ Lab นั้นลงตัว |
| 4 / Lab Guide | README เดียวแบบพาทำละเอียด พร้อมไฟล์ประกอบที่จำเป็น | ทำและทบทวนทีละ Lab |
| 5 / ลงมือและปิดงาน | ผลจริง ปัญหา Retest สรุป Case Study และ Cleanup | ก่อนเดินต่อ Lab ถัดไป |

ไม่เร่งเขียน Guide ทั้ง 20 พร้อมกัน หากพบข้อจำกัดระหว่างทำให้ปรับ Lab ปัจจุบันและ master plan ก่อน เพื่อไม่ให้ roadmap กับของจริงแยกจากกัน

## ภาพรวม 20 โจทย์

| Lab | Solution | ทักษะเด่น |
|---|---|---|
| 01 | [เว็บหลาย Zone หลัง Load Balancer](#lab-01) | HA บน VM และการวิเคราะห์ traffic |
| 02 | [ระบบ Inventory ภายในองค์กรแบบ Private](#lab-02) | Private networking และการแบ่งสิทธิ์ |
| 03 | [เว็บไซต์เอกสารสาธารณะผ่าน CDN และ HTTPS](#lab-03) | Web delivery, caching และ release management |
| 04 | [ระบบจองบริการบน Serverless และ Private Database](#lab-04) | Serverless application และ data access |
| 05 | [ระบบธุรกรรมสามชั้นบน VM](#lab-05) | Tiered architecture และ database continuity |
| 06 | [ระบบรับและประมวลผลไฟล์อย่างปลอดภัย](#lab-06) | Object storage และ event processing |
| 07 | [ระบบรับคำสั่งซื้อและประมวลผลงานผ่าน Queue](#lab-07) | Asynchronous systems และ reliable processing |
| 08 | [ระบบรายงานตามเวลาและงาน Batch รายวัน](#lab-08) | Scheduled operations และ batch reliability |
| 09 | [ระบบส่ง Webhook ให้ระบบคู่ค้า](#lab-09) | Integration reliability และ external dependency handling |
| 10 | [ระบบ Catalog ที่ใช้ Cache ลดภาระ Database](#lab-10) | Performance engineering และ cost/performance |
| 11 | [ระบบบริการบน GKE ที่ Deploy และขยายได้](#lab-11) | Kubernetes workload operations |
| 12 | [ระบบ Microservices ที่ติดตามปัญหาข้ามบริการได้](#lab-12) | Distributed-system troubleshooting |
| 13 | [ระบบประมวลผลข้อมูลนำเข้าแบบขนาน](#lab-13) | Compute batch orchestration และ data correctness |
| 14 | [แพลตฟอร์มส่งมอบ App สำหรับทีมพัฒนา](#lab-14) | CI/CD, trusted delivery และ environment promotion |
| 15 | [ระบบสำนักงานสาขาเชื่อมบริการ Private บน Cloud](#lab-15) | Hybrid networking และ fault isolation |
| 16 | [ย้ายระบบ Legacy พร้อมข้อมูลขึ้น Cloud](#lab-16) | Migration planning และ data-safe cutover |
| 17 | [ระบบจัดเก็บข้อมูลพร้อมแผนกู้คืนที่ทดสอบได้](#lab-17) | Backup, disaster recovery และ recovery evidence |
| 18 | [แพลตฟอร์มสร้าง Environment ให้ทีมใหม่](#lab-18) | Infrastructure automation และ team governance |
| 19 | [ระบบเฝ้าระวังและรับ Incident สำหรับทีมบริการ](#lab-19) | Service operations และ incident communication |
| 20 | [แพลตฟอร์มจองและสร้างรายงานแบบรับมอบงานได้](#lab-20) | การสังเคราะห์ Cloud Engineering แบบครบวงจร |

## ขอบเขตระดับ Solution

เทคโนโลยีด้านล่างเป็น **candidate stack** จะยืนยันชนิดบริการ/edition/region/สิทธิ์/ราคาอีกครั้งใน Lab brief หากเปลี่ยน stack ต้องยังตอบโจทย์เดิมและอธิบายเหตุผลได้

<a id="lab-01"></a>

### 01 — เว็บหลาย Zone หลัง Load Balancer

**โจทย์:** ทีมต้องการเว็บที่ยังรับคำขอได้เมื่อ App หนึ่งเครื่องหยุด

**สร้างอะไร:** Compute Engine สอง Zone, Application LB, VPC, IAP, diagnostic web/API

**ดูแลและพิสูจน์อะไร:** พิสูจน์ traffic distribution, health transitions, หยุด/กู้ App และปรับความสามารถรับโหลด

**Change request:** เพิ่ม backend จากสองเป็นสามเครื่อง แล้วเปรียบเทียบผล

**วิธีหลักที่วางไว้:** Console เป็นหลัก

**ขอบเขตเมื่อจบ:** ใช้งาน flow หลักได้ มีผลตรวจตาม requirement หลักฐาน fault/recovery หรือ operational scenario ที่กำหนด และบันทึกผลการเปลี่ยนแปลง ไม่จบเพียงสร้าง resource สำเร็จ

---

<a id="lab-02"></a>

### 02 — ระบบ Inventory ภายในองค์กรแบบ Private

**โจทย์:** ทีมงานต้องเข้า API ภายในได้ โดย VM และ database ไม่เปิดรับอินเทอร์เน็ตโดยตรง

**สร้างอะไร:** Internal Inventory UI/API, internal LB, private VM, PostgreSQL, private DNS, NAT, IAP

**ดูแลและพิสูจน์อะไร:** ตรวจ DNS/route/firewall, สิทธิ์ผู้ใช้, outbound path และกู้ App ที่ตั้งค่าผิด

**Change request:** เพิ่ม client network พร้อมกำหนดสิทธิ์เข้าถึงเฉพาะบริการที่จำเป็น

**วิธีหลักที่วางไว้:** Console + CLI

**ขอบเขตเมื่อจบ:** ใช้งาน flow หลักได้ มีผลตรวจตาม requirement หลักฐาน fault/recovery หรือ operational scenario ที่กำหนด และบันทึกผลการเปลี่ยนแปลง ไม่จบเพียงสร้าง resource สำเร็จ

---

<a id="lab-03"></a>

### 03 — เว็บไซต์เอกสารสาธารณะผ่าน CDN และ HTTPS

**โจทย์:** ทีมสื่อสารต้องเผยแพร่เนื้อหาเร็ว อัปเดตได้ และย้อนเวอร์ชันได้

**สร้างอะไร:** Static content, Cloud Storage backend bucket, external Application LB, CDN, DNS, TLS, deployment script

**ดูแลและพิสูจน์อะไร:** ทดสอบ cache hit/miss, header/TTL, stale content, invalidation และ rollback release

**Change request:** ปล่อยเอกสารเวอร์ชันใหม่โดยกำหนด cache strategy สำหรับ HTML กับ assets ต่างกัน

**วิธีหลักที่วางไว้:** Console + CLI

**ขอบเขตเมื่อจบ:** ใช้งาน flow หลักได้ มีผลตรวจตาม requirement หลักฐาน fault/recovery หรือ operational scenario ที่กำหนด และบันทึกผลการเปลี่ยนแปลง ไม่จบเพียงสร้าง resource สำเร็จ

---

<a id="lab-04"></a>

### 04 — ระบบจองบริการบน Serverless และ Private Database

**โจทย์:** ผู้ใช้ต้องจองและตรวจสถานะได้ ข้อมูลต้องคงอยู่แม้เปลี่ยน revision

**สร้างอะไร:** Booking UI/API, Cloud Run, private Cloud SQL, Secret Manager, authenticated user flow

**ดูแลและพิสูจน์อะไร:** ตรวจ IAM กับ app auth แยกกัน, DB connections, credential rotation, revision rollback และ load limits

**Change request:** เพิ่ม concurrency โดยรักษาความถูกต้องของการจองและ connection budget

**วิธีหลักที่วางไว้:** CLI + Terraform

**สถานะปัจจุบัน:** [Design checkpoint](LAB-013-parallel-data-processing/README.md) — CI #333 ผ่าน design baseline; revision ของ retry-policy wording, image-pull IAM และ bucket writer/read boundaries pending CI; Cloud verification Not run.

**ขอบเขตเมื่อจบ:** ใช้งาน flow หลักได้ มีผลตรวจตาม requirement หลักฐาน fault/recovery หรือ operational scenario ที่กำหนด และบันทึกผลการเปลี่ยนแปลง ไม่จบเพียงสร้าง resource สำเร็จ

---

<a id="lab-05"></a>

### 05 — ระบบธุรกรรมสามชั้นบน VM

**โจทย์:** องค์กรมี App ที่ต้องแยก Web, API และ Database tiers พร้อมขยาย App tier ได้

**สร้างอะไร:** Web/API บน instance groups, public/internal LB ตาม flow, Cloud SQL HA, private subnets, deployment artifacts

**ดูแลและพิสูจน์อะไร:** ทดสอบ tier access matrix, rolling update, App failure, planned DB failover และ reconnect

**Change request:** ปรับ app replicas/connection pool โดยวัดผลก่อน–หลัง

**วิธีหลักที่วางไว้:** Terraform + Console/CLI สำหรับตรวจ rollout/failover (ยืนยันใน Lab brief; ไม่สร้าง manual ซ้ำทับ state)

**ขอบเขตเมื่อจบ:** ใช้งาน flow หลักได้ มีผลตรวจตาม requirement หลักฐาน fault/recovery หรือ operational scenario ที่กำหนด และบันทึกผลการเปลี่ยนแปลง ไม่จบเพียงสร้าง resource สำเร็จ

---

<a id="lab-06"></a>

### 06 — ระบบรับและประมวลผลไฟล์อย่างปลอดภัย

**โจทย์:** ผู้ใช้ต้องอัปโหลดไฟล์ ดูสถานะ และดาวน์โหลดผลเฉพาะรายการที่ตนมีสิทธิ์

**สร้างอะไร:** Upload portal/API, signed access, Cloud Storage, Eventarc, worker, metadata store

**ดูแลและพิสูจน์อะไร:** ตรวจ file ownership, type/size validation, duplicate events, failed file retry, expiry และ retention

**Change request:** รองรับไฟล์ใหญ่ขึ้นโดยไม่เปิด bucket สาธารณะ

**วิธีหลักที่วางไว้:** CLI + Terraform

**ขอบเขตเมื่อจบ:** ใช้งาน flow หลักได้ มีผลตรวจตาม requirement หลักฐาน fault/recovery หรือ operational scenario ที่กำหนด และบันทึกผลการเปลี่ยนแปลง ไม่จบเพียงสร้าง resource สำเร็จ

---

<a id="lab-07"></a>

### 07 — ระบบรับคำสั่งซื้อและประมวลผลงานผ่าน Queue

**โจทย์:** API ต้องรับงานได้เร็ว และงานสำคัญต้องไม่เกิดผลซ้ำเมื่อ delivery ซ้ำ

**สร้างอะไร:** Order API, Pub/Sub, authenticated worker, PostgreSQL transaction/idempotency ledger, status UI

**ดูแลและพิสูจน์อะไร:** ฉีด transient/poison messages, ตรวจ business effect ซ้ำ, dead-letter, replay และ backlog

**Change request:** เพิ่ม worker throughput พร้อมคงเงื่อนไข idempotency

**วิธีหลักที่วางไว้:** CLI + Terraform

**ขอบเขตเมื่อจบ:** ใช้งาน flow หลักได้ มีผลตรวจตาม requirement หลักฐาน fault/recovery หรือ operational scenario ที่กำหนด และบันทึกผลการเปลี่ยนแปลง ไม่จบเพียงสร้าง resource สำเร็จ

---

<a id="lab-08"></a>

### 08 — ระบบรายงานตามเวลาและงาน Batch รายวัน

**โจทย์:** ทีมต้องได้รายงานตามรอบเวลา พร้อมรู้เมื่อ job ขาดหายและรันย้อนหลังได้

**สร้างอะไร:** Cloud Scheduler, Cloud Run Jobs, job ledger, synthetic source data, report storage, notification

**ดูแลและพิสูจน์อะไร:** ทดสอบ timeout/retry, schedule timezone, missed run, overlapping jobs และ backfill โดยไม่เขียนผลซ้ำ

**Change request:** เพิ่มรายงานย้อนหลังหลายวันโดยควบคุม concurrency และค่าใช้จ่าย

**วิธีหลักที่วางไว้:** CLI + Terraform

**ขอบเขตเมื่อจบ:** ใช้งาน flow หลักได้ มีผลตรวจตาม requirement หลักฐาน fault/recovery หรือ operational scenario ที่กำหนด และบันทึกผลการเปลี่ยนแปลง ไม่จบเพียงสร้าง resource สำเร็จ

---

<a id="lab-09"></a>

### 09 — ระบบส่ง Webhook ให้ระบบคู่ค้า

**โจทย์:** ต้องส่ง event ถึงคู่ค้าอย่างตรวจสอบได้ แม้ปลายทางช้าหรือล่มชั่วคราว

**สร้างอะไร:** Event API, Cloud Tasks, authenticated delivery worker, partner mock endpoint, delivery ledger

**ดูแลและพิสูจน์อะไร:** ตรวจ timeout, backoff, signature/identity, duplicate handling, exhausted retries และ manual redrive

**Change request:** เพิ่ม partner ปลายทางใหม่ที่มี rate limit ต่างกัน

**วิธีหลักที่วางไว้:** CLI + Terraform

**ขอบเขตเมื่อจบ:** ใช้งาน flow หลักได้ มีผลตรวจตาม requirement หลักฐาน fault/recovery หรือ operational scenario ที่กำหนด และบันทึกผลการเปลี่ยนแปลง ไม่จบเพียงสร้าง resource สำเร็จ

---

<a id="lab-10"></a>

### 10 — ระบบ Catalog ที่ใช้ Cache ลดภาระ Database

**โจทย์:** รายการสินค้าถูกอ่านมากจน database หนัก แต่ข้อมูลต้องอัปเดตตามเงื่อนไขที่กำหนด

**สร้างอะไร:** Catalog UI/API, Cloud Run, PostgreSQL, managed Redis cache, bounded load generator

**ดูแลและพิสูจน์อะไร:** วัด cache hit/miss, invalidation/TTL, cache outage fallback, connection usage และ latency/error ก่อน–หลัง

**Change request:** เปลี่ยน cache policy เพื่อรองรับข้อมูลที่อัปเดตบ่อยและอธิบาย trade-off

**วิธีหลักที่วางไว้:** Terraform + CLI

**ขอบเขตเมื่อจบ:** ใช้งาน flow หลักได้ มีผลตรวจตาม requirement หลักฐาน fault/recovery หรือ operational scenario ที่กำหนด และบันทึกผลการเปลี่ยนแปลง ไม่จบเพียงสร้าง resource สำเร็จ

---

<a id="lab-11"></a>

### 11 — ระบบบริการบน GKE ที่ Deploy และขยายได้

**โจทย์:** ทีมต้องรัน App/worker หลาย replicas พร้อมควบคุม readiness และ identity

**สร้างอะไร:** GKE, API/worker, Gateway/Services, workload identity, secrets, NetworkPolicy, HPA

**ดูแลและพิสูจน์อะไร:** ทดสอบ broken rollout, pod failure, HPA scale up/down, forbidden network path และ runtime secret access

**Change request:** เพิ่มโหลดและปรับ requests/limits โดยไม่ทำให้เกิด OOM หรือ readiness failures

**วิธีหลักที่วางไว้:** Terraform + kubectl

**ขอบเขตเมื่อจบ:** ใช้งาน flow หลักได้ มีผลตรวจตาม requirement หลักฐาน fault/recovery หรือ operational scenario ที่กำหนด และบันทึกผลการเปลี่ยนแปลง ไม่จบเพียงสร้าง resource สำเร็จ

---

<a id="lab-12"></a>

### 12 — ระบบ Microservices ที่ติดตามปัญหาข้ามบริการได้

**โจทย์:** ทีมต้องการรู้ว่าความช้าและ error เกิดที่บริการใดใน user journey

**สร้างอะไร:** Storefront, order/catalog/payment-mock services, GKE, tracing, structured logs, service identities

**ดูแลและพิสูจน์อะไร:** ทดสอบ dependency timeout, bounded retry, resource isolation, trace correlation และ recovery

**Change request:** เปลี่ยนสัญญาการตอบกลับหนึ่งบริการแบบ backward-compatible แล้วปล่อยเป็นช่วง

**วิธีหลักที่วางไว้:** Terraform + manifests

**ขอบเขตเมื่อจบ:** ใช้งาน flow หลักได้ มีผลตรวจตาม requirement หลักฐาน fault/recovery หรือ operational scenario ที่กำหนด และบันทึกผลการเปลี่ยนแปลง ไม่จบเพียงสร้าง resource สำเร็จ

---

<a id="lab-13"></a>

### 13 — ระบบประมวลผลข้อมูลนำเข้าแบบขนาน

**โจทย์:** ไฟล์ข้อมูลจำนวนมากต้องผ่าน validation และรวมผลได้ แม้บาง task ล้มเหลว

**สร้างอะไร:** Cloud Batch, containerized validator/processor, Cloud Storage, manifest/checkpoint และ summary UI

**ดูแลและพิสูจน์อะไร:** ตรวจ input/output reconciliation, partial failure, retry, checkpoint และ bounded parallelism

**Change request:** เพิ่มขนาดข้อมูลและเลือกทรัพยากรใหม่พร้อมเทียบเวลา/ต้นทุน

**วิธีหลักที่วางไว้:** CLI + Terraform

**ขอบเขตเมื่อจบ:** ใช้งาน flow หลักได้ มีผลตรวจตาม requirement หลักฐาน fault/recovery หรือ operational scenario ที่กำหนด และบันทึกผลการเปลี่ยนแปลง ไม่จบเพียงสร้าง resource สำเร็จ

---

<a id="lab-14"></a>

### 14 — แพลตฟอร์มส่งมอบ App สำหรับทีมพัฒนา

**โจทย์:** ทีมต้องมีเส้นทางจาก commit ถึง staging/production ที่เชื่อถือได้และย้อนกลับได้

**สร้างอะไร:** Sample business App, GitHub Actions, WIF, Artifact Registry, staging/prod runtime, provenance และ deployment policy

**ดูแลและพิสูจน์อะไร:** ทดสอบ CI fail, untrusted identity, unapproved image, canary error, rollback และ audit trail

**Change request:** เพิ่ม approval/exception workflow โดยกำหนดผู้รับผิดชอบและอายุข้อยกเว้น

**วิธีหลักที่วางไว้:** CI pipeline + Terraform

**ขอบเขตเมื่อจบ:** ใช้งาน flow หลักได้ มีผลตรวจตาม requirement หลักฐาน fault/recovery หรือ operational scenario ที่กำหนด และบันทึกผลการเปลี่ยนแปลง ไม่จบเพียงสร้าง resource สำเร็จ

---

<a id="lab-15"></a>

### 15 — ระบบสำนักงานสาขาเชื่อมบริการ Private บน Cloud

**โจทย์:** สาขาต้องใช้บริการภายใน Cloud ได้ และยังทำงานเมื่อ VPN tunnel หนึ่งหยุด

**สร้างอะไร:** จำลอง branch ด้วย peer VPC, HA VPN/BGP, private Inventory API, DNS และ firewall matrix

**ดูแลและพิสูจน์อะไร:** ตรวจ routes/BGP, tunnel failover, CIDR conflict scenario, DNS failure และ restore connectivity

**Change request:** เพิ่ม subnet ของสาขาใหม่พร้อมควบคุม prefix/สิทธิ์เข้าถึง

**วิธีหลักที่วางไว้:** Console + CLI + Terraform

**ขอบเขตเมื่อจบ:** ใช้งาน flow หลักได้ มีผลตรวจตาม requirement หลักฐาน fault/recovery หรือ operational scenario ที่กำหนด และบันทึกผลการเปลี่ยนแปลง ไม่จบเพียงสร้าง resource สำเร็จ

---

<a id="lab-16"></a>

### 16 — ย้ายระบบ Legacy พร้อมข้อมูลขึ้น Cloud

**โจทย์:** ทีมต้องย้ายระบบเดิมโดยควบคุมช่วงหยุดและมีแผนถอยที่ไม่ทำข้อมูลหาย

**สร้างอะไร:** Simulated legacy App/PostgreSQL, target Cloud Run/VM + Cloud SQL, migration tooling, cutover routing

**ดูแลและพิสูจน์อะไร:** ซ้อมย้าย, schema compatibility, write freeze, data reconciliation, cutover และ backout boundary

**Change request:** ลด downtime ด้วยแนวทาง incremental migration หากความพร้อมต้นทางรองรับ

**วิธีหลักที่วางไว้:** Scripts + CLI + Terraform

**ขอบเขตเมื่อจบ:** ใช้งาน flow หลักได้ มีผลตรวจตาม requirement หลักฐาน fault/recovery หรือ operational scenario ที่กำหนด และบันทึกผลการเปลี่ยนแปลง ไม่จบเพียงสร้าง resource สำเร็จ

---

<a id="lab-17"></a>

### 17 — ระบบจัดเก็บข้อมูลพร้อมแผนกู้คืนที่ทดสอบได้

**โจทย์:** ทีมต้องรู้ว่าถ้าลบข้อมูลผิดหรือเสีย environment จะกู้บริการได้อย่างไร

**สร้างอะไร:** Records App, PostgreSQL/Cloud SQL, object storage, backup/PITR, IaC, integrity probes และ recovery runbook

**ดูแลและพิสูจน์อะไร:** จำลองข้อมูลเสีย/ถูกลบ, restore ไปปลายทางใหม่, ตรวจ business invariants และวัด RTO/RPO ตามนิยาม

**Change request:** เพิ่ม cross-region recovery เฉพาะเมื่อกำหนด replication และ failback ครบ

**วิธีหลักที่วางไว้:** Terraform + recovery scripts

**ขอบเขตเมื่อจบ:** ใช้งาน flow หลักได้ มีผลตรวจตาม requirement หลักฐาน fault/recovery หรือ operational scenario ที่กำหนด และบันทึกผลการเปลี่ยนแปลง ไม่จบเพียงสร้าง resource สำเร็จ

---

<a id="lab-18"></a>

### 18 — แพลตฟอร์มสร้าง Environment ให้ทีมใหม่

**โจทย์:** ทีมต้องเปิด dev/staging ได้เร็วโดยไม่ใช้สิทธิ์ร่วมกันและไม่หลงเหลือ resource ไร้เจ้าของ

**สร้างอะไร:** Project-level foundation, environment factory, Terraform remote state, sample workload, IAM, budgets/labels, log sinks

**ดูแลและพิสูจน์อะไร:** ทดสอบ provisioning, environment isolation, drift/locking, onboarding, teardown และ ownership

**Change request:** รับทีมใหม่ที่มี requirement ด้าน location/permissions ต่างกัน; org policies เป็น extension ตามสิทธิ์

**วิธีหลักที่วางไว้:** Terraform + policy tests

**ขอบเขตเมื่อจบ:** ใช้งาน flow หลักได้ มีผลตรวจตาม requirement หลักฐาน fault/recovery หรือ operational scenario ที่กำหนด และบันทึกผลการเปลี่ยนแปลง ไม่จบเพียงสร้าง resource สำเร็จ

---

<a id="lab-19"></a>

### 19 — ระบบเฝ้าระวังและรับ Incident สำหรับทีมบริการ

**โจทย์:** ทีมต้องตรวจพบอาการ เข้าใจผลกระทบ และทำตาม runbook ได้ก่อนผู้ใช้แจ้ง

**สร้างอะไร:** Sample API/worker/database, logs/metrics/traces, SLI/SLO, alerts, incident board และ synthetic probes

**ดูแลและพิสูจน์อะไร:** ฉีด error/latency/dependency faults, ตรวจ alert delivery, ใช้ runbook หา root cause และเก็บ timeline/postmortem

**Change request:** ลด alert noise โดยยังจับ failure ที่กระทบผู้ใช้ได้

**วิธีหลักที่วางไว้:** Terraform + instrumentation + game day

**ขอบเขตเมื่อจบ:** ใช้งาน flow หลักได้ มีผลตรวจตาม requirement หลักฐาน fault/recovery หรือ operational scenario ที่กำหนด และบันทึกผลการเปลี่ยนแปลง ไม่จบเพียงสร้าง resource สำเร็จ

---

<a id="lab-20"></a>

### 20 — แพลตฟอร์มจองและสร้างรายงานแบบรับมอบงานได้

**โจทย์:** รับโจทย์บริการครบวงจรและส่งมอบให้ทีมอื่นเปิดใช้งาน/ดูแลต่อได้

**สร้างอะไร:** Booking UI/API + async reporting + private data + HTTPS edge + CI/CD + IaC + observability; เลือก runtime หลักหนึ่งแบบ

**ดูแลและพิสูจน์อะไร:** ทดสอบ user journey, secure access, scaling, bad release, dependency outage, restore, cost review และ operational handover

**Change request:** รับ requirement ใหม่หนึ่งข้อและเสนอทางเลือกก่อน implement/retest

**วิธีหลักที่วางไว้:** เลือกสถาปัตยกรรมพร้อม ADR

**ขอบเขตเมื่อจบ:** ใช้งาน flow หลักได้ มีผลตรวจตาม requirement หลักฐาน fault/recovery หรือ operational scenario ที่กำหนด และบันทึกผลการเปลี่ยนแปลง ไม่จบเพียงสร้าง resource สำเร็จ


## ตรวจความครอบคลุมของทักษะ

| ทักษะ | Lab ที่เป็นเจ้าภาพหลัก | การนำกลับมาใช้ |
|---|---|---|
| Linux/service/process, VM, LB, health, availability | 01, 05 | 02, 15, 16 |
| Private networking, DNS, NAT, routing, firewalls | 02, 15 | 04, 05, 10, 11 |
| Public edge, TLS, caching, CDN | 03, 10 | 20 |
| IAM, runtime identity, secrets, audit | 02, 04, 14, 18 | ใช้ตามความจำเป็นในทุกระบบ |
| Containers และ serverless | 04, 06–09 | 14, 20 |
| Database, connections, transactions, failover | 04, 05, 07 | 16, 17, 20 |
| Event delivery, retries, idempotency, background jobs | 06–09 | 12, 20 |
| Kubernetes rollout, probes, scaling, policy | 11, 12 | 20 หากเลือก GKE |
| Batch compute และ data integrity | 08, 13 | 16, 17 |
| Terraform/state/drift และ reproducibility | 14, 18 | นำไปใช้ใน Lab ที่เหมาะ ไม่บังคับทำซ้ำทุกวิธี |
| CI/CD, provenance, promotion, rollback | 14 | ใช้ release workflow ตามขนาดใน Lab อื่น |
| Logs, metrics, traces, SLO, alert, incident | 19 | มี health/logs และ fault evidence ตั้งแต่ Lab แรก |
| Migration, backup, restore และ DR | 16, 17 | ทำ backup/cleanup ที่จำเป็นตั้งแต่ระบบมีข้อมูล |
| Cost, quotas, sizing และ resource ownership | 10, 13, 18, 20 | ทุก Lab ต้องวางต้นทุน/เพดานทดสอบ/Cleanup |

Lab ที่เป็นเจ้าภาพหลักเจาะเรื่องนั้นลึกที่สุด แต่พื้นฐานที่จำเป็นยังอยู่ในทุก Solution เช่น Lab Database ต้องมีการจัดการสิทธิ์และ log โดยไม่ต้องรอไปทำ Lab 19 ก่อน

## รูปแบบคู่มือของแต่ละ Lab

README เดียวเรียงตามการทำจริง:

1. ชื่อ Solution, ภาพรวม และ Diagram ที่อ่านเห็นเส้นทางหลัก
2. สถานการณ์ ผู้ใช้ Requirements และนิยามสำเร็จ
3. เหตุผลการออกแบบและขอบเขตที่ยังไม่ทำ
4. สิ่งที่เตรียม ค่าใช้จ่าย สิทธิ์ ค่า config และไฟล์ App/Script/seed data
5. Tasks: เป้าหมาย → ทำที่ไหน → ขั้นตอนละเอียด → Expected output → จุดบันทึก → เกณฑ์ไปต่อ
6. ทดสอบ business flow, identity/network boundaries และ behavior ของระบบ
7. Operations/fault/recovery ที่ตรงกับ Solution นั้น
8. Change request ที่ให้วิเคราะห์ทางเลือกและปรับระบบ
9. ผลจริง หลักฐาน Troubleshooting บทเรียน และสรุปผลงาน
10. Cleanup และวิธีสร้างกลับจากเวอร์ชันที่บันทึกไว้

Diagram ใช้รูปแบบที่ทดลองแล้ว: ไอคอนทางการ สีแยกขอบเขต เลย์เอาต์ตามการเชื่อมต่อ และตรวจอ่านที่ความกว้าง README

## ขอบเขตที่ต้องปิดก่อนเริ่ม Guide ของแต่ละ Lab

- ใครใช้บริการ และ business flow ที่จะทดสอบคืออะไร
- Requirements ใดเป็น must-have และอะไรเป็น optional extension
- Architecture ถูกตาม scope จริงหรือไม่ เช่น global/regional resources, subnet/zone และ identity
- App/API/Worker ต้องมี endpoint, log, seed และ fault controls อะไรให้ทดสอบได้
- แต่ละเกณฑ์มีวิธีวัด Expected/Actual พร้อม evidence ที่ทำได้จริง
- Failure injection ปลอดภัยใน sandbox และมีทางคืนสถานะชัดเจน
- Runtime/IAM/user authentication แยกกันอย่างไร
- มี budget/access/quotas/domain หรือข้อจำกัด organization ใดก่อนเริ่ม
- ชุดเริ่มต้นและ finish point ของ Lab ครบในตัว ไม่พึ่ง resource ที่เปิดไว้จาก Lab ก่อน
- การ Deploy/rollback มีผลต่อ schema, messages และข้อมูลค้างอย่างไร
- กำหนดเพดาน load, cleanup, retention และค่าใช้จ่ายก่อนทดสอบ

## หลักฐานที่ทำให้หนึ่ง Solution พร้อมเป็นผลงาน

- Diagram ตรงกับระบบที่ทำจริง และบอก trade-off ของแบบได้
- User journey ทำงานครบ พร้อมผล positive/negative tests
- มีสถานการณ์ผิดปกติที่ควบคุมได้ วิธีตรวจ สาเหตุ และผลหลังแก้
- บันทึกการตัดสินใจใน Change request ด้วยเหตุผลของผู้ทำ
- ไม่อ้าง zero downtime, exact-once, production capacity หรือ SLA จากผลที่ยังไม่ได้พิสูจน์
- มีเวอร์ชัน code/config, ผลทดสอบ, runbook ตามขอบเขต และวิธี Cleanup/rebuild

## ข้อจำกัดและการคุมขอบเขต

แผนครอบคลุมกลุ่มงาน Cloud Engineer ไม่ได้รับประกันว่าทำครบแล้วแทนประสบการณ์ production ได้ ต้องอธิบาย แก้ปัญหา และตัดสินใจได้ด้วยตนเอง

ไม่จำเป็นต้องเปิด 20 ระบบพร้อมกัน สามารถ reuse code และ modules ที่มีเวอร์ชัน แต่แต่ละ Lab ต้องอธิบายวิธีเริ่มจาก clean environment ให้ครบ บริการที่มีต้นทุนสูง เช่น GKE, database HA, NAT, VPN และ LB จะกำหนดเวลาเปิดและ Cleanup ราย Lab

Lab 15 ใช้ peer VPC จำลอง branch จึงไม่อ้างว่าได้ทดสอบอุปกรณ์ on-prem จริง Lab 17 แยก backup/PITR baseline จาก cross-region DR extension และ Lab 18 ไม่อ้างว่าใช้ org controls ถ้าไม่มี organization/admin access จริง

Lab 20 เป็นโจทย์รับมอบงานที่ใช้ทักษะทั้งหมด แต่ยังต้องมี baseline package และลำดับเริ่มระบบครบในตัวเอง ไม่ใช่ลิงก์กลับให้ผู้อ่านประกอบ Lab เก่าเอง

## ลำดับถัดไป

Lab 10 — [Catalog Cache](LAB-010-catalog-cache/README.md) — Guide-ready หลัง [CI #310](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/40088902566) และ [CI #311](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/40089135500) ผ่านครบ 35/35 jobs ต่อรอบ: app/TTL integration, Guide Tasks/evidence/Bash syntax/links, design/diagram และ Terraform fmt/init/validate. คู่มือมี troubleshooting, cleanup และ clean rebuild path. ไม่ได้ provision GCP; Cloud verification ยังคง Not run.

Lab 11 — [GKE Quote Engine](LAB-011-gke-quote-engine/README.md) — Guide-ready หลัง [CI #315](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/40092884085) ผ่านครบ 39/39 jobs. ครอบคลุม App/API-worker, Terraform foundation, regional GKE Autopilot, HTTPS Gateway, private worker, per-workload Secret Manager access, bounded HPA/load observation, logs, readiness rollback, pod recovery, pricing change request, token rotation และ cleanup. CI ตรวจ source/config เท่านั้น; ไม่ได้ provision GCP และ Cloud verification ยัง Not run.

Lab 12 — [Microservices tracing](LAB-012-cross-service-tracing/README.md) — Guide-ready หลัง [CI #330](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/40097377975) ผ่านครบ 43/43 jobs; ครอบคลุม app/build, Terraform, manifest/IAM, guide checks และ diagram. Architecture/icon checkpoint ก่อนหน้าอยู่ใน [CI #324](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/40095281229). ทั้งหมดเป็น repository evidence; ไม่มี GCP provisioning และ Cloud verification Not run.

ตัวอย่างรูปแบบการอ่านที่ยืนยันแล้ว: [Lab Test 2](../test/lab-test-2/README.md) เป็นตัวอย่างรูปแบบ ไม่ถือเป็นผลการทำ Lab ใด

## แหล่งอ้างอิงในการจัดขอบเขต

ตรวจแผนกับแนวทางบริการวันที่ 21 ตุลาคม 2026 รายละเอียด implementation ต้องตรวจอีกครั้งเมื่อออกแบบแต่ละ Lab

- [Google Cloud Well-Architected Framework](https://docs.cloud.google.com/architecture/framework)
- [Google Cloud Architecture Center](https://docs.cloud.google.com/architecture/)
- [Landing zone design](https://docs.cloud.google.com/architecture/landing-zones)
- [Event-driven architecture with Pub/Sub](https://docs.cloud.google.com/solutions/event-driven-architecture-pubsub)

