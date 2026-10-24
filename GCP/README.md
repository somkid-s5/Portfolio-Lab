# GCP Solution Labs

[แผน 20 Solution Labs สำหรับ Cloud Engineer](ROADMAP.md)

หนึ่ง Lab คือหนึ่ง Solution ที่จบทั้งสร้างและดูแลในเรื่องเดียว ใช้คู่มือ README เดียว พร้อมไฟล์ App/Script ที่จำเป็น แต่ละ Lab มีจุดเริ่มต้นครบในตัว ไม่ต้องกระโดดไปสร้างระบบจาก Lab อื่น

ทำตามลำดับ: ภาพใหญ่ 20 โจทย์ → Lab brief ทีละเรื่อง → ออกแบบ Tasks → เขียน Guide → ลงมือ ตรวจผลและปิดงาน → Lab ถัดไป

ตัวอย่างรูปแบบคู่มือ: [Lab Test 2](../test/lab-test-2/README.md)

สถานะปัจจุบัน: [Lab 01](LAB-001-multi-zone-web/README.md) ถึง [Lab 09 — ระบบส่ง Webhook ให้ระบบคู่ค้า](LAB-009-partner-webhook-delivery/README.md) อยู่ระดับ Guide-ready; [Lab 10 — Catalog Cache](LAB-010-catalog-cache/README.md) มี App, infrastructure, Tasks 00–14, troubleshooting และ clean rebuild draft แล้ว โดย App/TTL integration, Guide checks, Diagram และ Terraform checks ผ่าน CI #309; CI #310 สำหรับการเพิ่ม troubleshooting/rebuild กำลังตรวจ. Lab 11–20 ยัง Planned ตาม [Progress](PROGRESS.md). ไม่มีการ provision GCP และ Cloud verification ยัง Not run.
