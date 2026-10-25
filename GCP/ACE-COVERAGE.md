# Google Cloud Associate Cloud Engineer — Exam Coverage Matrix

**ตรวจตาม Google Cloud ACE Exam Guide v4.0** (ตรวจเอกสารทางการวันที่ 2026-10-25)  
Official guide: https://services.google.com/fh/files/misc/v4.0_associate_cloud_engineer_exam_guide_english.pdf  
Certification page: https://cloud.google.com/learn/certification/cloud-engineer

> การมี Lab ที่เกี่ยวข้อง **ไม่เท่ากับผ่านทุก Exam Objective**. Lab ทั้งหมดเป็น Guide-ready และ Cloud verification ยัง Not run. ต้องฝึกจากบัญชี GCP จริงและเช็ก Exam Guide อีกครั้งก่อนสอบ

| ACE v4.0 domain | น้ำหนักที่ระบุในคู่มือ | Lab ที่ช่วยฝึก | ประเด็นควรศึกษา/ทำเพิ่ม |
|---|---:|---|---|
| 1 — Setting up a cloud solution environment | ~23% | 01, 02, 05, 14, 18, 20 | Organization/resource hierarchy, org policies, Cloud Identity, Billing exports, quotas, Cloud Asset Inventory, Gemini Cloud Assist; บางอย่างต้องใช้ Org ที่มีสิทธิ์ |
| 2 — Planning and implementing a cloud solution | ~30% | 01–16, 18, 20 | Spot VM/Hyperdisk, Cloud NGFW secure tags, Network Service Tiers, Interconnect, BigQuery, Storage Transfer, specialized data products และ service-selection tradeoffs |
| 3 — Ensuring successful operation of a cloud solution | ~27% | 01, 02, 04, 05, 07, 10–12, 16, 17, 19, 20 | Ops Agent, Database Center, GKE node pool changes, Cloud Run traffic splitting, Cloud DNS/NAT operations, logging export, personalized service health, Active Assist |
| 4 — Configuring access and security | ~20% | 02, 04, 07, 11, 14, 15, 18–20 | IAM custom roles, service account impersonation, short-lived credentials และ policy administration อย่างเป็นระบบ |

## วิธีใช้กับ Portfolio-Lab

- ใช้ **Lab 01–05** ปูพื้น Compute Engine, VPC, IAM, LB, Cloud SQL แล้วอธิบายเหตุผลเลือกบริการ
- ใช้ **Lab 06–10** ทำความเข้าใจ Cloud Run, Pub/Sub, storage, async workflows, cache และ data flow
- ใช้ **Lab 11–15** เจาะ GKE, CI/CD และ Network/IAM design ระดับสูงกว่า ACE บางหัวข้อ
- ใช้ **Lab 16–20** ฝึก operation, migration, DR, monitoring, incident, security และ handover
- นำ **หัวข้อที่ไม่มีเจ้าภาพชัดเจน** ไปสร้าง Learning Notes/Focused exercises เพิ่มเป็นรายการฝึกขนาดเล็ก โดยไม่ต้องขยาย 20 Lab เป็น 30 Lab

## ตรวจความถูกต้องของเนื้อหา

- **Service/API/IAM**: อ้างเอกสารผลิตภัณฑ์อย่างเป็นทางการ, กำหนด version/region/edition ตรงกับสิ่งที่จะ deploy
- **Commands**: ตรวจ Working Directory, Project/Region, Environment, Variables และ Terraform workspace ก่อนทุกขั้นตอนที่สร้างหรือทำลาย resource
- **Claims**: แยก Code/CI/static tests, expected outputs และผล execution บน GCP จริง
- **Diagram**: แยก global vs regional resources, VPC-contained components vs managed services และ trust boundaries อย่างถูกต้อง

โปรดใช้คู่มือ ACE v4.0 ฉบับปัจจุบันเป็นตัวตัดสิน scope ไม่ใช้ Roadmap/CI เป็นตัวแทนประกาศว่า 'ACE 100% covered'
