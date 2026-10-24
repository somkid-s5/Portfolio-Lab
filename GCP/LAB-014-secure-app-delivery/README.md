---
lab: LAB-014
platform: GCP
phase: brief
guide_status: brief
cloud_verification: not-run
last_verified: null
---

# Lab 14 — แพลตฟอร์มส่งมอบ App สำหรับทีมพัฒนา

> **สถานะเอกสาร:** Brief — กำหนดโจทย์ ขอบเขต สถาปัตยกรรมตั้งต้น และเกณฑ์พิสูจน์แล้ว; ยังไม่ได้เขียน Task Guide หรือไฟล์ deploy
> **สถานะ Cloud:** Not run — เป็นแผนและแบบฝึกหัด ยังไม่มีการสร้างทรัพยากรหรือผลทดสอบ GCP จริง

## สถานการณ์

ทีมพัฒนามีบริการคำนวณค่าจัดส่ง และต้องการปล่อยการเปลี่ยนแปลงจาก GitHub ไปยัง staging และ production อย่างมีหลักฐาน ตรวจสอบย้อนหลังได้ และกู้กลับได้ ทีมไม่ต้องการเก็บ Service Account key ใน GitHub และไม่ต้องการให้ทุก workflow deploy เข้า production ได้โดยตรง

ให้วาง delivery path ที่แยกหน้าที่ระหว่างการทดสอบ การสร้าง artifact การรับรอง artifact และการ deploy ใช้ image แบบ immutable digest, ป้องกัน Cloud Run รับ image ที่ไม่มี attestation, ตรวจ staging ก่อน production, กำหนดผู้อนุมัติ production และใช้ canary พร้อม verification ก่อนเลื่อน traffic เต็มระบบ

## ขอบเขตบริการตัวอย่าง

App เป็น Shipping Quote API แบบ stateless ใช้ข้อมูลจำลองและไม่เก็บข้อมูลลูกค้าจริง มี endpoint สำหรับ health, version และคำนวณ quote พร้อม structured logs ที่เชื่อม request กับ image digest/commit ได้ เนื้อหา App ทำหน้าที่ให้ทีมมี business path ที่ทดสอบจาก CI, staging และ production ไม่ใช่หัวข้อหลักที่ต้องใช้เวลาเขียน App ใหม่

## Requirements และเกณฑ์ยอมรับ

| ID | Requirement | หลักฐานที่ต้องบันทึก |
|---|---|---|
| R1 | Pull request รัน unit/contract tests โดยไม่ออก GCP credential; workflow ที่ publish ได้จำกัดเฉพาะ repository และ branch ที่เชื่อถือผ่าน GitHub OIDC + Workload Identity Federation | run URL, branch/ref, test summary และผลทดลอง workflow จาก branch ที่ไม่อยู่ใน trust condition |
| R2 | ไม่มี long-lived service-account key ใน GitHub Secrets; token เป็น short-lived และ IAM ให้สิทธิ์ตามหน้าที่ | GitHub workflow permissions, WIF provider condition, IAM matrix และ secret scan |
| R3 | สร้าง container image หนึ่งครั้ง, push ไป Artifact Registry และ deploy ด้วย digest เดียวกันทุก environment; ไม่ใช้ mutable tag เป็นตัวตัดสินปล่อย | build ID, repository path, image digest และ digest ใน Cloud Deploy release |
| R4 | Build ทำ tests ที่กำหนดและสร้างหลักฐาน provenance; image ที่ไม่มี attestation จาก attestor ที่เชื่อถือถูก Binary Authorization ปฏิเสธก่อนสร้าง Cloud Run revision | build result/provenance, attestation ของ digest ที่อนุมัติ และ error/audit event จากการ deploy digest ที่ไม่มี attestation |
| R5 | Staging deploy และ verification ผ่านก่อนจึงขอเลื่อน release; verifier ตรวจทั้ง health และ business quote path | rollout state, verification result, HTTP status และ response ที่ sanitize แล้ว |
| R6 | Production rollout ต้องมี approval จาก identity ที่แยกจาก release caller; GitHub publisher ไม่มีสิทธิ์ approve หรือ deploy Cloud Run โดยตรง | principal ผู้สร้าง release, principal ผู้อนุมัติ และ IAM deny/permission checks |
| R7 | Production ใช้ Cloud Deploy canary ตามลำดับ 10% → 50% → 100%; แต่ละ canary phase รัน verification และหยุดเมื่อผลไม่ผ่าน | rollout phases, traffic split, verify job logs และ revision/traffic ก่อน–หลัง |
| R8 | จำลอง application regression ที่ health ยังตอบได้แต่ business path ผิด; canary verification ต้อง fail และ traffic ต้องไม่เลื่อนไป 100% | release/rollout ที่ fail, business probe output และ traffic split ที่คงเหลือ |
| R9 | Recovery ทำได้ด้วย Cloud Deploy rollback ไป revision/release ที่รู้ว่าดี แล้วพิสูจน์ health, business path และ traffic กลับสภาพปกติ | rollback rollout, stable revision, traffic state, probe output และ audit logs |
| R10 | Change Request เพิ่ม approval/exception record ที่ระบุ owner, เหตุผล, ขอบเขต และวันหมดอายุ; งานตรวจต้องปฏิเสธ exception ที่หมดอายุหรือไม่มี owner | record ก่อน–หลัง, CI/policy result และการอนุมัติ/หมดอายุ |
| R11 | Cleanup inventory ระบุ Cloud Run revisions/services, Cloud Deploy resources, Artifact Registry images, KMS key/attestor, IAM bindings และ build artifacts; ลบเฉพาะ resource ของ Lab | inventory ก่อนลบ, command/result และตรวจซ้ำหลัง cleanup |

ตัวเลข canary เป็น progression ของแบบฝึกหัด ไม่ใช่คำแนะนำสัดส่วนที่เหมาะกับ production ทุกระบบ; จะบันทึกเหตุผลและผลจริงใน environment ของผู้เรียน

## สถาปัตยกรรมตั้งต้น

เส้นทางที่ต้องพิสูจน์:

1. **Pull request:** GitHub Actions checkout → unit/contract tests, lint และตรวจ manifest โดยไม่มี GCP token
2. **Trusted release:** เมื่อ merge เข้า branch ที่อนุญาต GitHub Actions ขอ OIDC token; WIF ตรวจ immutable repository ID และ branch/ref ก่อนให้ short-lived credentials
3. **Build:** workflow สั่ง Cloud Build สร้าง/test image แล้ว push image digest ไป Artifact Registry; build identity ไม่มีสิทธิ์ deploy Cloud Run หรืออนุมัติ production
4. **Attest:** trusted build result ผูกกับ digest; signer ใช้ Cloud KMS key ลงนาม Binary Authorization attestation หลังเงื่อนไข build ผ่าน โดยแยกสิทธิ์จาก runtime และ production approver
5. **Staging:** Cloud Deploy สร้าง release จาก digest เดิมและ deploy ไป Cloud Run staging; verify job ตรวจ health และ quote contract
6. **Production gate:** promotion สร้าง production rollout ที่ต้อง approval; approver ตรวจ staging evidence, digest, change record และ rollout details ก่อนอนุมัติ
7. **Canary:** Cloud Deploy ส่ง traffic ไป revision ใหม่เป็นช่วง 10%, 50%, แล้วจึง 100%; verify job ทำ bounded HTTPS probes ทุก phase
8. **Recovery:** หาก verify ล้มเหลว rollout ไม่เดินต่อ; ใช้ rollback ไป stable release และตรวจ traffic/revision อีกครั้ง
9. **Audit:** Cloud Build, Cloud Deploy, Binary Authorization และ Cloud Run events ถูกเชื่อมกับ release ID, digest, commit และผู้ปฏิบัติ

ใช้หนึ่ง disposable project และหนึ่ง region ใน baseline เพื่อลด prerequisite โดยแยก Cloud Run service/target เป็น staging และ production; เป็น learning simplification ไม่ใช่ข้อสรุปว่า production จริงควรรวม project. การแยก project, signer และ attestation project เพิ่มเติมเป็น extension หลัง baseline ใช้งานได้

## Identity boundary ที่ต้องรักษา

| Principal | หน้าที่ตั้งต้น | สิ่งที่ไม่มีสิทธิ์ |
|---|---|---|
| GitHub PR workflow | รันทดสอบ source | ไม่มี OIDC permission และไม่มี GCP access |
| WIF release caller | สั่ง build/release ตาม workflow ที่เชื่อถือ | ไม่มี Cloud Run Admin, ไม่มี KMS signing และไม่มี production approval |
| Cloud Build builder | ทดสอบ/build/push เฉพาะ Artifact Registry repository | ไม่มี production approval และไม่แก้ IAM |
| Attestation signer | ลงนาม attestation ของ digest หลัง build gate | ไม่มี Cloud Run deploy/approve |
| Cloud Deploy execution identity | deploy และ run verification ตาม targets | ไม่แก้ policy หรือ IAM |
| Production approver | approve/deny production rollout | ไม่ build, sign image หรือเปลี่ยน artifact |
| Cloud Run runtime identity | ทำงานของ Quote API | ไม่มีสิทธิ์ build, sign หรือแก้ delivery pipeline |

บทบาทและ scope ของ IAM เป็นแบบร่างเพื่อเริ่ม Design; ตอนทำคู่มือจะเทียบ permission กับเอกสารทางการและลดขอบเขตให้แคบที่สุดก่อนเขียนคำสั่งจริง

## Fault และ Change Request

- **Untrusted identity:** ทดลอง workflow จาก branch/ref ที่ไม่ตรง WIF condition; คาดว่า token exchange ถูกปฏิเสธ และไม่มี Cloud Build/Cloud Deploy resource เกิดขึ้น
- **Unapproved image:** ชี้ release ไปยัง digest ที่ไม่มี attestation; Binary Authorization ต้องปฏิเสธการสร้าง revision ขณะที่ revision เดิมยังรับ traffic
- **Canary regression:** ใช้ build ที่ผ่าน unit tests แต่มี regression ที่ quote route; health ยังผ่านแต่ Cloud Deploy business verification ต้องล้มเหลวใน canary phase และไม่เลื่อนเป็น stable 100%
- **Rollback:** deploy release ล่าสุดที่รู้ว่าดีตามกลไก Cloud Deploy แล้วตรวจ traffic, revision และ quote response ซ้ำ; ห้ามเรียกการแก้กลับว่าเสร็จจากการกด rollback อย่างเดียว
- **Change Request:** เพิ่ม exception record ที่มี owner, reason, scope, approved_by และ expires_at; exception ไม่เปลี่ยน Binary Authorization policy เอง และ expired record ต้องถูก CI/policy test ปฏิเสธ
- **First release caveat:** Cloud Deploy canary ไม่มี revision เก่าที่จะ split traffic ใน deployment แรก จึงอาจข้าม canary phases; ต้อง deploy baseline ให้สำเร็จก่อนแล้วจึงทดสอบ canary รอบถัดไป

## สมมติฐาน ค่าใช้จ่าย และความเสี่ยง

- ผู้เรียนมี Google Cloud project ที่เปิด Billing และสิทธิ์เปิด APIs, สร้าง IAM/WIF/KMS/Binary Authorization/Cloud Build/Artifact Registry/Cloud Deploy/Cloud Run resources ได้; ขั้นตอน Organization Policy เป็น extension ไม่ใช่ prerequisite บังคับ
- ต้องตั้ง GitHub Actions environment/repository variables ตามคู่มือ; ห้าม commit key, token, state, build credential หรือผลลัพธ์ที่มี secret
- Cloud Build, Cloud Run, Artifact Registry storage, Cloud Logging, Cloud KMS key และ Binary Authorization อาจคิดค่าใช้จ่าย; ก่อน run จริงต้องตรวจ pricing, quota และ region จากหน้า official ปัจจุบัน พร้อมจำกัด request/concurrency, min instances เป็นศูนย์ และเวลาทดลอง
- ไม่ทำ production traffic จริง, ไม่สร้าง external customer data และไม่ใช้ load test ที่ยิงไม่จำกัด
- สถานะ Lab นี้ยังไม่ใช่คู่มือพร้อมรัน; ยังไม่สร้าง resource และไม่มีผลราคา/เวลา/ประสิทธิภาพจาก Cloud
- Cloud Run Binary Authorization ใช้ default policy สำหรับ Cloud Run; Cloud Run ไม่รองรับ service-specific rule แบบ GKE ตามเอกสาร policy ปัจจุบัน จึงต้องอธิบายผลของ policy scope ชัดเจน
- เอกสาร Cloud Run ระบุ built-by-cloud-build attestor เป็น Preview; baseline นี้จะพิจารณา custom attestor + Cloud KMS แทน และจะตรวจข้อกำหนด/สถานะบริการอีกครั้งก่อนเขียนคำสั่ง deploy

## หลักฐานสำหรับ Case Study

เมื่อทำ Guide เสร็จ แต่ละ Task จะมีช่อง Actual/Evidence ติดกับจุดตรวจ ให้บันทึกอย่างน้อย:

- release ID, commit SHA, image digest, build ID และ attestation/attestor
- WIF subject/claims ที่ sanitize แล้ว, identity ที่ใช้งาน, และผล negative authorization
- staging/production rollout IDs, approval principal, canary percentages และ verification output
- regression ที่ใช้, จุดที่ rollout หยุด, rollback ID และ traffic/revision หลัง recovery
- exception owner/reason/scope/expiry พร้อม policy-test result
- เวลาเริ่ม–จบเฉพาะที่วัดจริง, ค่าใช้จ่ายจาก Billing ที่มีช่วงเวลา/ขอบเขตชัด และ cleanup inventory
- สิ่งที่ไม่สำเร็จ, สิ่งที่ยังไม่ได้ตรวจ และสิ่งที่ต้องปรับก่อนใช้กับ production จริง

ไม่กรอก Expected ลงช่อง Actual และไม่ใช้ผล CI แทนผล Cloud

## แหล่งอ้างอิงทางการสำหรับช่วง Design

- [Workload Identity Federation สำหรับ deployment pipelines](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-deployment-pipelines) — GitHub OIDC claims, attribute mapping/condition และการแลก short-lived credentials
- [Cloud Deploy targets สำหรับ Cloud Run](https://docs.cloud.google.com/deploy/docs/run-targets) — target, Skaffold, Cloud Run service และข้อจำกัดของ canary สำหรับ jobs
- [Cloud Deploy pipeline และ targets](https://docs.cloud.google.com/deploy/docs/create-pipeline-targets) — requireApproval และการจัด target
- [Cloud Deploy canary สำหรับ Cloud Run](https://docs.cloud.google.com/deploy/docs/deployment-strategies/canary/cloud-run) — traffic progression และ verify ต่อ phase
- [Cloud Deploy deployment verification](https://docs.cloud.google.com/deploy/docs/verify-deployment) — verify task exit code และ rollout failure
- [จัดการ Cloud Deploy rollouts](https://docs.cloud.google.com/deploy/docs/deployment-strategies/manage-rollout) — phases และการข้าม canary ใน first deployment
- [Binary Authorization สำหรับ Cloud Run](https://docs.cloud.google.com/binary-authorization/docs/run/overview) — policy enforcement และข้อจำกัดของ rule
- [สร้าง Binary Authorization attestation ด้วย Cloud KMS](https://docs.cloud.google.com/binary-authorization/docs/making-attestations) — signing และ attestor
- [Artifact Registry IAM](https://docs.cloud.google.com/artifact-registry/docs/access-control) — role scope ของ repository

## ขั้นถัดไป

Design จะล็อก request/data/identity flow, pipeline config, IAM bindings, attestation trust boundary, canary verification/rollback และ Diagram ก่อนเริ่มเขียน Task Guide จากนั้นจึงสร้าง App/infra/test materials และเขียน README ไฟล์นี้ต่อให้เป็นคู่มือครบหนึ่ง Lab ไม่มีการสร้าง GCP resources ในขั้นจัดทำเอกสาร
