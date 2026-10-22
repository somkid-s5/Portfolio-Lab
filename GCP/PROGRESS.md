# GCP Labs — Progress

สถานะ Guide กับผล Cloud แยกกัน ไม่ใช้ PASS จากการตรวจเอกสารแทนการทดสอบจริง

| Lab | Solution | Guide status | Cloud verification | PR / checkpoint |
|---|---|---|---|---|
| 01 | [เว็บหลาย Zone หลัง Load Balancer](LAB-001-multi-zone-web/README.md) | Guide-ready | Not run | [PR #1](https://github.com/somkid-s5/Portfolio-Lab/pull/1) |
| 02 | [ระบบ Inventory ภายในองค์กรแบบ Private](LAB-002-private-inventory/README.md) | Design | Not run | [PR #1](https://github.com/somkid-s5/Portfolio-Lab/pull/1) |
| 03 | เว็บไซต์เอกสารสาธารณะผ่าน CDN และ HTTPS | Planned | Not run | — |
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
