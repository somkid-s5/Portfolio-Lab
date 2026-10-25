# GCP Solution Labs — สารบัญและเส้นทางการเรียน

**สถานะเอกสาร:** คู่มือครบ 20/20 เรื่อง ระดับ Guide-ready  
**สถานะการทดสอบจริง:** Cloud verification = Not run ทั้ง 20 Lab (Guide-ready ≠ Cloud-verified)

โปรเจกต์นี้คือ **20 Independent Solution Labs** สำหรับเรียน Google Cloud Associate Cloud Engineer (ACE) และต่อยอดเป็น Portfolio โดยแต่ละ Lab มีโจทย์ สถาปัตยกรรม คำสั่ง/แอปประกอบ การทดสอบ Fault/Recovery การเปลี่ยนแปลงระบบ และ Cleanup ให้ทำตามจบใน README ของตนเอง ไม่จำเป็นต้อง Deploy Lab ก่อนหน้าทิ้งไว้

## เริ่มตรงไหน

1. [อ่านภาพรวม 20 โจทย์และขอบเขต](ROADMAP.md) เพื่อเลือก Solution
2. เปิด README ของ Lab จากสารบัญด้านล่าง; อ่าน Requirements, Diagram, ค่าใช้จ่ายและความเสี่ยงก่อนสร้างทรัพยากร
3. ทำ Task ตามลำดับ และบันทึก **Expected / Actual / Evidence** แยกจากกัน ห้ามถือผล CI เป็นหลักฐาน Cloud
4. ซ้อม Incident/Change Request, Cleanup, ตรวจ Resource ค้าง และสรุป Portfolio Case Study
5. อัปเดตผลจริงใน [PROGRESS.md](PROGRESS.md); ใช้ [ACE coverage matrix](ACE-COVERAGE.md) เพื่อดูหัวข้อสอบที่ควรอ่านเสริม

## สารบัญ 20 Solution Labs

### Foundation · Compute & Networking (Lab 01–05)

- **Lab 01** — [เว็บหลาย Zone หลัง Load Balancer](LAB-001-multi-zone-web/README.md)
- **Lab 02** — [ระบบ Inventory ภายในองค์กรแบบ Private](LAB-002-private-inventory/README.md)
- **Lab 03** — [เว็บไซต์เอกสารสาธารณะผ่าน CDN และ HTTPS](LAB-003-public-docs-cdn/README.md)
- **Lab 04** — [ระบบจองบริการบน Serverless และ Private Database](LAB-004-serverless-booking/README.md)
- **Lab 05** — [ระบบสั่งซื้อสามชั้นบน VM](LAB-005-three-tier-orders/README.md)

### Serverless · Events & Data (Lab 06–10)

- **Lab 06** — [ระบบรับไฟล์ยอดขายและสร้างรายงานส่วนตัว](LAB-006-private-file-processing/README.md)
- **Lab 07** — [ระบบรับคำสั่งซื้อและประมวลผลงานผ่าน Queue](LAB-007-queued-order-processing/README.md)
- **Lab 08** — [ระบบรายงานยอดขายรายวันและ Batch ที่รันย้อนหลังได้](LAB-008-daily-batch-reports/README.md)
- **Lab 09** — [ระบบส่ง Webhook ให้ระบบคู่ค้า](LAB-009-partner-webhook-delivery/README.md)
- **Lab 10** — [ระบบ Catalog ที่ใช้ Cache ลดภาระ Database](LAB-010-catalog-cache/README.md)

### GKE · Delivery & Advanced Networking (Lab 11–15)

- **Lab 11** — [ระบบคำนวณราคาเสนอค่าขนส่งบน GKE](LAB-011-gke-quote-engine/README.md)
- **Lab 12** — [ระบบ Microservices ที่ติดตามปัญหาข้ามบริการได้](LAB-012-cross-service-tracing/README.md)
- **Lab 13** — [ระบบประมวลผลข้อมูลนำเข้าแบบขนาน](LAB-013-parallel-data-processing/README.md)
- **Lab 14** — [แพลตฟอร์มส่งมอบ App สำหรับทีมพัฒนา](LAB-014-secure-app-delivery/README.md)
- **Lab 15** — [ระบบสำนักงานสาขาเชื่อมบริการ Private บน Cloud](LAB-015-branch-private-connectivity/README.md)

### Migration · Recovery & Operations (Lab 16–20)

- **Lab 16** — [ย้ายระบบ Legacy พร้อมข้อมูลขึ้น Cloud](LAB-016-legacy-migration/README.md)
- **Lab 17** — [ระบบจัดเก็บข้อมูลพร้อมแผนกู้คืนที่ทดสอบได้](LAB-017-data-recovery/README.md)
- **Lab 18** — [แพลตฟอร์มสร้าง Environment ให้ทีมใหม่](LAB-018-team-environment-factory/README.md)
- **Lab 19** — [ระบบเฝ้าระวังและรับ Incident สำหรับทีมบริการ](LAB-019-service-observability/README.md)
- **Lab 20** — [แพลตฟอร์มจองและสร้างรายงานแบบรับมอบงานได้](LAB-020-reservation-handoff/README.md)

## ขอบเขตการพิสูจน์

- **Guide-ready:** มีคู่มือและไฟล์/โค้ดประกอบที่ตรวจใน repository แล้ว แต่ไม่มีการรับรองว่ารันผ่านจริงบนบัญชี GCP
- **Cloud-verified:** ต้องลงมือสร้าง/ทดสอบ/กู้คืน/cleanup บน GCP และเก็บผล Actual กับหลักฐานจริง
- **Portfolio-ready:** ต้องมี Case Study จากการลงมือ พร้อม Architecture, Decision/Trade-off, Failure/Recovery, Cost และหลักฐานที่ตรวจย้อนกลับได้

มาตรฐานร่วม: [PLAN.md](../PLAN.md) · [Diagram Style](../docs/diagram-style.md) · [Roadmap](ROADMAP.md) · [Progress](PROGRESS.md) · [ACE Coverage](ACE-COVERAGE.md)
