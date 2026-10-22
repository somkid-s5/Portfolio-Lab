---
lab: LAB-003
platform: GCP
guide_status: design
cloud_verification: not-run
last_verified: null
---
# Lab 03 — เอกสารสาธารณะผ่าน CDN และ HTTPS ที่อัปเดตและย้อนเวอร์ชันได้

ทีม Support ต้องเผยแพร่คู่มือผลิตภัณฑ์ให้ลูกค้าเปิดผ่าน HTTPS ได้ทั่วถึง ปัญหาไม่ได้จบที่อัปโหลด HTML: เมื่อเปลี่ยนเอกสารต้องไม่เห็นหน้าใหม่กับ CSS เก่าปนกัน และถ้าปล่อยเนื้อหาผิดต้องย้อนกลับได้โดยพิสูจน์จาก version/hash ไม่ใช่แค่กด refresh แล้วคิดว่าหาย

## Requirements และขอบเขต Solution

| ID | ความต้องการ | วิธีพิสูจน์ / หลักฐาน |
|---|---|---|
| R1 | เข้าคู่มือผ่าน HTTPS ด้วยชื่อที่ทีมควบคุม | DNS A ตรง frontend IP, managed certificate ACTIVE และ TLS validation ผ่านโดยไม่ใช้ -k; เก็บ hostname/certificate และ HTTP status |
| R2 | เผยแพร่เนื้อหา/asset ครบและอ้างอิงตรง release | หน้า /index.html แสดง release ID; CSS content-hash URL โหลด200 และ SHA256 ตรง manifest; ไม่ทิ้งไฟล์ให้ผู้เรียนคิดเอง |
| R3 | Cache ตามชนิดไฟล์ | index.html public,max-age=60; immutable hashed assets max-age=31536000; ดู metadata/headers และ CDN cache-hit logs หลัง warmup ไม่ใช้ latency อย่างเดียวพิสูจน์ hit |
| R4 | อัปเดตเป็น v2 โดยไม่เสีย asset consistency | อัปโหลด immutable assets ก่อน index, publish index ด้วย generation precondition; ตรวจ release ID/hash หลัง TTL หรือ targeted invalidation |
| R5 | วินิจฉัยและกู้ bad release | ปล่อย bad release ที่ควบคุมไว้ ตรวจอาการจาก HTTP/content/hash แล้ว publish index v1 กลับด้วย generation fence; invalidate เฉพาะ path ที่จำเป็นและตรวจผลใหม่ |
| R6 | สิทธิ์ Public content ชัดและไม่อ้าง origin isolation | เฉพาะ bucket Lab เป็น public read; ไม่มี secret/customer data; anonymous write ต้องไม่สำเร็จ; ตรวจ IAM และ organization Public Access Prevention ก่อนเริ่ม |
| R7 | Change request: HTML กับ asset TTL ต่างกัน | เปรียบเทียบ update ก่อน/หลังเลือก TTL และ fingerprinted URLs; บันทึก stale object behavior และข้อจำกัด browser cache |
| R8 | Cleanup/rebuild ครบ | ลบ frontend/proxy/URL map/backend bucket/cert/reserved IP/objects versions/bucket และ DNS record ของ Lab ตาม dependency; บันทึก commit/config/resources จริง |

## Architecture ที่จะยืนยันก่อนเขียน Tasks

Global external Application LB + Cloud CDN + Cloud Storage backend bucket + public DNS + Google-managed certificate ไม่มี VM/VPC/subnet ในเส้นทางนี้ ไม่ใส่กรอบ network ที่ไม่ได้สร้าง

เลือก **Global external Application Load Balancer รุ่น EXTERNAL_MANAGED** กับ backend bucket ตาม [คู่มือ setup รุ่น global](https://docs.cloud.google.com/load-balancing/docs/https/setup-global-ext-https-buckets) ใช้ HTTP proxy สำหรับ redirect และ HTTPS proxy สำหรับ content ไม่มีการปน EXTERNAL ของ classic ในชุดเดียวกัน

Cloud Storage origin baseline เป็น public-readable สำหรับเอกสารสาธารณะ จึงอาจอ่าน origin URL โดยตรงได้ ไม่อ้างว่าใครต้องผ่าน CDN เสมอ TLS termination ที่ LB ไม่ทำให้ origin private โดยอัตโนมัติ ไม่เปิด signed URL/private bucket complexity มาปะปนกับ baseline

## Domain, IAM และค่าใช้จ่ายที่เป็นเงื่อนไขเริ่ม

- ผู้เรียนต้องมี subdomain ที่ควบคุม DNS ได้จริง ไม่มีการซื้อ domain หรือเปลี่ยน DNS ของงานจริงโดยอัตโนมัติ ไม่มี domain ให้บันทึก BLOCKED ของ HTTPS; HTTP/IP-only test ไม่ถือว่าผ่าน R1
- หากองค์กรบังคับ Public Access Prevention ห้ามปิดนโยบายเพื่อทำ Lab ให้ใช้ sandbox ที่ได้รับอนุญาตหรือทบทวน solution ใหม่
- Bucket เก็บเฉพาะ demo docs ใช้ uniform bucket-level access และ public object viewer ตาม scope ไม่ให้ allUsers มีสิทธิ์เขียน
- ตรวจ Compute/LB, Storage, certificate และ DNS permissions ตามวิธีที่เลือก ไม่ขอ Owner เพื่อแก้ทุก error
- มีต้นทุน LB/static IP/storage/CDN egress/cache fill/requests/logs และ DNS ถ้าสร้าง zone แยก Budget ไม่ใช่ hard cap เปิดเวลาจำกัดแล้ว cleanup
- งานจัดทำคู่มือไม่สร้างทรัพยากร ไม่เปลี่ยน DNS และไม่ Deploy เว็บไซต์ใดจริง ผู้เรียนรันหลังตรวจงบ/สิทธิ์ของตนเอง

## Release materials ที่ต้องมี

สร้างตัวอย่างคู่มือผลิตภัณฑ์อย่างน้อยสอง release พร้อม release ID, immutable CSS/JS, local manifest ระบุ SHA256/size/MIME/cache metadata และ bad-release fixture ที่เปลี่ยนกลับได้ เครื่องมือ build/release ต้องไม่เขียนทับ output เดิมแบบเงียบ ไม่ใส่ timestamps แบบสุ่มจนตรวจ hash ซ้ำไม่ได้

เครื่องมือ publish ต้อง upload assets ก่อน root index, ตรวจ generation fence, ไม่ลบ asset เก่าทันที และไม่ใช้งาน cloud credentials ใน CI baseline มี bounded HTTP probe เก็บ status/headers/content hash โดยไม่อ้าง cache HIT จาก header ที่ origin ใส่เอง

## ขอบเขตหลักฐานและการออกแบบทดสอบ

แยก browser cache, edge cache และ origin metadata ให้ชัด การ invalidate CDN ไม่ล้าง browser cache และการใช้ URL query สุ่มอาจเปลี่ยน cache key จึงห้ามใส่ cache-buster ใน probe ที่ใช้พิสูจน์ cache hit การ warm จาก client เดียวไม่พิสูจน์ hit ทุก PoP

เก็บ request timestamp/URL/release/hash, cache logs ที่สัมพันธ์กับชุดทดสอบ, certificate/DNS และ before/after metadata ไม่แต่ง screenshot หรือค่า latency เปรียบเทียบที่ไม่ได้วัด

## ลำดับหลัง Brief

ยืนยัน stack/certificate/DNS/access model → สร้าง deterministic release materials/test contracts → Diagram ที่ไม่มี VPC ปลอม → คู่มือ Console/CLI พร้อม publish/fault/rollback/cache change → review/render/cleanup evidence

สถานะ Design / Materials: มี deterministic builder, manifest integrity validator, dry-run publisher และ bounded content probe พร้อม tests กำลังตรวจ cloud CI ยังไม่มีคู่มือเต็มหรือผล Deploy จริง

ไฟล์: [releases](content/releases.json), [build](scripts/build-release.py), [publish](scripts/publish-release.py), [probe](scripts/probe-release.py), [tests](tests/test_release.py)

URL map ใช้ [renderer](scripts/render-config.py) แยก content map (HTTPS; / redirect ไป /index.html) ออกจาก HTTP→HTTPS map ไม่ใส่ httpsRedirect บน map ที่ใช้กับ HTTPS proxy Backend bucket logging เปิดให้อัตโนมัติและไม่มีสวิตช์ sample-rate แบบ backend service ตาม [เอกสาร logging](https://docs.cloud.google.com/load-balancing/docs/https/https-logging-monitoring)

Publisher upload asset/archived index ด้วย generation=0 ก่อนเปลี่ยน root index ด้วย expected generation ที่ผู้ทำป้อน การ rollback ใช้ --index-only และ verify remote bytes ของ asset/archive ก่อนเปลี่ยน index ไม่ลบ asset เก่า ไม่ invalidate cache โดยอัตโนมัติ ไม่เรียก cloud ถ้าไม่ใส่ --apply

## แหล่งอ้างอิงขอบเขต

- [Cloud CDN setup overview](https://docs.cloud.google.com/cdn/docs/using-cdn)
- [Backend bucket setup](https://docs.cloud.google.com/load-balancing/docs/https/ext-load-balancer-backend-buckets)
- [Cloud Storage static website](https://docs.cloud.google.com/storage/docs/hosting-static-website)
- [Cloud CDN cache modes](https://docs.cloud.google.com/cdn/docs/caching)
- [Cache invalidation](https://docs.cloud.google.com/cdn/docs/cache-invalidation-overview)
