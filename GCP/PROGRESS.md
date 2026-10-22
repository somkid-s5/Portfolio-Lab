# GCP Labs — Progress

สถานะ Guide กับผล Cloud แยกกัน ไม่ใช้ PASS จากการตรวจเอกสารแทนการทดสอบจริง

| Lab | Solution | Guide status | Cloud verification | PR / checkpoint |
|---|---|---|---|---|
| 01 | [เว็บหลาย Zone หลัง Load Balancer](LAB-001-multi-zone-web/README.md) | Guide-ready | Not run | [PR #1](https://github.com/somkid-s5/Portfolio-Lab/pull/1) |
| 02 | [ระบบ Inventory ภายในองค์กรแบบ Private](LAB-002-private-inventory/README.md) | Guide-ready | Not run | [PR #1](https://github.com/somkid-s5/Portfolio-Lab/pull/1) |
| 03 | [เว็บไซต์เอกสารสาธารณะผ่าน CDN และ HTTPS](LAB-003-public-docs-cdn/README.md) | Review | Not run | [PR #1](https://github.com/somkid-s5/Portfolio-Lab/pull/1) |
| 04 | ระบบจองบริการบน Serverless และ Private Database | Planned | Not run | — |
| 05 | ระบบธุรกรรมสามชั้นบน VM | Planned | Not run | — |
| 06 | ระบบรับและประมวลผลไฟล์อย่างปลอดภัย | Planned | Not run | — |
| 07 | ระบบรับคำสั่งซื้อและประมวลผลงานผ่าน Queue | Planned | Not run | — |
| 08 | ระบบรายงานตามเวลาและงาน Batch รายวัน | Planned | Not run | — |
| 09 | ระบบส่ง Webhook ให้ระบบคู่ค้า | Planned | Not run | — |
| 10 | ระบบ Catalog ที่ใช้ Cache ลดภาระ Database | Planned | Not run | — |
| 11 | ระบบบริการบน GKE ที่ Deploy และขยายได้ | Planned | Not run | — |
| 12 | ระบบ Microservices ที่ติดตามปัญหาข้ามบริการได้ | Planned | Not run | — |
| 13 | ระบบประมวลผลข้อมูลนำเข้าแบบขนาน | Planned | Not run | — |
| 14 | แพลตฟอร์มส่งมอบ App สำหรับทีมพัฒนา | Planned | Not run | — |
| 15 | ระบบสำนักงานสาขาเชื่อมบริการ Private บน Cloud | Planned | Not run | — |
| 16 | ย้ายระบบ Legacy พร้อมข้อมูลขึ้น Cloud | Planned | Not run | — |
| 17 | ระบบจัดเก็บข้อมูลพร้อมแผนกู้คืนที่ทดสอบได้ | Planned | Not run | — |
| 18 | แพลตฟอร์มสร้าง Environment ให้ทีมใหม่ | Planned | Not run | — |
| 19 | ระบบเฝ้าระวังและรับ Incident สำหรับทีมบริการ | Planned | Not run | — |
| 20 | แพลตฟอร์มจองและสร้างรายงานแบบรับมอบงานได้ | Planned | Not run | — |

Guide status: Planned → Brief → Design → Authoring → Review → Guide-ready

Cloud verification: Not run → In progress → Verified / Failed / Blocked (ต้องมีหลักฐานจริง)

## Current checkpoint

M1 / Lab 01: Guide-ready — คู่มือครบ Tasks 0–10/8B, normal/fault/recovery/load/access/change/backout/cleanup/rebuild, code และภาพก่อน/หลังเปลี่ยน อ่านกลับจาก GitHub แล้ว

[CI run 39809864366](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39809864366) ของ commit `3a5f312c21355f9254f1deee776ca26c4d4dbcf4`: shell syntax, Python compile, 10 tests และ render SVG สองแบบผ่าน ตรวจภาพ baseline/after-change ที่ 960px แล้ว PNG ถูกบันทึกใน assets พร้อม SVG editable และเครดิตไอคอน

ขอบเขต: ไม่ได้สร้าง GCP resources, ไม่ได้ทดสอบ IAP/firewall/LB health จริง หรือ apt/systemd ใน GCE ผล cloud ทุก Lab ยัง Not run ไม่ใช้ CI เป็นหลักฐาน Cloud-verified

M2 / Lab 02: Design และ Build materials — บันทึก access matrix, app contract, PostgreSQL schema/seed/invariants และ real-DB integration tests แล้ว กำลังตรวจ cloud CI ก่อนเขียน Tasks คู่มือเต็ม

Lab 02 materials checkpoint: [CI 39810811347 / job lab002](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39810811347) รัน App สอง process กับ PostgreSQL 15 จริงและผ่าน 7 integration tests: shared data, auth/validation, retry/conflict, concurrent overdraw, concurrent duplicate key, non-destructive seed และ health/search ใช้ฐานข้อมูล CI ชั่วคราว ไม่ใช่ผล Deploy GCP; secret-generator/installer tests เพิ่มเติมยังอยู่ระหว่างตรวจ

Lab 02: [CI 39811584409](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39811584409) ผ่าน runtime-role และ learner probe tests กับ PostgreSQL 15 รวม 10 tests (Inventory 9 + secrets 1), App สอง process ใช้ inventory_app ที่ไม่มี superuser/DDL/delete-ledger และตรวจ no-overwrite/no-token-leak ของ probe แล้ว README มี Tasks 0–5; ยังต้องเติม LB/DNS/tests/ops/change/cleanup/diagram ก่อน Review

Lab 02 / Review: README ครบ Tasks 0–12 พร้อม App/schema/least-privilege grants/secrets/probe และ Diagram สองมุมมอง [CI 39813178436 job lab002](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39813178436) ผ่าน 15 tests, installer shell syntax และ SVG render ภาพตรวจที่ 960px แล้ว พบ DNS association line เบียด label จึงขยับและรอภาพใหม่ก่อนปิด Review; ยังไม่มี GCP provisioning หรือผลจริง T00–T12

Lab 02: Guide-ready หลัง [CI 39813493443](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39813493443) / commit 11c260e ผ่าน 15 tests และ render สองภาพ ตรวจภาพรอบแก้แล้ว เก็บ PNG/SVG พร้อม attribution คู่มือครบทั้ง build/test/operate/change/evidence/cleanup/rebuild ขั้นถัดไป Lab 03 Brief ก่อน Tasks ทุก Lab ยัง Cloud Not run

Lab 03 / Design + Materials: เลือก EXTERNAL_MANAGED backend bucket ตามคู่มือ official global setup มี v1/v2/bad release fixtures, deterministic builder, SHA256 manifests, dry-run publisher (assets/archive generation0 ก่อน root generation fence), rollback remote integrity checks และ bounded HTTP probe; กำลังตรวจ CI ยังไม่ใช่ Guide-ready และไม่มี cloud writes

Lab 03 / Authoring: README ครบ Tasks 0–11 (DNS/TLS/CDN/content tests/v2 publish/bad-release rollback/HTML TTL15 change/public-read boundary/cleanup), มี URL map renderer และ code tests เพิ่มเติม ยังรอ CI jobs ที่อยู่ queued ตาม handle จริง ไม่ rerun ซ้ำเพียงเพราะรอ และยังเหลือ Diagram/Review ก่อน Guide-ready

Lab 03 / Review: คู่มือ Tasks 0–11, release materials และ SVG delivery/release-flow พร้อม attribution อยู่บน branch แล้ว ยังต้องยืนยัน tests และดู rendered previews จาก CI ก่อน Guide-ready; CI รอบ 39815687613 ยืนยันว่า queued ณ ตอนตรวจ ไม่ได้ terminal จึงไม่ถือว่ารันทดสอบล้มเหลวหรือผ่าน และไม่เริ่ม Lab 04 ก่อนปิด Lab 03

Lab 03 review refinement: เพิ่ม --reuse-assets สำหรับ partial publish โดย verify remote CSS ก่อน archive/root uploads มี tests ตรวจหยุดเมื่อ hash ไม่ตรง GitHub run 39816163024 ยังคง Queued ตามทั้ง API และหน้าเว็บ; GitHub Status วันที่ 22 ต.ค. 2026 รายงาน Actions degraded (https://www.githubstatus.com/) เป็นข้อมูลประกอบ ไม่ใช่หลักฐานว่า test ผ่าน หลีกเลี่ยง local fallback เพราะ runtime ที่ตรวจพบเป็น win32 บน laptop
