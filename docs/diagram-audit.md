# Diagram design alignment — 20 GCP Solution Labs

วันที่ตรวจ: 2026-10-25 · เป้าหมายภาพ: [Personal Custom Diagram Style](diagram-style.md)

## นิยามสถานะ

- **Asset-ready:** มี SVG ที่แก้ไขได้และ Markdown ชี้ไปยัง `assets/diagrams/`; ไม่ได้แปลว่างานภาพใช้รูปแบบเดียวกัน
- **Token-aligned (static):** พบชุดสีหลักของ Personal Custom ใน source SVG; ยังต้องเปิดภาพตรวจ layout
- **Visual-reviewed:** คนตรวจภาพ Render จริงที่ความกว้างการอ่าน ยืนยัน routing, icon, labels, geometry, scopes และไม่หลอกเรื่อง Cloud resource placement
- **Skill-rendered:** ยืนยันกระบวนการสร้าง/ปรับด้วย Diagram Design Personal Custom Skill ที่ **เรียกใช้ได้จริง** พร้อม source/verification ไม่ใช่แค่ comment

## ผลตรวจ Source SVG (static signature)

ทุก Lab มี `solution.svg` พร้อม title, description และ aria label และไฟล์แสดงผลถูกเก็บใน `assets/diagrams/`. การตรวจ token เป็นเพียงการดูค่า literal `#F7FAFF`, `#2563EB`, `#0F766E` ใน SVG ไม่ใช่การตรวจภาพแสดงผล

| Lab | Personal Custom palette signatures ใน SVG | Visual review | Action |
|---|---|---|---|
| 01 | Not fully present | Pending | ตรวจ Render, grouping, connector, icon provenance และปรับด้วย Skill เมื่อเรียกใช้ได้ |
| 02 | Not fully present | Pending | ตรวจ Render, grouping, connector, icon provenance และปรับด้วย Skill เมื่อเรียกใช้ได้ |
| 03 | Not fully present | Pending | ตรวจ Render, grouping, connector, icon provenance และปรับด้วย Skill เมื่อเรียกใช้ได้ |
| 04 | Not fully present | Pending | ตรวจ Render, grouping, connector, icon provenance และปรับด้วย Skill เมื่อเรียกใช้ได้ |
| 05 | Not fully present | Pending | ตรวจ Render, grouping, connector, icon provenance และปรับด้วย Skill เมื่อเรียกใช้ได้ |
| 06 | Not fully present | Pending | ตรวจ Render, grouping, connector, icon provenance และปรับด้วย Skill เมื่อเรียกใช้ได้ |
| 07 | Not fully present | Pending | ตรวจ Render, grouping, connector, icon provenance และปรับด้วย Skill เมื่อเรียกใช้ได้ |
| 08 | Not fully present | Pending | ตรวจ Render, grouping, connector, icon provenance และปรับด้วย Skill เมื่อเรียกใช้ได้ |
| 09 | Not fully present | Pending | ตรวจ Render, grouping, connector, icon provenance และปรับด้วย Skill เมื่อเรียกใช้ได้ |
| 10 | Not fully present | Pending | ตรวจ Render, grouping, connector, icon provenance และปรับด้วย Skill เมื่อเรียกใช้ได้ |
| 11 | Not fully present | Pending | ตรวจ Render, grouping, connector, icon provenance และปรับด้วย Skill เมื่อเรียกใช้ได้ |
| 12 | Partial (blue, teal) | Pending | ตรวจ Render, grouping, connector, icon provenance และปรับด้วย Skill เมื่อเรียกใช้ได้ |
| 13 | Not fully present | Pending | ตรวจ Render, grouping, connector, icon provenance และปรับด้วย Skill เมื่อเรียกใช้ได้ |
| 14 | Not fully present | Pending | ตรวจ Render, grouping, connector, icon provenance และปรับด้วย Skill เมื่อเรียกใช้ได้ |
| 15 | Canvas + blue + teal | Pending | ตรวจ Render, grouping, connector, icon provenance และปรับด้วย Skill เมื่อเรียกใช้ได้ |
| 16 | Canvas + blue + teal | Pending | ตรวจ Render, grouping, connector, icon provenance และปรับด้วย Skill เมื่อเรียกใช้ได้ |
| 17 | Canvas + blue + teal | Pending | ตรวจ Render, grouping, connector, icon provenance และปรับด้วย Skill เมื่อเรียกใช้ได้ |
| 18 | Canvas + blue + teal | Pending | ตรวจ Render, grouping, connector, icon provenance และปรับด้วย Skill เมื่อเรียกใช้ได้ |
| 19 | Canvas + blue + teal | Pending | ตรวจ Render, grouping, connector, icon provenance และปรับด้วย Skill เมื่อเรียกใช้ได้ |
| 20 | Canvas + blue + teal | Pending | ตรวจ Render, grouping, connector, icon provenance และปรับด้วย Skill เมื่อเรียกใช้ได้ |

## ข้อพบจากโครงสร้าง

- **01–11, 13–14:** มี source SVG และหลักฐานบางส่วน แต่ไม่ใช้ palette ครบตาม literal tokens ของแนวทางปัจจุบัน จึง **ยังอ้างไม่ได้** ว่ามี visual style เหมือน Lab 15–20
- **12:** มีบางสีตรง standard แต่ canvas signature ยังต่าง จึงยังต้องตรวจด้วยสายตา
- **15–20:** source พบ palette หลักตรง guide แต่ยังไม่มีบันทึก human visual review ที่ยืนยันว่าองค์ประกอบและเส้นถูกต้องในทุกภาพ
- เดิม 01–08 ฝัง PNG preview เป็นหลัก ขณะที่ Lab หลังใช้ inline SVG; ตอนนี้ Markdown อ้างภาพใน `assets/diagrams/` สม่ำเสมอแล้ว แต่ยังมีความต่างเรื่อง output format ตามต้นฉบับ
- ไม่พบไฟล์ `diagram-design.zip` ใน tracked Git Tree; provenance อ้างอิง ZIP ส่วนตัว แต่ **ยังพิสูจน์ไม่ได้** ว่า Skill ถูกเรียกใช้สร้างทุกภาพจริง

## ขั้นตอน Review ที่ต้องทำกับไฟล์ภาพจริง

1. ใช้ Diagram Design Personal Custom Skill ตัวเดียวกันเปิดหรือปรับ SVG ของ Lab 01–20 ตาม [style](diagram-style.md); **ไม่ปรับโครงสร้าง Cloud เพื่อให้ดูสวยแต่ผิดเทคนิค**
2. Render แต่ละ Diagram ที่ 900–1000 px พร้อมตรวจ icon source, labels/line crossing, layout และ GCP scope ด้วยสายตา
3. Sync SVG/PNG/HTML publication กับ compatibility mirror; ตรวจด้วย `python scripts/check-diagram-mirrors.py`
4. บันทึก Reviewer, วันที่, ภาพ preview, สิ่งที่เปลี่ยน และสถานะ Visual-reviewed ราย Lab ก่อนกล่าวว่า Design Consistency ผ่าน

> สถานะปัจจุบัน: **20/20 Asset-ready; 0/20 certified Visual-reviewed**. นี่ไม่ใช่คำตัดสินว่า Diagram ทุกภาพมีปัญหา แต่เป็นการแยกการมีไฟล์ออกจากการตรวจสายตาแบบมืออาชีพ
