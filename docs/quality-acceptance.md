# GCP Solution Labs — Quality acceptance

Date: 2026-10-25 · Scope: docs and source; **no provisioned GCP resources**

## สิ่งที่ตรวจและแก้

- **โครงสร้าง:** README 20 เรื่องเปิดอ่านได้ครบ, แยก Lab ให้เป็น Solution แบบอิสระ, มี Quick Navigation ที่ GCP/README.md, PLAN/ROADMAP/PROGRESS แยกบทบาท; การนำทางและลิงก์ Diagram ใช้ relative paths
- **รูปแบบเนื้อหา:** README ทั้ง 20 มี Task flow, Expected, Actual/Evidence, Change Request, Cleanup, แหล่งอ้างอิงทางการ (ตรวจระดับเอกสาร); สถานะ Guide-ready/Cloud verification ถูกแยก
- **Lab 20 runnable instructions:** Cloud Build config ต้องส่ง repository root, Change Request patch ใช้ --directory และทดสอบ disposable ก่อน apply, migrate schema ก่อน release digest, cleanup image/repo ตาม dependency order, และระบุว่า support_desk ยังไม่ใช่ impersonation authorization
- **ACE coverage:** ตรวจแนว Exam Guide Google v4.0 ตามวันตรวจ ไม่ตีความว่า Lab ครบ = ผ่านทุก objective
- **Diagram structure:** canonical assets/diagrams/solution.svg ครบ 20; legacy mirrors เพื่อ compatibility, visual style ดู docs/diagram-audit.md

## ขอบเขตที่ "Guide-ready" ทำได้

| Category | Static evidence | Out-of-scope proof |
|---|---|---|
| Guide narrative | คำสั่งและลำดับส่วนใหญ่ถูกตรวจจาก Source / References | ผู้เรียนทำทุกคำสั่งด้วย GCP จริง |
| Terraform | `fmt`/`validate` ผ่านบน CI ตาม Job ที่กำหนด | Provider API/quotas/cost/runtime end-to-end |
| App | Tests บางส่วนกับ emulators/disposable DB | Deployed GCP network/IAM/Cloud SQL behavior |
| Visual | SVG, structure, palette and basic source geometry | Human 1000px view review / Personal Skill run |
| Case Study | Template และ Evidence fields | Actual evidence, measured incidents, cleanup |

**Quality gate:** จะให้สถานะ Portfolio Case Study สำเร็จราย Lab ได้ต่อเมื่อมี actual Cloud deploy + operational drill + evidence + cleanup จริงเท่านั้น. การรับ Guide-ready หรือ Merge PR คือการเผยแพร่คู่มือ ไม่ใช่การรับรอง Cloud-runtime

## Priority issues remaining outside static scope

1. **Diagram visual sign-off:** ต้องเรียก Diagram Design Personal Custom Skill จริง (ปัจจุบันไม่ปรากฏใน connected skills), เปิด/ตรวจ Render และแก้จาก source; ดู audit
2. **Cloud execution:** ยังไม่ได้ดำเนินการตาม policy ไม่สร้างทรัพยากร/ค่าใช้จ่ายโดยไม่อนุญาต
3. **Full semantic line-by-line review:** 20 Labs มีเอกสารหลายหมื่นบรรทัด; การตรวจหมวดและ spot-check ไม่เท่ากับการ validate ทุก claim บน Cloud; review กับ official docs ก่อนรันแต่ละ Lab
