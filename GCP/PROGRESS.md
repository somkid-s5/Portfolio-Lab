# GCP Labs — Progress

สถานะ Guide กับผล Cloud แยกกัน ไม่ใช้ PASS จากการตรวจเอกสารแทนการทดสอบจริง

| Lab | Solution | Guide status | Cloud verification | PR / checkpoint |
|---|---|---|---|---|
| 01 | [เว็บหลาย Zone หลัง Load Balancer](LAB-001-multi-zone-web/README.md) | Review | Not run | [PR #1](https://github.com/somkid-s5/Portfolio-Lab/pull/1) |
| 02 | ระบบ Inventory ภายในองค์กรแบบ Private | Planned | Not run | — |
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

M0 เสร็จแล้ว; M1 / Lab 01 อยู่ระหว่าง Review มีคู่มือเต็ม Tasks 0–10 และ Change request 8B, App/startup/probe, Diagram baseline พร้อม PNG และ Diagram หลังเพิ่ม C แล้ว ยังต้องตรวจภาพหลังเปลี่ยนและผล documentation checks รอบล่าสุดก่อน Guide-ready

- [CI 39809105744](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39809105744): shell syntax, Python compile, 6 materials tests และ render baseline ผ่าน ตรวจภาพ PNG ที่ความกว้าง 960px แล้ว
- [CI 39809433657](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39809433657): 6 materials tests ผ่าน แต่ documentation anchor validator ไม่รองรับ combining marks ภาษาไทย แก้ตัวตรวจแล้วใน commit d52cfe4 และรันทดสอบใหม่ ไม่ข้าม test หรือทำเครื่องหมายผ่านย้อนหลัง
- Cloud verification ยัง Not run: ไม่ได้รัน apt/systemd บน GCE หรือสร้าง LB/firewall/IAP การทดสอบบน Ubuntu CI ไม่แทนผล GCP
