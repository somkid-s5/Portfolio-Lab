---
lab: LAB-005
platform: GCP
guide_status: brief
cloud_verification: not-run
last_verified: null
---
# Lab 05 — ระบบสั่งซื้อสามชั้นบน VM ที่รับมือ App failure และ Database failover ได้

ทีมขายมีเว็บสั่งซื้อที่ต้องแยก Web, API และฐานข้อมูลออกจากกัน ต้องปล่อย App รุ่นใหม่โดยไม่หยุดทุกเครื่องพร้อมกัน และต้องรู้ว่าระหว่างฐานข้อมูลสลับ primary คำสั่งซื้อใดสำเร็จ คำสั่งใดควร retry โดยไม่ตัดสต็อกซ้ำ

## ผู้ใช้และเส้นทางธุรกิจ

ลูกค้าสองบัญชีและ operator ใช้ข้อมูลสังเคราะห์ ผู้ใช้ login → ดูสินค้า/สต็อก → ส่งคำสั่งซื้อ → ดูรายการของตน → ยกเลิกและคืนสต็อกหนึ่งครั้ง Operator ดูรายการรวมเพื่อเทียบกับ ledger แต่ไม่ใช้สิทธิ์ Cloud IAM มาแทน App role

ชุด App ต้องมี UI ที่ใช้งานได้, PostgreSQL schema/seed, health endpoints, structured logs และ bounded HTTP probes ครบ ไม่ให้ผู้เรียนสร้าง App เองก่อนทำระบบ

## Requirements และวิธีพิสูจน์

| ID | Must-have | Acceptance / หลักฐานที่ต้องเก็บ |
|---|---|---|
| R1 | HTTPS user journey ผ่าน Web → private API → SQL | login/list/create/read/cancel ทำงานจริง เก็บ order reference, request IDs และผลจาก DB โดยไม่เปิด API/DB สาธารณะ |
| R2 | แยก tier และ runtime identity | Web/API VMs ไม่มี external IP; Web SA อ่าน DB secret ไม่ได้; client ที่ไม่ใช่ Web tier เข้า API VIP/backend ไม่ได้ตาม firewall matrix; anonymous/other-owner/operator negative tests |
| R3 | ธุรกรรมถูกต้องแม้คำขอพร้อมกันหรือซ้ำ | หลาย API process ใช้ DB เดียว ไม่ขายเกิน stock; retry key เดิมได้ order เดิม; key เดิมเปลี่ยน payload ได้ 409; cancel ซ้ำไม่คืน stock ซ้ำ; stock/ledger reconciliation ไม่มีส่วนต่าง |
| R4 | Web/API แต่ละ tier อยู่สอง zone และรับมือ App เครื่องเดียวเสีย | กำหนด fault กับหนึ่ง VM/หนึ่ง process ตรวจ LB health, MIG action, surviving requests และ recovery instance ID; ไม่อ้าง zone outage จริงจากการหยุด process เดียว |
| R5 | Rolling update ที่ตรวจและถอยได้ | ทดสอบ compatible v2 และ bad startup template; บันทึก current actions/healthy replicas/errors; backout template ที่ยังอ่าน schema เดิมได้ ไม่อ้างว่า update policy รับประกัน zero errors |
| R6 | Cloud SQL HA และ reconnect หลัง planned failover | ใช้ Enterprise REGIONAL private SQL; ตรวจ primary/standby configuration และ operation จริงก่อน-หลัง failover; วัดช่วง error/recovery จาก probe; retry key เดิมและตรวจ order/stock ไม่ซ้ำ |
| R7 | รับ Change Request เพิ่ม API replicas/connection capacity อย่างมีเหตุผล | API2→4 replicas, pool4 คงเดิม; คำนวณ surge/old/new/admin headroom ก่อนเปลี่ยน เทียบ bounded load/latency/error/DB connections/invariants และทดสอบ backout |
| R8 | มี runbook, evidence, cleanup และ rebuild | ผู้เรียนแยก LB/MIG/process/network/SQL สาเหตุได้ เก็บ timeline/decision/case study และลบ DNS/TLS/LB/MIG/templates/SQL/secrets/NAT/artifacts/VPC ตาม inventory ของ Lab |

Optional extensions ที่ไม่ใช้แทน baseline: mTLS ระหว่าง Web/API, managed login/SSO, autoscaling policy, Cloud Armor, cross-region recovery และ destructive schema migration ต้องออกแบบ/ทดสอบแยก ไม่อ้างว่ามีแล้ว

## Candidate architecture ที่จะยืนยันใน Design

- Region asia-southeast1; Web และ API เป็น regional managed instance groups คนละกลุ่ม กลุ่มละ 2VM กระจายสอง zone ไม่ใช่ unmanaged groups จาก Lab01
- Public global external Application Load Balancer รับ HTTPS ด้วย domain ที่ผู้เรียนควบคุม DNS ได้ ส่งไป Web Nginx บน private VMs
- Web ให้ static UI และ reverse proxy /api ไป **regional internal passthrough Network Load Balancer TCP8080** ซึ่งกระจายไป API VMs ใช้ L4 เพื่อรักษา client source และกำหนด ingress API ให้มาจาก Web tier ตาม matrix ไม่วาดเป็น regional L7proxy หรือเพิ่ม proxy-only subnet โดยไม่มีบริการนั้น
- API ใช้ PostgreSQL transactions/locks/idempotency ledger ผ่าน Cloud SQL Python Connector private IP/TLS ไป Cloud SQL PostgreSQL16 Enterprise REGIONAL (HA) ใน region เดียวกัน
- Custom VPC; แยก regional Web/API subnets; PSA allocation เป็น managed service producer address space ไม่ใช่ subnet ของฐานข้อมูล VM
- Cloud Router/NAT สำหรับ private VM outbound ตามจำเป็น; IAP TCP forwarding + OS Login สำหรับดูแล ไม่เปิด SSH0.0.0.0/0
- Web SA ไม่มี SQLClient/DBSecretAccessor; API SA มีสิทธิ์เฉพาะ SQLClient, App/DBsecret, อ่าน release artifact ที่ต้องใช้ และส่ง logs ตามจำเป็น Bootstrap/admin เป็น identity คนละชุด
- Release artifact ตรึง source commit/hash; instance template ใหม่สำหรับแต่ละ release ไม่มี password อยู่ใน template/startupmetadata/image/repository
- Public TLS จบที่ externalLB ส่วน Web→API baseline เป็น HTTP ใน private VPC พร้อม firewall/Appauth **ไม่ใช่ end-to-end mTLS** ต้องระบุ trade-off นี้ชัดเจน SQL connector ใช้ TLS แยกต่างหาก

เลือก Terraform สร้างระบบซ้ำได้ และใช้ Console/CLI สำรวจ ตรวจ health/metrics ทำ rollout/failover และวิเคราะห์เหตุ แทนการสร้าง manual ชุดหนึ่งแล้วให้ Terraform สร้างชื่อซ้ำทับ หากต้องนำของที่สร้าง manual เข้า state ต้องมีขั้น import/reconcile เฉพาะ ไม่ให้ผู้เรียนเดาเอง

## Data และ App contract

products มี SKU/ชื่อ/stock ตั้งต้น; orders มี UUID/owner/status/idempotency key/request fingerprint; order_items มี quantity และ snapshot ราคาหน่วยเป็นจำนวนเต็ม; stock_events มี order/SKU/effect/event และ unique business constraints

Create order ต้องล็อกสินค้าในลำดับแน่นอนและทำ stock/order/event ใน transaction เดียว; การ cancel คืนเฉพาะ order ที่ confirmed ครั้งแรก ไม่ลบ ledger สอง API เครื่องต้องพิสูจน์จาก DB เดียวกัน ไม่ใช้ in-memorycounter แทนผลจริง

API มี /livez สำหรับ process และ /healthz ตรวจ schema/DB แยกบทบาทจากกัน LB/autohealing ที่ใช้ processhealth ต้องไม่ recreate ทุก VM เพียงเพราะ SQL failover ชั่วคราว จะยืนยัน startup grace/readiness/health thresholds ใน Design ก่อนเขียน Task

App user ใช้ hashed demo passwords, secure session/CSRF/ownership/role มีข้อจำกัด production ระบุชัด ชุดทดสอบต้องไม่พิมพ์ cookie/secret และอ่านรหัสจาก privatefile ไม่รับ plaintextpassword ใน command line

## Operation scenarios ที่ต้องเตรียม

1. Normal journey + unauthorized/cross-owner/role/network checks
2. Concurrent orders บน API สอง process, duplicate delivery/key conflict, cancel replay และ reconciliation
3. Stop หนึ่ง API process แบบควบคุม ตรวจ healthybackend ที่เหลือ/MIG recovery ไม่ขยาย fault เป็นลบทั้งกลุ่ม
4. Compatible rolling release และ bad-template rollout พร้อม backout/evidence
5. Planned Cloud SQL HA failover ระหว่าง bounded writes/readiness checks จด operation ID, errors, reconnect time และ data integrity ไม่สัญญาว่าไม่มี connectionreset
6. Change API2→4 พร้อม surge/headroom calculation และ retest
7. Cleanup จาก inventory ของ Lab นี้และ rebuild จาก source/infra version เดิม โดยไม่พึ่ง resource จาก Lab ก่อน

## Connection และ resource assumptions ก่อนทำ Guide

ค่าตั้งต้นที่จะตรวจอีกครั้ง: App หนึ่ง worker/VM, pool4/max_overflow0, Web2VM/API2VM, APIchange4VM, regional rollout เผื่อ surge สำหรับสอง zone ต้องคำนวณ instance สูงสุดช่วง rollout ก่อนเลือก SQL max_connections และขนาดเครื่อง ไม่ใช้จำนวน replicas steady state เป็น connection hard cap

ต้องมี Sandbox ที่เปิด Billing, compute/SQL/NAT/LB quotas, สิทธิ์ IAM/OSLogin/IAP/DNS ที่จำเป็น และ domain/subdomain ของผู้เรียนเอง หากไม่มี domain/สิทธิ์ DNS จะยังไม่ผ่าน R1 แบบ HTTPS ห้ามเปลี่ยนเป็น publicHTTP แล้วอ้างว่าครบ baseline

SQL HA, VMs หลายเครื่อง, NAT, LB, disks/backups/logs และ IP มีค่าใช้จ่ายระหว่างฝึก ต้องประมาณงบและเวลาปิดก่อน provision Budget เป็น alert ไม่ใช่ hard cap การจัดทำเอกสารนี้ยังไม่สร้าง GCPresource หรือเปลี่ยน DNS จริง

## แหล่งอ้างอิงที่ใช้ปิดขอบเขต

- [Cloud SQL PostgreSQL high availability](https://docs.cloud.google.com/sql/docs/postgres/high-availability)
- [Internal passthrough Network Load Balancer](https://docs.cloud.google.com/load-balancing/docs/internal)
- [Managed instance group rolling updates](https://docs.cloud.google.com/compute/docs/instance-groups/rolling-out-updates-to-managed-instance-groups)
- [External Application Load Balancer](https://docs.cloud.google.com/load-balancing/docs/https)

ขั้นถัดไป: ยืนยัน ports/source identities/routes/health policy, tier placement, SQL sizing/connection budget และ data invariants → working App/installer/tests/IaC → Diagram → Tasks พาทำ → Review/Guide-ready ยังไม่ถือว่า Brief นี้เป็น Lab ที่ทำเสร็จ
