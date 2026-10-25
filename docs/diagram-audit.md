# GCP Diagram Alignment Audit — 20 Solution Labs

ตรวจเมื่อ 2026-10-25 · [มาตรฐานหลัก](diagram-style.md) · อ้างอิง `assets/diagrams/`

## ความหมายของ "แนวทางเดียวกัน"

- **Structural alignment:** ทุก Lab มีภาพหลัก `assets/diagrams/solution.svg` ที่แก้ไขได้ และ README เชื่อมด้วย relative path
- **Design-system alignment:** ใช้แนวคิดเดียวกันในการแยก project/region/network, official service icons, typography, functional palette, connections และ failure/management paths (ไม่ได้บังคับว่าทุก Lab ต้องใช้สีครบทุกสี)
- **Visual certification:** เปิดภาพที่ render จริง วัดความชัดของชื่อ, เส้นไม่ชน, icon/source, ความเที่ยงตรงของ scope และความหมายของ route ต้องผ่านการตรวจเชิงภาพเฉพาะ Lab
- **Skill provenance:** เอกสารระบุเพียง reference จาก ZIP; การมี SVG/คำว่า "Diagram Design" ไม่ได้พิสูจน์ว่าได้เรียก Personal Custom Skill

## ผลตรวจ Source SVG (case-insensitive)

ตรวจ **ค่าสีใน SVG แบบไม่สนใจตัวพิมพ์เล็ก/ใหญ่**; ค่าที่ไม่ปรากฏอาจเป็นเพราะ topology ไม่จำเป็นต้องใช้สีบทบาทนั้น และห้ามตีความอัตโนมัติว่า "ไม่เป็นแนวเดียวกัน"

| Lab | App blue #2563EB | Network teal #0F766E | Paper #F7FAFF | Diagram review |
|---|:---:|:---:|:---:|---|
| 01 | ✓ | ✓ | — | Rendered and visually inspected; not runtime-certified |
| 02 | ✓ | ✓ | — | Rendered and visually inspected; not runtime-certified |
| 03 | ✓ | ✓ | — | Rendered and visually inspected; not runtime-certified |
| 04 | ✓ | ✓ | — | Rendered and visually inspected; not runtime-certified |
| 05 | ✓ | ✓ | — | Rendered and visually inspected; not runtime-certified |
| 06 | ✓ | — | — | Rendered and visually inspected; not runtime-certified |
| 07 | ✓ | ✓ | — | Rendered and visually inspected; not runtime-certified |
| 08 | ✓ | ✓ | — | Rendered and visually inspected; not runtime-certified |
| 09 | ✓ | ✓ | — | Rendered and visually inspected; not runtime-certified |
| 10 | ✓ | ✓ | — | Rendered and visually inspected; not runtime-certified |
| 11 | ✓ | ✓ | ✓ | Rendered and visually inspected; not runtime-certified |
| 12 | ✓ | ✓ | — | Rendered and visually inspected; not runtime-certified |
| 13 | ✓ | ✓ | ✓ | Rendered and visually inspected; not runtime-certified |
| 14 | ✓ | ✓ | — | Rendered and visually inspected; not runtime-certified |
| 15 | ✓ | ✓ | ✓ | Rendered and visually inspected; not runtime-certified |
| 16 | ✓ | ✓ | ✓ | Rendered and visually inspected; not runtime-certified |
| 17 | ✓ | ✓ | ✓ | Rendered and visually inspected; not runtime-certified |
| 18 | ✓ | ✓ | ✓ | Rendered and visually inspected; not runtime-certified |
| 19 | ✓ | ✓ | ✓ | Rendered and visually inspected; not runtime-certified |
| 20 | ✓ | ✓ | ✓ | Rendered and visually inspected; not runtime-certified |

**ข้อเท็จจริงที่สรุปได้จาก source:** 20/20 ภาพมีสีน้ำเงินหลัก, 19/20 มีสี teal, 8/20 ใช้สีพื้นกระดาษอ่อนตรง token; ทุกภาพมี accessible `title`/`desc` และ `role="img"`. White canvas ยังอยู่ภายใต้มาตรฐานที่ยอมรับ white/pale canvas. ไม่ควรใช้การไม่มีค่าสีเพียงอย่างเดียวตัดสินคุณภาพของ Diagram

**จุดแตกต่างที่ต้องตรวจภาพจริง:** Lab 13 ปรับ semantic palette ใน SVG/HTML ให้ตรงสีหลักด้วยการแก้ Source โดยตรง (รักษา provider icons และ route geometry เดิมไว้; **ไม่ได้ใช้ Personal Custom Skill**); Lab 06 ไม่ใช้ Network/VPC teal เพราะ Solution นี้ **ไม่มี VPC** ตามสถาปัตยกรรมที่ระบุใน SVG; ไม่ควรเติม Network panel หรือสีเพียงเพื่อให้ครบ palette; Lab 01–08 ใช้ PNG Preview ใน README เป็นหลัก ในขณะที่ Lab ถัดไปนิยมแสดง SVG; 01–08 ไม่จำเป็นต้อง redraw หาก layout ชัดเจนอยู่แล้ว. รูปแบบ font-size, label spacing, icon size และ connection geometry อาจยังไม่สม่ำเสมอ

## สถานะและเกณฑ์ปิดงาน

| เกณฑ์ | ผล |
|---|---|
| Architecture SVG แก้ไขได้ในที่เดียวกันครบ 20 Lab | **ผ่าน 20/20** |
| Relative diagram links ของ README ทุก Lab ชี้เป้าจริง | **ผ่าน 20/20** |
| Compatibility asset mirrors ตรงกับ canonical files | **ผ่าน 60/60** ณ revision ที่ตรวจ |
| Architecture semantics/diagram rendering inspected manually at 1000 px | **ตรวจภาพจริงครบ 20/20 ที่ 960–1000 px** (visual QA ไม่ใช่ GCP-runtime proof) |
| Personal Custom Diagram Design Skill invocation verified | **ตรวจยืนยันไม่ได้ในสภาพแวดล้อม Cloud นี้** |

## Final render inspection — 2026-10-25

- เปิดภาพหลักของ Lab **01–20 ครบ**: Lab 01–08 ใช้ PNG preview ใน Repo; Lab 09–20 render SVG source ที่ document width 1000px ผ่าน CI workflow #457 และตรวจภาพจริง
- ตรวจความอ่านได้ของ icon/label, project/region/VPC scope, ความหมายของเส้นและพื้นที่ว่างเท่าที่พิสูจน์จากภาพ static; แก้ Lab 11/13/15 เรื่อง header contrast ที่ถูก global CSS override, Lab 16 เรื่องข้อความเส้นทางทับ region, Lab 20 เรื่อง title layering และ boundary. Sync `assets/diagrams/solution.svg` กับ mirrors/HTML
- ติดตั้ง pinned Thai font ในการทำ preview ลดปัญหาตัวอักษรไทย fallback; layout ต่างกันตาม topology ได้โดยไม่ต้องใช้สี/องค์ประกอบเท่ากันทุก Lab
- **หลักฐานว่าเรียกใช้ Personal Custom Diagram Design Skill ยังไม่มี** เนื่องจาก Skill นี้ไม่ callable ในสภาพแวดล้อมนี้; อ้าง ZIP เป็น style reference เท่านั้น. ไม่อ้างว่า Skill-certified
- Manual image review ไม่ใช่การตรวจว่าบริการ IAM/network/region ทุกคำสั่ง Deploy ผ่าน GCP จริง (Cloud verification = Not run); ตอนทำ Lab ถ้าแบบจริงต่างจากภาพต้องแก้และบันทึกหลักฐาน

**คำตัดสิน:** ผ่านการตรวจโครงสร้างไฟล์และ Visual QA ของภาพหลัก 20/20 เพื่อเผยแพร่ **Guide-ready**; ไม่ใช่ Cloud-verified หรือการรับรอง Skill provenance.
