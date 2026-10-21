# แผนดำเนินงาน — GCP 20 Solution Labs

**สถานะ:** พร้อมใช้ตั้ง Goal; ยังไม่เริ่มจัดทำ Lab จริง 01–20

## ผลลัพธ์ปลายทาง

จัดทำ Solution Labs 20 เรื่องตาม [Roadmap](GCP/ROADMAP.md) ให้ผู้เรียนเปิด README แล้วเริ่มจากศูนย์ สร้างและทดสอบระบบ ดูแล/แก้ปัญหา รับ Change Request บันทึกผล และ Cleanup ได้ใน Lab เดียว

Source of truth คือ GitHub repository `somkid-s5/Portfolio-Lab` งานต่อไปต้องทำใน Cloud โดยอ่านและบันทึกจาก Repo นี้ ไม่พึ่ง path หรือ process บน laptop

## ขอบเขตงานที่ Goal สามารถรับผิดชอบ

1. ตรวจความครอบคลุมและขอบเขต 20 โจทย์ให้ตรง Roadmap
2. ลงรายละเอียด Lab 01 ก่อน ตั้งแต่ brief จนถึงคู่มือและไฟล์ประกอบที่ทดสอบได้
3. ตรวจความครบของ Lab ปัจจุบันและแก้ข้อผิดพลาดก่อนเดินต่อ
4. ทำ Lab 02–20 ตามลำดับเดียวกัน โดยอัปเดตสถานะและ commit เป็นช่วง
5. ตรวจทั้งชุดเพื่อให้ navigation, names, scope, prerequisites และรูปแบบหลักฐานสอดคล้องกัน

ผู้เรียนเป็นผู้รัน GCP Lab และเติมหลักฐานจริงภายหลัง เว้นแต่จะอนุญาตการสร้างทรัพยากรและงบประมาณเพิ่มอย่างชัดเจน งานจัดทำคู่มือห้ามตั้งสถานะผล Cloud เป็น PASS หรือ verified จากการตรวจเอกสาร/โค้ดในเครื่อง

## ขั้นทำงานต่อหนึ่ง Lab

| ขั้น | งาน | เงื่อนไขออกจากขั้น |
|---|---|---|
| Brief | สถานการณ์ ผู้ใช้ Requirements, must-have/extension, acceptance, resource/access/cost assumptions | ทุก Requirement มีวิธีพิสูจน์และขอบเขตที่ทำได้ |
| Design | Architecture, data/identity/request flow, trade-offs และ task order | Diagram ตรงกับ component/permissions/network ที่จะใช้ |
| Build materials | App/API/worker/schema/seed, configs, scripts และตัวทดสอบที่จำเป็น | ทำ business flow และ failure scenario ที่โจทย์ต้องใช้ได้ |
| Guide | README เดียว พาทำละเอียด พร้อม Expected/checkpoint/record/cleanup | ผู้เรียนรู้ว่าจะทำอะไร ที่ไหน ควรเห็นอะไร และติดแล้วตรวจอย่างไร |
| Review | ตรวจ code, links, anchors, syntax, local/container smoke tests และ render Diagram | แก้ failure ที่ตรวจได้และระบุสิ่งที่ยังไม่ได้ทดสอบจริง |
| Publish checkpoint | Commit/PR และอัปเดต PROGRESS | ผลงานตรวจกลับจาก GitHub ได้ พร้อมบอกข้อจำกัดก่อนเรื่องถัดไป |

เกณฑ์เหล่านี้เป็น self-review checkpoints ไม่ใช่ข้อกำหนดให้หยุดขออนุมัติทุกขั้น เมื่อผู้ใช้เริ่ม Goal แล้วสามารถทำต่อเป็นลำดับภายในขอบเขตที่มอบหมายได้

## รูปแบบส่งมอบ

```text
GCP/
├── ROADMAP.md
├── PROGRESS.md
└── LAB-001-<solution-slug>/
    ├── README.md
    ├── assets/
    │   ├── solution.svg
    │   ├── solution-preview.png
    │   └── evidence/
    └── scripts/ หรือ app/ หรือ infra/ ตามโจทย์
```

เนื้อหาสำหรับเรียน บันทึกผล และสรุปผลงานอยู่ใน README เดียว ไม่แตกเป็น guide/results/worklog/case-study หลายไฟล์ โค้ดและ assets แยกไฟล์ได้ตามความจำเป็น

## Milestones

| Milestone | สิ่งส่งมอบ |
|---|---|
| M0 — Plan ready | Roadmap 20 เรื่อง + PLAN + PROGRESS + reference ที่ผู้ใช้ยืนยัน |
| M1 — First complete Lab | Lab 01 ครบทั้ง brief, design, app/scripts, guide, tests, cleanup และ review |
| M2 — Labs 02–05 | ทำทีละเรื่องจน guide-ready |
| M3 — Labs 06–10 | ทำทีละเรื่องจน guide-ready |
| M4 — Labs 11–15 | ทำทีละเรื่องจน guide-ready |
| M5 — Labs 16–20 | ทำทีละเรื่องจน guide-ready |
| M6 — Collection review | ตรวจทั้ง 20 เรื่อง, skill coverage และ navigation พร้อมสรุปข้อจำกัด |

ไม่เริ่มเขียน Guide ทั้ง 20 พร้อมกัน และไม่ใช้เอกสารชื่อ Lab ที่มีแต่ placeholder แทนผลงานที่เสร็จแล้ว

## Definition of done — Guide-ready

- โจทย์และ Requirements ชัด; criteria ตรวจได้ ไม่ใช้คำว่าทำงานได้เฉย ๆ
- Diagram ใช้ provider icons, nested boundaries ที่ถูกต้อง, layout จาก connectivity, เส้นไม่อ้อมและไม่กำกวม
- App และข้อมูลประกอบพร้อมใช้ ไม่ต้องให้ผู้เรียนไปคิด App ใหม่ก่อนเริ่ม Lab
- ขั้นตอนระบุ Console/Cloud Shell/VM/เครื่องผู้เรียน และ path/variable ที่ใช้ต่อกันได้
- มีตัวอย่าง Expected output ที่ติดป้ายแยกจาก Actual และไม่มีภาพ Console ปลอม
- ครอบคลุม normal flow, access boundaries, operational fault/recovery และ change request ตาม Solution
- ช่องบันทึกผลและหลักฐานอยู่ติดจุดตรวจ พร้อมชื่อไฟล์/สิ่งที่ภาพหรือ Log ต้องพิสูจน์
- มี troubleshooting ที่ใช้แยกสาเหตุ, cleanup/resource inventory และ rebuild entry point
- ตรวจ version/region/edition/quotas/IAM/domain assumptions กับเอกสารทางการ ณ ตอนเขียน
- ทดสอบ scripts/App ตามที่ cloud execution environment ทำได้ และระบุ external/cloud checks ที่ยังไม่ได้รัน
- เนื้อหาขึ้น GitHub และตรวจอ่านกลับแล้ว; สถานะ PROGRESS ตรงกับงานจริง

Guide-ready ไม่เท่ากับ Cloud-verified โดย Cloud-verified ต้องมีผลจากการสร้าง/ทดสอบทรัพยากรจริงพร้อมหลักฐาน

## ขอบเขตสิทธิ์และการเผยแพร่

- อนุญาตจัดทำเอกสาร code/tests และบันทึกลง Repo นี้ตามงาน
- ทำงานผ่าน branch/PR เพื่อให้ review ได้ ไม่ force-push หรือแก้ sharing/visibility
- อย่าใส่ credentials, runtime exports, ผลทดสอบที่มีข้อมูลเครื่องส่วนตัว หรือไฟล์ชั่วคราวลง Repo
- ไม่มีการ deploy เว็บไซต์ Portfolio หรือใช้บัญชี GCP สร้างทรัพยากรที่คิดค่าใช้จ่ายใน Goal นี้
- หากต้องใช้สิทธิ์/บริการภายนอกที่ไม่มีจริง ให้บันทึกข้อจำกัดและทำงานที่ตรวจได้ต่อ ไม่แต่งผลสำเร็จ

## ข้อความตั้ง Goal ที่พร้อมใช้

> จัดทำ GCP Solution Labs ทั้ง 20 เรื่องใน repository somkid-s5/Portfolio-Lab ตาม PLAN.md และ GCP/ROADMAP.md ให้ครบระดับ Guide-ready ทำทีละ Lab เริ่มจาก Lab 01: วาง brief และ architecture ให้ชัดก่อนเขียน Task/README พร้อม App, scripts, Diagram และการตรวจที่เหมาะสม เมื่อ Lab ปัจจุบันผ่าน self-review แล้วจึงไป Lab ถัดไป บันทึกงานบน GitHub ผ่าน branch/PR และอัปเดต GCP/PROGRESS.md ทุก checkpoint ทำใน Cloud โดยไม่พึ่ง laptop ไม่สร้างทรัพยากร GCP ที่คิดค่าใช้จ่าย ไม่ deploy เว็บไซต์ Portfolio และไม่อ้าง Cloud-verified เมื่อยังไม่ได้รันจริง

## สิ่งที่ยังไม่เริ่มในรอบวางแผน

ยังไม่ตั้ง Goal อัตโนมัติ และยังไม่เริ่มสร้าง Lab 01–20 ผู้ใช้จะเป็นผู้เริ่ม Goal เมื่อพร้อม
