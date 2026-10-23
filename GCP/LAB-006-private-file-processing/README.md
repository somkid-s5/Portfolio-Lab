---
lab: LAB-006
platform: GCP
guide_status: brief
cloud_verification: not-run
last_verified: null
---
# Lab 06 — รับไฟล์ยอดขายและสร้างรายงานส่วนตัวแบบ Event-driven

## สถานการณ์

ทีมปฏิบัติการรับ CSV ยอดขายจากหลายคน ผู้ส่งต้องเห็นเฉพาะไฟล์ของตน รู้ว่าไฟล์กำลังรอ ประมวลผลสำเร็จ หรือถูกปฏิเสธ และดาวน์โหลดรายงานได้โดยไม่เปิด bucket สาธารณะ หาก worker ล้มหลังเขียนผลแล้ว การส่ง event ซ้ำต้องไม่สร้างรายงานธุรกิจซ้ำหรือเปลี่ยนเจ้าของงาน

ผู้เรียนจะสร้าง Upload portal และระบบประมวลผลจริง ไม่ใช่เพียงสร้าง bucket กับ trigger ตัวอย่างนี้ใช้ข้อมูลสังเคราะห์ ไม่มีบัตรชำระเงินหรือข้อมูลลูกค้าจริง

**สถานะ:** กำหนดโจทย์และ acceptance ก่อนลง Design/Materials ยังไม่ใช่คู่มือพร้อมรัน ไม่มีผลทดสอบ GCP จริง

## ผู้ใช้และผลลัพธ์

- alice / bob: login, ขอสิทธิ์ upload, ส่ง CSV, ดูประวัติ/สถานะของตน และขอ download link ของผลสำเร็จ
- operator: ดูงานค้าง/failed พร้อมเหตุผลที่ไม่เปิดข้อมูลไฟล์ และขอ retry เฉพาะงานที่เข้าเงื่อนไข
- worker: อ่านไฟล์ต้นฉบับ generation ที่ถูกตรึง ตรวจข้อมูล และสร้าง summary JSON ไม่มี public endpoint สำหรับเรียกโดย anonymous

CSV baseline: คอลัมน์ sale_id,sku,quantity,unit_price_satang; จำกัด UTF-8, header ตรง, sale_id ไม่ซ้ำในไฟล์, quantity เป็นจำนวนเต็มบวก, ราคาเป็นจำนวนเต็มสตางค์ ไม่ใช้ float รายงานมีจำนวนรายการ จำนวนหน่วย ยอดรวม และยอดแยก SKU พร้อม input SHA256 และ processor version ไม่สะท้อน arbitrary HTML จากไฟล์

## Requirements และหลักฐาน

| ID | ข้อกำหนด | วิธีพิสูจน์ |
|---|---|---|
| R1 | ส่งไฟล์และรับรายงานครบวงจร | Browser login → upload → pending/processing → succeeded → download; เทียบผลกับ expected fixture ที่คำนวณไว้ |
| R2 | แยก owner และ runtime identity | bob อ่านสถานะหรือขอ link ของ alice ได้404; anonymous401; worker ปฏิเสธ anonymous; bucketไม่มี allUsers/allAuthenticatedUsers |
| R3 | จำกัด upload ทั้งทางเข้าและการอ่านจริง | baseline1MiB/10,000rows; ทดสอบ oversized, MIMEปลอม, invalidUTF-8, headerผิด, duplicate sale_id และตัวเลขผิด; rejectedไม่มี published output |
| R4 | รับ event ซ้ำ/ต่างลำดับอย่างถูกต้อง | replay CloudEvent เดิมและ eventIDต่างกันแต่ bucket/name/generationเดิม; มี logical result เดียว, ownerเดิม และ immutable input binding |
| R5 | กู้จาก failure ระหว่าง storage กับ metadata | ฉีด fault หลัง output create ก่อน success commit; retry ตรวจ output เดิมและทำงานจบโดยไม่เขียนผลซ้ำ; leaseหมดอายุถูก reclaim อย่างมี fencing |
| R6 | สิทธิ์เข้าถึงมีอายุและ retention ตรวจได้ | upload permissionหมดอายุใช้งานไม่ได้; download linkเป็น bearer capabilityที่มีTTLสั้น; Appไม่ออกlinkหลังหมดอายุงาน; บันทึก lifecycle/softdelete/metadata expiry ตามจริง |
| R7 | Change request เพิ่มขนาดไฟล์อย่างมีเพดาน | baseline1MiB→5MiB พร้อมเพิ่ม row/timeout/memory budgetที่มีเหตุผล; ทดสอบก่อน–หลัง/negative cases/คืนbaseline ไม่เพียงแก้ UI |
| R8 | ดูแลและปิดระบบได้ | request/job/event correlation, stuck-job inspection, bounded retry/backout, evidence/case study, cleanupทั้งobjects/generations/metadata/trigger/services/identities และrebuild |

## Candidate architecture และขอบเขต

เลือก Cloud Run portal/API + Cloud Run worker แยก service accounts, Cloud Storage incoming/results แยก private buckets, Eventarc Standard object-finalized trigger เฉพาะ incoming และ Firestore Native สำหรับ job state/claim ledger

วางบริการ/Storage/Firestore location ให้เข้ากันใน asia-southeast1 โดยตรวจข้อกำหนด Eventarc และ Firestore database location ก่อนสร้างจริง ไม่ใช้ทรัพยากรที่ยังเปิดค้างจาก Lab ก่อน

Portal ใช้ HTTPS ของ Cloud Run และ App session/CSRF/owner checks; การเปิด portal ให้เข้า login ได้ไม่แปลว่า worker หรือ buckets เปิดสาธารณะ ผู้ใช้ไม่รับ Google Cloud credentials และ Browser ไม่เข้าถึง Firestore โดยตรง Server SDK ใช้ IAM จึงต้องตรวจ App ownership เอง ไม่อ้าง Firestore Security Rules มาคุม server SDK แทน

ทาง upload จะลงรายละเอียดการใช้ V4 signed POST policy ที่ตรึง bucket/key/Content-Type/expiry และ content-length-range ก่อนเขียน code เหตุผลคือโจทย์ต้องจำกัดขนาดตั้งแต่ทางเข้า ไม่ใช้คำอธิบายว่า signed URL ธรรมดาบังคับขนาด/ตรวจเนื้อหาได้เอง Worker ต้องตรวจ bytes/rows/schema ซ้ำเสมอ CORS ไม่ใช่ authentication และ MIME/filename จาก client ไม่ใช่หลักฐานชนิดไฟล์

ทาง download ใช้ V4 signed GET อายุสั้นเฉพาะ output object generation ที่ jobสำเร็จและ ownerผ่านแล้ว ไม่ใส่ signed URL/query/session/cookie ใน logs หรือหลักฐาน ลิงก์ที่ออกไปแล้วเป็น bearer capability: คนที่ได้ลิงก์อาจอ่านได้จนหมดอายุ จึงไม่อ้างว่า owner login ถูกตรวจทุกครั้งที่ Storage รับ download

ไม่ใช้ service-account private key file ใน repo หรือ runtime ใช้ IAM Credentials signBlob แบบ keyless โดยแยก upload signer/download signer และกำหนดสิทธิ์เฉพาะ resource ที่ต้องใช้ รายละเอียด IAM/custom role จะยืนยันใน Design

## ข้อตกลงข้อมูลและความถูกต้องที่ต้องปิดใน Design

1. สร้าง job UUID/owner/object key/limits ก่อนออก upload permission; object key กำหนดโดย server ไม่รับ pathจาก client
2. incoming ต้องป้องกัน overwrite โดย uploader identity มี create ไม่ใช่ update/delete; bindingเลือก generationหนึ่งครั้งใน transaction และไม่เปลี่ยนตาม eventที่มาทีหลัง
3. ระบุตัวตนงานจาก bucket/name/generation ไม่ใช้ eventIDอย่างเดียว ตรวจ bucketและjob bindingก่อนอ่านไฟล์
4. Firestore transaction callback ไม่มี network I/O หรือเขียน Storage เพราะ callbackอาจถูก retry
5. claim ใช้ attempt token/fencing + lease expiry; publish success เฉพาะ tokenปัจจุบัน ไม่ให้ workerเก่าทับสถานะหลังถูก reclaim
6. output ชื่อ deterministic จาก job/generation/processor-version, create-only precondition และ verify bytes/hash เมื่อพบของเดิม; StorageกับFirestoreไม่ใช่ transactionเดียวกัน ต้องมี recoveryสำหรับช่องว่างนี้
7. validation failureเป็น terminal rejectedพร้อมreason codeที่ปลอดภัยและack; transient failureคืน retryable response ไม่ackเป็นsuccess; stale/unknown eventsต้องมีpolicyไม่เขียนข้อมูลผิดowner
8. result expiryตรวจใน App ก่อนออกlink; FirestoreTTL/Storagelifecycleเป็น cleanupภายหลัง ไม่ใช่ตัวปฏิเสธaccessทันทีและไม่รับประกันลบตรงวินาที
9. initial limits/processor versionถูกบันทึกใน job; change requestไม่เปลี่ยน contractของงานเก่ากลางทาง
10. operator retryต้อง authenticated/authorized, จำกัดจำนวนและอายุ, เก็บattempt history และกลับไปอ่าน generationเดิม ไม่สร้าง jobใหม่เงียบ ๆ

## Failure และ change scenarios

- ส่ง eventซ้ำพร้อมกันสอง worker และส่ง eventของ generationอื่นหลัง jobถูกbindแล้ว
- ข้อมูลเสียเป็น rejectedโดยไม่วน retryไม่จบ; งานค้างเพราะ transient faultสามารถ inspectและretryได้
- worker crashหลัง outputเขียนสำเร็จ แต่ก่อนmetadata success ต้อง convergeเป็นresultเดียว
- workerที่leaseหมดอายุพยายามcommitหลังattemptใหม่ ต้องถูกfence
- ถอดสิทธิ์เฉพาะ sandbox test identity/ใช้ fault revision เพื่อทดสอบ access failure ไม่แก้ IAMกว้างทั้งproject
- ขยาย1→5MiB และวัดเวลา/memory/error/ผลรวมถูกต้อง พร้อมกลับค่าเดิม; ใช้synthetic fixturesไม่ใช่ไฟล์จริงของทีม

## สิ่งที่จะส่งมอบก่อน Guide-ready

READMEนี้จะรวม Diagram, Tasksแบบพาทำ, Expected/Actualข้างงาน, runbook, case study และcleanup โค้ดแยกเฉพาะportal/worker/domain/storage-metadata adapters/infra/tests/fixtures/toolsที่จำเป็น ต้องมีsample CSV valid/invalid/boundaryและexpected summaries, health endpoints, structured logs, UIจริง, bounded journey/event-replay/fault tools และ testsกับFirestore emulatorบนcloud CI รวมกรณีrace/lease/recovery ไม่ใช้ in-memorymockอย่างเดียวพิสูจน์ transactionของFirestore

Diagramจะทำหลังยืนยันscope/identity/eventflow; ไม่ใช้ภาพแทนการตัดสินใจทางเทคนิค ชุดนี้ยังไม่มีAppหรือDiagramสำเร็จ จึงไม่เรียกGuide-ready

## เตรียมสิทธิ์ ต้นทุน และ Cleanup

ใช้ sandbox projectที่เปิด Billing และมีสิทธิ์สร้าง Cloud Run/Eventarc/Storage/Firestore/Artifact Registry/Secret Manager/IAM Credentials และกำหนด IAM bindings ต้องตรวจว่ามี Firestore databaseเดิมหรือไม่ ไม่เปลี่ยน location/type ของระบบอื่นเพื่อทำLab

กำหนด max instances/concurrency/timeouts/ขนาดไฟล์/จำนวนงาน/retentionก่อนทดสอบ Budget alertไม่ใช่hard cap Storage operations, Eventarc/PubSub transport, Firestore reads/writes, Cloud Run/build/image/logs และsoftdeletedobjectsอาจคิดค่าใช้จ่าย ไม่มีการprovisionในงานเขียนเอกสารนี้

Cleanupต้องหยุดรับงาน/triggerก่อนลบworker, resolve/บันทึกงานค้าง, ตรวจobjectsทุกgeneration/softdelete, metadataและTTL, triggertransportที่ระบบสร้าง, service accounts/IAM/secrets/imagesและservices โดยแยกของLabจากFirestoreหรือprojectที่แชร์ ไม่ลบdefaultdatabaseทั้งก้อนถ้ามีข้อมูลอื่น

## แหล่งอ้างอิงที่ใช้ตั้งโจทย์

ตรวจวันที่23ตุลาคม2026 รายละเอียด version/IAM/location/SDKจะตรวจอีกครั้งใน Design

- [Eventarc retry และ duplicate delivery](https://docs.cloud.google.com/eventarc/docs/retry-events)
- [Cloud Storage events ไป Cloud Run](https://docs.cloud.google.com/run/docs/triggering/storage-triggers)
- [V4 policy signatures และ conditions](https://docs.cloud.google.com/storage/docs/authentication/signatures)
- [HTML form upload](https://docs.cloud.google.com/storage/docs/xml-api/post-object-forms)
- [Signed URLs และ bearer access](https://docs.cloud.google.com/storage/docs/access-control/signed-urls)
- [Firestore transactions](https://firebase.google.com/docs/firestore/manage-data/transactions)

ขั้นถัดไป: ปิด Designเรื่องlocation/IAM/POST policy/objectgeneration/state machine/fencing/retry/retention และtest matrix ก่อนเริ่มสร้าง Materials
