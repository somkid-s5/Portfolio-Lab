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

## Follow-up audit — 2026-10-25 (final-review attempt)

- ตรวจ `README.md`, `PLAN.md`, `GCP/{README,ROADMAP,PROGRESS}.md`, เอกสาร QA และ README Lab 01–20 เทียบกับรายการไฟล์ใน PR #1: **ไม่พบ relative Markdown link ที่ชี้ไฟล์ไม่มีอยู่ใน PR** (ตรวจ target path; ยังไม่ได้ตรวจทุก anchor/URL ภายนอก)
- อ่านโครงสร้างของ `assets/diagrams/solution.svg` ครบ **20/20**: มี `viewBox`, `title`, `desc`, และ `role="img"`; ไม่พบการโหลด icon ผ่าน external HTTP URL ภายใน SVG หลัก. เป็นการตรวจ source ไม่ใช่ยืนยันความถูกต้องของการวาง node/เส้น
- เปิด **PNG preview ของ Lab 01–08** เพื่อ spot-review รูปที่แสดงจริง. พบความต่างของขนาดตัวอักษร ความหนาแน่น และรูปแบบ panel/heading ระหว่าง Labs; ยังไม่เซ็นรับรองว่า visual design ทั้งชุดสม่ำเสมอ. Lab 09–20 มี SVG/HTML และ CI render artifacts แต่ไม่ได้ตรวจภาพที่ render จริงผ่าน reviewer ในรอบนี้ จึงห้ามนับเป็น visual-reviewed
- แก้ README Lab 16–20 ให้สื่อความหมายอย่างถูกต้องว่าใช้ **visual reference จาก ZIP** ไม่ได้ยืนยันว่าเรียกใช้ Personal Custom Diagram Design Skill; Skill นี้ยังไม่พบใน connected skills ของรอบตรวจ
- เพิ่ม guard ให้ `.github/workflows/release.yml` สำหรับ Lab 14: GitHub attestation/release จะไม่ทำงานเมื่อไม่มี repository variable `LAB014_RELEASE_ENABLED=true`. อัปเดต README Lab 14 เรื่อง opt-in/disable ก่อน cleanup. **ต้องตรวจ Cloud Build trigger ใน GCP แยกเอง** เพราะ GitHub variable นี้ไม่สามารถปิด GCP-side trigger ที่ถูกตั้งไว้ก่อนแล้ว
- ตรวจคำสั่งและ identity boundary บางส่วนของ Lab 14/20 กับ Terraform, README และ Google Cloud documentation; **ยังไม่ใช่ full semantic validation ทุกบรรทัดหรือ runtime proof**

**Merge gate / pending:** คง PR #1 เป็น Draft จนกว่าจะตรวจภาพ Render ของ Lab 09–20 และแก้ visual differences ที่ตรวจพบ (พร้อมทำ visual sign-off ของ Lab 01–08), ตรวจ cloud release trigger/cost side effects ของ Lab 14 และมีผู้ทบทวนความถูกต้องของ critical instructions ก่อนอนุมัติ Merge. ไม่จำเป็นต้องรัน GCP จริงเพื่อ Merge คู่มือ แต่ห้ามเรียกผลนั้นว่า Cloud-verified.
