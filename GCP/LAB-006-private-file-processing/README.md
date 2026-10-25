---
lab: LAB-006
platform: GCP
guide_status: guide-ready
cloud_verification: not-run
last_verified: null
---
# Lab 06 — รับไฟล์ยอดขายและสร้างรายงานส่วนตัวแบบ Event-driven

![สถาปัตยกรรม Sales File Desk: อัปโหลดตรงเข้า Storage และประมวลผลผ่าน Eventarc](assets/diagrams/solution-preview.png)

Browser ขอสิทธิ์จาก Portal แล้วส่ง CSV ตรงเข้า private incoming bucket เมื่อไฟล์ finalized จึงมี event เรียก worker ส่วน Firestore เก็บ owner และสถานะงาน ไม่ส่งไฟล์ผ่าน Portal และไม่ใช้ VPC ใน Solution นี้ เส้นประแยกการ claim/publish สถานะออกจากเส้นทางไฟล์

[SVG แก้ไขได้](assets/diagrams/solution.svg) · [ที่มาไอคอนและผลตรวจภาพ](assets/diagram-provenance.json) ภาพเป็นการออกแบบ ไม่ใช่ผล deploy บน GCP

## สถานการณ์

ทีมปฏิบัติการรับ CSV ยอดขายจากหลายคน ผู้ส่งต้องเห็นเฉพาะไฟล์ของตน รู้ว่าไฟล์กำลังรอ ประมวลผลสำเร็จ หรือถูกปฏิเสธ และดาวน์โหลดรายงานได้โดยไม่เปิด bucket สาธารณะ หาก worker ล้มหลังเขียนผลแล้ว การส่ง event ซ้ำต้องไม่สร้างรายงานธุรกิจซ้ำหรือเปลี่ยนเจ้าของงาน

ผู้เรียนจะสร้าง Upload portal และระบบประมวลผลจริง ไม่ใช่เพียงสร้าง bucket กับ trigger ตัวอย่างนี้ใช้ข้อมูลสังเคราะห์ ไม่มีบัตรชำระเงินหรือข้อมูลลูกค้าจริง

**สถานะ:** Guide-ready — คู่มือและไฟล์ประกอบผ่านการตรวจตามขอบเขตด้านล่าง ผล GCP ยัง Not run ช่อง Actual และหลักฐานเป็นส่วนที่ผู้เรียนเติมจากการลงมือจริง

## ผู้ใช้และผลลัพธ์

- alice / bob: login, ขอสิทธิ์ upload, ส่ง CSV, ดูประวัติ/สถานะของตน และขอ download link ของผลสำเร็จ
- operator: ดูงานค้าง/failed พร้อมเหตุผลที่ไม่เปิดข้อมูลไฟล์ และขอ retry เฉพาะงานที่เข้าเงื่อนไข
- worker: อ่านไฟล์ต้นฉบับ generation ที่ถูกตรึง ตรวจข้อมูล และสร้าง summary JSON ไม่มี public endpoint สำหรับเรียกโดย anonymous

CSV baseline: คอลัมน์ sale_id,sku,quantity,unit_price_satang; จำกัด UTF-8, header ตรง, sale_id ไม่ซ้ำในไฟล์, quantity เป็นจำนวนเต็มบวก, ราคาเป็นจำนวนเต็มสตางค์ ไม่ใช้ float รายงานมีจำนวนรายการ จำนวนหน่วย ยอดรวม และยอดแยก SKU พร้อม input SHA256 และ processor version ไม่สะท้อน arbitrary HTML จากไฟล์

## Requirements และหลักฐาน

| ID | ข้อกำหนด | วิธีพิสูจน์ |
|---|---|---|
| R1 | ส่งไฟล์และรับรายงานครบวงจร | Browser login → upload → pending/processing → succeeded → download; เทียบผลกับ expected fixture ที่คำนวณไว้ |
| R2 | แยก owner และ runtime identity | bob อ่านสถานะหรือขอ link ของ alice ได้ 404; anonymous401; worker ปฏิเสธ anonymous; bucket ไม่มี allUsers/allAuthenticatedUsers |
| R3 | จำกัด upload ทั้งทางเข้าและการอ่านจริง | baseline1MiB/10,000rows; ทดสอบ oversized, MIME ปลอม, invalidUTF-8, header ผิด, duplicate sale_id และตัวเลขผิด; rejected ไม่มี published output |
| R4 | รับ event ซ้ำ/ต่างลำดับอย่างถูกต้อง | replay CloudEvent เดิมและ eventID ต่างกันแต่ bucket/name/generation เดิม; มี logical result เดียว, owner เดิม และ immutable input binding |
| R5 | กู้จาก failure ระหว่าง storage กับ metadata | ฉีด fault หลัง output create ก่อน success commit; retry ตรวจ output เดิมและทำงานจบโดยไม่เขียนผลซ้ำ; lease หมดอายุถูก reclaim อย่างมี fencing |
| R6 | สิทธิ์เข้าถึงมีอายุและ retention ตรวจได้ | upload permission หมดอายุใช้งานไม่ได้; download link เป็น bearer capability ที่มี TTL สั้น; App ไม่ออก link หลังหมดอายุงาน; บันทึก lifecycle/softdelete/metadata expiry ตามจริง |
| R7 | Change request เพิ่มขนาดไฟล์อย่างมีเพดาน | baseline1MiB→5MiB พร้อมเพิ่ม row/timeout/memory budget ที่มีเหตุผล; ทดสอบก่อน–หลัง/negative cases/คืน baseline ไม่เพียงแก้ UI |
| R8 | ดูแลและปิดระบบได้ | request/job/event correlation, stuck-job inspection, bounded retry/backout, evidence/case study, cleanup ทั้ง objects/generations/metadata/trigger/services/identities และ rebuild |

## สถาปัตยกรรมและขอบเขต

เลือก Cloud Run portal/API + Cloud Run worker แยก service accounts, Cloud Storage incoming/results แยก private buckets, Eventarc Standard object-finalized trigger เฉพาะ incoming และ Firestore Native สำหรับ job state/claim ledger

วางบริการ/Storage/Firestore location ให้เข้ากันใน asia-southeast1 โดยตรวจข้อกำหนด Eventarc และ Firestore database location ก่อนสร้างจริง ไม่ใช้ทรัพยากรที่ยังเปิดค้างจาก Lab ก่อน

Portal ใช้ HTTPS ของ Cloud Run และ App session/CSRF/owner checks; การเปิด portal ให้เข้า login ได้ไม่แปลว่า worker หรือ buckets เปิดสาธารณะ ผู้ใช้ไม่รับ Google Cloud credentials และ Browser ไม่เข้าถึง Firestore โดยตรง Server SDK ใช้ IAM จึงต้องตรวจ App ownership เอง ไม่อ้าง Firestore Security Rules มาคุม server SDK แทน

ทาง upload ใช้ V4 signed POST policy ที่ตรึง bucket/key/Content-Type/expiry และ content-length-range เหตุผลคือโจทย์ต้องจำกัดขนาดตั้งแต่ทางเข้า ไม่ใช้คำอธิบายว่า signed URL ธรรมดาบังคับขนาด/ตรวจเนื้อหาได้เอง Worker ต้องตรวจ bytes/rows/schema ซ้ำเสมอ CORS ไม่ใช่ authentication และ MIME/filename จาก client ไม่ใช่หลักฐานชนิดไฟล์

ทาง download ใช้ V4 signed GET อายุสั้นเฉพาะ output object generation ที่ job สำเร็จและ owner ผ่านแล้ว ไม่ใส่ signed URL/query/session/cookie ใน logs หรือหลักฐาน ลิงก์ที่ออกไปแล้วเป็น bearer capability: คนที่ได้ลิงก์อาจอ่านได้จนหมดอายุ จึงไม่อ้างว่า owner login ถูกตรวจทุกครั้งที่ Storage รับ download

ไม่ใช้ service-account private key file ใน repo หรือ runtime ใช้ IAM Credentials signBlob แบบ keyless โดยแยก upload signer/download signer และกำหนดสิทธิ์เฉพาะ resource ที่ต้องใช้ ขอบเขต IAM/custom role อยู่ในตารางสิทธิ์ด้านล่าง

## ข้อตกลงข้อมูลและความถูกต้อง

1. สร้าง job UUID/owner/object key/limits ก่อนออก upload permission; object key กำหนดโดย server ไม่รับ path จาก client
2. incoming ต้องป้องกัน overwrite โดย uploader identity มี create ไม่ใช่ update/delete; binding เลือก generation หนึ่งครั้งใน transaction และไม่เปลี่ยนตาม event ที่มาทีหลัง
3. ระบุตัวตนงานจาก bucket/name/generation ไม่ใช้ eventID อย่างเดียว ตรวจ bucket และ job binding ก่อนอ่านไฟล์
4. Firestore transaction callback ไม่มี network I/O หรือเขียน Storage เพราะ callback อาจถูก retry
5. claim ใช้ attempt token/fencing + lease expiry; publish success เฉพาะ token ปัจจุบัน ไม่ให้ worker เก่าทับสถานะหลังถูก reclaim
6. output ชื่อ deterministic จาก job/generation/processor-version, create-only precondition และ verify bytes/hash เมื่อพบของเดิม; Storage กับ Firestore ไม่ใช่ transaction เดียวกัน ต้องมี recovery สำหรับช่องว่างนี้
7. validation failure เป็น terminal rejected พร้อม reason code ที่ปลอดภัยและ ack; transient failure คืน retryable response ไม่ ack เป็น success; stale/unknown events ต้องมี policy ไม่เขียนข้อมูลผิด owner
8. result expiry ตรวจใน App ก่อนออก link; FirestoreTTL/Storagelifecycle เป็น cleanup ภายหลัง ไม่ใช่ตัวปฏิเสธ access ทันทีและไม่รับประกันลบตรงวินาที
9. initial limits/processor version ถูกบันทึกใน job; change request ไม่เปลี่ยน contract ของงานเก่ากลางทาง
10. operator retry ต้อง authenticated/authorized, จำกัดจำนวนและอายุ, เก็บ attempt history และกลับไปอ่าน generation เดิม ไม่สร้าง job ใหม่เงียบ ๆ

## Failure และ change scenarios

- ส่ง event ซ้ำพร้อมกันสอง worker และส่ง event ของ generation อื่นหลัง job ถูก bind แล้ว
- ข้อมูลเสียเป็น rejected โดยไม่วน retry ไม่จบ; งานค้างเพราะ transient fault สามารถ inspect และ retry ได้
- worker crash หลัง output เขียนสำเร็จ แต่ก่อน metadata success ต้อง converge เป็น result เดียว
- worker ที่ lease หมดอายุพยายาม commit หลัง attempt ใหม่ ต้องถูก fence
- ถอดสิทธิ์เฉพาะ sandbox test identity/ใช้ fault revision เพื่อทดสอบ access failure ไม่แก้ IAM กว้างทั้ง project
- ขยาย 1→5MiB และวัดเวลา/memory/error/ผลรวมถูกต้อง พร้อมกลับค่าเดิม; ใช้ synthetic fixtures ไม่ใช่ไฟล์จริงของทีม

## เตรียมสิทธิ์ ต้นทุน และ Cleanup

ใช้ sandbox project ที่เปิด Billing และมีสิทธิ์สร้าง Cloud Run/Eventarc/Storage/Firestore/Artifact Registry/Secret Manager/IAM Credentials และกำหนด IAM bindings ต้องตรวจว่ามี Firestore database เดิมหรือไม่ ไม่เปลี่ยน location/type ของระบบอื่นเพื่อทำ Lab

กำหนด max instances/concurrency/timeouts/ขนาดไฟล์/จำนวนงาน/retention ก่อนทดสอบ Budget alert ไม่ใช่ hard cap Storage operations, Eventarc/PubSub transport, Firestore reads/writes, Cloud Run/build/image/logs และ softdeletedobjects อาจคิดค่าใช้จ่าย ไม่มีการ provision ในงานเขียนเอกสารนี้

Cleanup ต้องหยุดรับงาน/trigger ก่อนลบ worker, resolve/บันทึกงานค้าง, ตรวจ objects ทุก generation/softdelete, metadata และ TTL, triggertransport ที่ระบบสร้าง, service accounts/IAM/secrets/images และ services โดยแยกของ Lab จาก Firestore หรือ project ที่แชร์ ไม่ลบ defaultdatabase ทั้งก้อนถ้ามีข้อมูลอื่น

## แหล่งอ้างอิงที่ใช้ตั้งโจทย์

ตรวจวันที่ 23 ตุลาคม 2026 รายละเอียด version/IAM/location/SDK จะตรวจอีกครั้งใน Design

- [Eventarc retry และ duplicate delivery](https://docs.cloud.google.com/eventarc/docs/retry-events)
- [Cloud Storage events ไป Cloud Run](https://docs.cloud.google.com/run/docs/triggering/storage-triggers)
- [V4 policy signatures และ conditions](https://docs.cloud.google.com/storage/docs/authentication/signatures)
- [HTML form upload](https://docs.cloud.google.com/storage/docs/xml-api/post-object-forms)
- [Signed URLs และ bearer access](https://docs.cloud.google.com/storage/docs/access-control/signed-urls)
- [Firestore transactions](https://firebase.google.com/docs/firestore/manage-data/transactions)

## การออกแบบระบบ

### Resource map และขอบเขตจริง

| Resource | ขอบเขต / ค่าตั้งต้น |
|---|---|
| Portal/API | Cloud Run service lab006-portal, asia-southeast1; HTTPS URL ของบริการ; min0/max2 instances, concurrency8, timeout30s, memory512MiB |
| Worker | Cloud Run service lab006-worker, asia-southeast1; ต้องผ่าน Cloud Run IAM, min0/max2, concurrency1, timeout60s, memory512MiB |
| Incoming / results | bucket คนละใบ ชื่อ globally unique ที่ผู้เรียนกำหนด, regional ASIA-SOUTHEAST1, uniform access/public-access prevention; ไม่มี static website/public ACL |
| Metadata | Firestore Native Standard named database lab006-files ใน asia-southeast1 ไม่ใช้หรือเปลี่ยน default database; server SDK เลือก database ID ชัดเจน |
| Events | Eventarc Standard trigger lab006-incoming-finalized, asia-southeast1, filter finalized+incoming bucket, destination worker path /events/storage |
| Image / Secret | Artifact Registry repository ของ Lab, image digest ที่บันทึกไว้; auth Secret version เป็นเลข, ไม่มี payload ใน Terraform |
| Signing | แยก service accounts upload-signer และ download-signer; portal ขอ signBlob ไม่ใช้ keyfile |
| Observability | structured stdout/stderr และ Cloud Run metrics; job_id/request_id/event_id ใช้เชื่อมเหตุการณ์ ไม่บันทึก attempt token ไม่มี CSV/policy/signedquery ใน logs |

ทุก resource อยู่ project เดียวกัน Eventarc location ตรง incoming bucket; Firestore เป็น managed regional service ไม่วาดอยู่ใน VPCsubnet และ Cloud Run ในโจทย์นี้ไม่ได้ใช้ VM/privateVPC/NAT เพิ่มเพียงเพื่อให้ Diagram ใหญ่ Worker ใช้ ingress all พร้อม IAMauthentication เพื่อให้ Eventarc และเครื่องมือ operator ที่ได้รับอนุญาตเรียกได้ **ไม่อ้างว่าเป็น private network endpoint** Public portal ต้องผ่าน Appauth สำหรับทุก businessendpoint ยกเว้น login/health/static

Named Firestore database แยกจากข้อมูลระบบอื่นเพื่อลดความเสี่ยงตอน Cleanup แต่ IAM ต้องตรวจ scope ตาม database ที่ใช้จริง ไม่อ้างว่าแยก database แล้ว project-widegrants จะหายไปโดยอัตโนมัติ

### Identity และ permission matrix

| Identity | อนุญาต | ไม่อนุญาต / จุดตรวจ |
|---|---|---|
| portal SA | อ่าน auth Secret ที่ระบุ; อ่าน/สร้าง/แก้ job ผ่าน Firestore; signBlob บน signer ทั้งสอง; invoke worker เฉพาะ service เพื่อ manualretry | ไม่มี Storageobjectadmin/ไม่อ่าน incomingbytes; ไม่มี privatekey; signBlob ไม่จำเป็นต้อง grantTokenCreator ทั้ง project |
| upload signer | storage.objects.create เฉพาะ incoming bucket | ไม่มี get/list/delete/update; replaypolicy ต้องไม่ overwriteobject เดิม |
| download signer | storage.objects.get เฉพาะ results bucket | ไม่มี create/delete/list; portal ต้องตรวจ owner ก่อนออก GET URL |
| worker SA | Firestorejob transactions; getincoming generation; create/getresults | ไม่มี signBlob/ไม่มี auth Secret/ไม่ลบหรือแก้ incoming; ไม่ให้ Editor |
| Eventarc trigger SA | eventarc.eventReceiver ตาม scope ที่บริการกำหนด และ run.invoker เฉพาะ worker | ไม่มี permission อ่านไฟล์เพื่อทำแทน worker |
| Cloud Storage service agent | pubsub.publisher สำหรับ directeventtransport ตามเอกสาร | แยกจาก trigger SA/runtimeworker ไม่ให้ StorageAdmin แทน |
| ผู้ดูแล Lab | deploy/actAs/inspect ตามความจำเป็นและ reviewIAM | สิทธิ์ผู้ดูแลไม่ใช้เป็นหลักฐานว่ารัน timeidentity ทำได้ |

สร้าง custom role สำหรับ iam.serviceAccounts.signBlob แล้ว bind บน signer แต่ละตัวให้ portal แทน role ที่รวม getAccessToken โดยไม่จำเป็น หากนโยบายองค์กรไม่อนุญาต custom role ต้องบันทึกทางเลือก/สิทธิ์ส่วนเกินก่อน deploy ไม่เพิ่ม Owner เพื่อให้ผ่าน สิทธิ์ Firestore ต้องใช้ IAMcondition/database scope ที่ provider รองรับและตรวจ policy จริงก่อนเรียก least-privilege; tests emulator ไม่พิสูจน์ IAM

### HTTP และ upload contract

Portal ใช้ Flask signed session, Secure/HttpOnly/SameSite=Lax, CSRF สำหรับทุก mutation, hashedsyntheticpasswords และ operatorrole; HTML/JS ใช้ same-originAPI ไม่มี password หรือ CSRF ใน localStorage ไม่มี inlineexecution จาก filename/CSV

| Endpoint | สัญญา |
|---|---|
| POST /api/login, POST /api/logout | จำกัด requestbody, CSRF ที่เหมาะกับ session, genericbadlogin, ไม่ logcredentials |
| GET /api/session | คืน user/role/CSRF สำหรับ session ที่เปิดอยู่ ไม่คืน passwordhash |
| POST /api/jobs | owner จาก session ไม่รับ owner จาก body; รับ displayname ที่จำกัดและ idempotencykey; สร้าง job+quotareservation ใน transaction |
| POST /api/jobs/{id}/upload-policy | owner ผ่านก่อน; ออก policy เฉพาะ awaiting_upload และภายใน upload deadline; retry ได้แต่ใช้ objectkey เดิม |
| GET /api/jobs, GET /api/jobs/{id} | queryowner ฝั่ง server, จำกัด page size20/cursor; other-owner404; ไม่คืน policy หรือ objectstorageURL |
| POST /api/jobs/{id}/download-link | owner+CSRF+success+notexpired; signedGET ตรึง outputgeneration; Cache-Control:no-store |
| POST /api/operator/jobs/{id}/retry | operator+CSRF; จำกัด epoch/attempt; preservegeneration/limits/version; เรียก worker ด้วย IDtoken และ audience ของ worker |
| POST worker /events/storage | Cloud Run IAM ก่อนเข้า App; CloudEvents binary headers+JSONdata; จำกัด body64KiB; ตรวจ eventtype/source/bucket/key/generation ซ้ำ |
| GET /livez, GET /healthz | ไม่แก้ข้อมูล; livezprocess/config, healthz boundedmetadataread ไม่มี list ทุก job |

Baseline: input1,048,576bytes/10,000rows; change5,242,880bytes/50,000rows; แต่ละ field ไม่เกิน 128chars, SKU รูปแบบ allowlist, quantity1..1,000,000 และ unit_price_satang0..100,000,000; จำกัดผลรวมไม่เกิน signed64-bit integer ปฏิเสธ NaN/decimal/bool/extra columns/nullbytes/quotednewline ถ้า parsercontract ไม่รองรับ BOM/CRLF ต้องกำหนดและทดสอบชัดเจนก่อนประกาศใช้งานได้

POSTpolicy อายุสูงสุด 300s และไม่เกิน upload_deadline; key ตรง incoming/{jobUUID}/source.csv, Content-Type=text/csv, lengthrange1..job.max_bytes ไม่มี starts-withkey ที่เปิดให้เลือก path เอง Browser ใช้ FormData ส่ง policyfields ตามที่ API ให้และ file เป็น field สุดท้าย ไม่ตั้ง multipartboundary เอง กำหนด success_action_status201 แล้วตรวจ response ก่อน polljob

Storagepolicy ตรวจ headers/size แต่ไม่รู้ว่า bytes เป็น CSV จริง Workerdownload แบบ bounded max_bytes+1 และตรึง generation ไม่ใช้ download_as_bytes แบบไม่จำกัดกับ eventsize ที่เชื่อจาก client ไม่ followURL ใน event ไม่ evalformula หรือเปิด spreadsheet เพื่อรัน macro

Uploadpolicy เป็น bearerpermission และ replay ได้ระหว่าง TTL การ createobject ชื่อเดิมอีกรอบต้องถูกปฏิเสธจาก signer ที่ไม่มี delete/update; ต้องพิสูจน์บน GCP จริง หาก storageAPI/library ต้องการ permission เกินที่ตั้งไว้ให้ทบทวน contract ไม่ให้ overwrite เพื่อทำให้ test ผ่าน

DownloadTTL สูงสุด 60s และไม่เกินเวลาที่ job เหลือก่อน expires_at ออก URL เฉพาะ generation ที่ตรวจแล้ว Content-Disposition attachment ชื่อ server กำหนดและ Content-Type application/json; ผลใกล้หมดอายุจนเหลือไม่ถึง 1s ให้ปฏิเสธ การ logout ไม่เพิกถอน link ที่ออกไปแล้ว

### Metadata และ state machine

jobs/{UUID} มี owner, display_name, object_name, created_at/upload_deadline/expires_at/delete_after, max_bytes/max_rows, processor_version, state, input_generation, input_sha256, attempt_epoch/count/token/lease_until, output_name/generation/sha256, safe_reason และ timestamps ส่วน idempotencyrecords ใช้ hash(owner+key)พร้อม fingerprint และ jobreference ไม่เก็บ rawkey ใน logs

ตั้ง expires_at=created+24h สำหรับ Appaccess; upload_deadline=created+5min; delete_after=created+48h สำหรับ TTLcleanup หลัง uploaddeadline จะขอ policy ใหม่ไม่ได้ แต่ metadata อาจยังเป็น awaiting_upload จนถึง Appexpiry หรือมีการประมวลผล event ไม่ได้มี reconciler เปลี่ยนทุกงานเป็น expired ทันที TTLdelete อาจล่าช้าและไม่ลบ Storageobjects โดยอัตโนมัติ

| สถานะเดิม | เหตุการณ์ | ผล |
|---|---|---|
| awaiting_upload | finalizedevent ที่ตรง key/bucket และไม่เลย deadline/expiry | transactionbindgeneration ครั้งเดียวแล้ว claimprocessing |
| processing / lease ยังไม่หมด | duplicategeneration เดิม | retryable503 ไม่ ack แล้วพึ่ง worker เดิมเพียงตัวเดียว |
| processing / lease หมด | event เดิมส่งใหม่ | claimtoken ใหม่; worker เก่าไม่มีสิทธิ์ publishstatus |
| processing | validation ไม่ผ่าน | rejected+safe_reason แล้ว ack204; ไม่มี published output |
| processing | outputverified + token ยังตรง | succeeded พร้อม generation/hash แล้ว ack204 |
| processing | transientstorage/metadata failure | ปล่อย lease ให้หมดหรือ release โดย token; return503 สำหรับ transportretry |
| succeeded/rejected/expired | duplicateevent | ack204 โดยไม่สร้างผลใหม่ |
| ทุกสถานะที่ bind แล้ว | generation ต่างจากที่ bind | ignore+reasonlogged ไม่เปลี่ยน owner/input/result |
| retry budget ครบ | transient ครั้งถัดไป | failed พร้อม safe_reason และ ack; operatorretry ได้ตาม policy ไม่วนตลอดไป |

Lease120s เป็นช่วงถือสิทธิ์ก่อน claim ใหม่ ไม่ใช่ตัวหยุด process; Cloud Run request timeout60s และ Gunicorn timeout65s ส่วน GCS แต่ละ operation ตั้ง timeout5s และ retry=None โค้ดยังไม่มี wall-clock deadline รวม 45s จึงไม่รับประกันว่า operation ทั้งหมดจะจบภายใน 45s หรือว่า HTTPtimeout หยุดงานทันที ใช้ token-fencedpublish และ create-or-verifyoutput รับมือ attempt ที่ทับช่วงกัน และต้องทดสอบ timeout/recovery บน Cloud จริง ไม่ต่อ lease ไม่จำกัด attempt ไม่เกิน 5 ต่อ epoch, manualretry ไม่เกิน 2epochs เพิ่มจากครั้งแรก; rejected/expired ไม่เปิด retry เพื่อหลบ validation ต้องสร้าง job ใหม่ผ่านขั้นตอนปกติ งาน failed เก็บ generation เดิมและนำ output ที่ถูกต้องกลับมาใช้ได้

Unknown/malformedevents: invalidenvelope400 เพื่อให้เห็น configurationerror; authentic แต่ไม่อยู่ bucket/key/jobnamespace ของ Lab ให้ ack204 และ safeignoredreason ไม่สร้าง job จาก event หาก metadata อ่านไม่ได้เป็น 503 ไม่เหมาว่า unknown แล้ว ack งานที่หาไม่เจอจริงต้อง logignored และให้ runbookreconcile ไม่สร้าง owner จาก objectmetadata ที่ client ปลอมได้

### Output commit และการกู้ช่องว่างข้ามบริการ

![ลำดับ claim ตรวจข้อมูล เขียนผล และ publish พร้อมการกู้ช่องว่าง output–metadata](assets/diagrams/recovery-preview.png)

[SVG การกู้คืน](assets/diagrams/recovery.svg): หากผลเขียนแล้วแต่สถานะยังไม่สำเร็จ รอบถัดไปต้องตรวจและใช้ผลเดิม ไม่เขียนทับเพื่อให้ผ่าน


คำนวณ summary แบบ deterministic ใช้ integer, sortedSKU, canonicalUTF-8JSON ไม่มี currenttime/attempttoken ใน businessbytes Outputkey คือ results/{jobUUID}/{inputGeneration}/{processorVersion}/summary.json เขียน if_generation_match=0 พร้อม metadatainputSHA/processorversion ไม่ updateobject ที่มีอยู่

ถ้าได้ preconditionfailed ให้ GETexistinggeneration แบบ bounded และเทียบ canonicalbytes/SHA/inputgeneration/version ก่อน reuse หากไม่ตรงให้ failed_integrity และหยุด ไม่ overwrite เพื่อให้เลขตรง ส่วน timestamp การ attempt เก็บใน Firestore แยกจากผลสรุป

หลังเขียนหรือ verifyoutput แล้วจึง Firestoretransaction ตรวจ token/generation/version/expiry ก่อน publishsuccess ถ้า worker เก่าถูก fenceoutput ที่คำนวณเหมือนกันอาจยังเกิดได้ แต่ไม่เปลี่ยน state และไม่มีผลธุรกิจซ้ำ worker ใหม่ verifyreuse แล้ว commit ต่อ ถ้างาน expire ระหว่างทำต้องไม่ publishdownloadable success; เก็บ orphanoutput ให้ cleanup ตาม retention

Faultcontrol เป็น revisionconfig สำหรับ sandbox: fail_after_output_once ตาม jobmarker ที่เก็บใน Firestore ไม่รับ flag จาก client ทั่วไป ปิด fault แล้ว replayeventgeneration เดิมต้องจบได้ด้วย output เดิม ไม่อ้าง exactly-oncedelivery แต่พิสูจน์ logicalresultconvergence

### ขอบเขตการทดสอบ

1. Domain parserfixtures: valid/CRLF/BOMcontract, duplicateID, invalidUTF8/header/quantity/price, maxbytes/rows/field/total bounds; exactexpectedsummary
2. Firestore emulator จริง: owner/idempotencytransaction, concurrentclaim, generationbinding, leaseexpiry, stale-tokencommit, retry budget/manualepoch, expiration และ quotareservation ไม่ใช้ fake อย่างเดียว
3. Storageadapter: boundedgenerationread, create-onlyoutput, existinghashmismatch, signedpolicyexactconditions/keylesssigner; mockrequest ใช้ตรวจ APIcontract แต่ไม่เรียก GCP จริง
4. HTTP/browser: aliceupload/status/download, bob404, anonymous401, operator403, CSRF, workerIAM แยกจาก Appunit checks, UIerror/retry/pollbounded โดยไม่เผย signedquery
5. Recoveryintegration: outputcreated→fault→duplicateevent→sameoutputgeneration→success; invalidfileackterminal; failedtransient สามารถ manualretry; expiredjob ไม่ออก link
6. Terraform: fmt/init-backendfalse/validate; IAM/triggerlocation/Firestoreisolation/staticconfigtests; actualplan/apply และ signedupload/permission/expiry ต้องผู้เรียนรันบน GCP
7. Guide: expected/actual ข้างทุก Task, fixtures+boundedtools, resourceinventory และ cleanuporder; ไม่มี CloudPASS ล่วงหน้า

Quota ฝึก: ไม่เกิน 5activejobs/owner และ 20newjobs/owner/UTCday ด้วย transactioncounter; จำกัดรวมชุดทดสอบ 40jobs และไฟล์ change สูงสุด 5MiB ต่อไฟล์ นี่เป็น Appguard ไม่ใช่ Billinghardcap publiclogin ยังไม่ใช่ productionabuseprotection ต้องตั้งเวลาเปิดและ maxinstances ร่วมด้วย

Retention: incoming/results lifecycledelete หลัง 2 วันและบันทึก softdeletepolicy จริง; FirestoreTTL ใช้ delete_after เมื่อเปิด policy แล้ว App ตรวจ expiry เองก่อน TTL; ไม่เปิด bucketversioning โดยไม่จำเป็น แต่ทุก read/resultbinding ยังใช้ generation Lifecycle/TTL ไม่ใช่ backupstrategy และไม่รับประกันไม่มีค่าใช้จ่ายหลัง UI ซ่อนงาน

แหล่งอ้างอิง Design: [Eventarc Storage routing/location](https://docs.cloud.google.com/eventarc/standard/docs/run/route-trigger-cloud-storage), [Eventarc identities](https://docs.cloud.google.com/eventarc/docs/roles-permissions), [Python signed POST policy API](https://docs.cloud.google.com/python/docs/reference/storage/latest/google.cloud.storage.client.Client), [Firestore database locations](https://docs.cloud.google.com/firestore/native/docs/locations), [Firestore transaction retries](https://firebase.google.com/docs/firestore/manage-data/transactions)

ข้อจำกัด SDK/API และสิทธิ์จริงต้องตรวจตอน deploy ตามจุดตรวจใน Tasks ผล CI ด้านล่างไม่ใช่หลักฐานว่าโครงสร้างนี้ถูกสร้างบน GCP แล้ว


## ไฟล์ที่ใช้ใน Lab และพฤติกรรมสำคัญ

| ส่วน | ไฟล์หลัก | ใช้ทำอะไร |
|---|---|---|
| ข้อมูลและรายงาน | [CSV domain](app/csv_domain.py), [valid CSV](fixtures/valid-sales.csv), [expected summary](fixtures/valid-sales.expected.json) | ตรวจข้อมูลและคำนวณผลแบบ deterministic |
| สถานะและฐานข้อมูล | [state transitions](app/job_state.py), [Firestore repository](app/firestore_jobs.py) | สร้างงาน, quota, idempotency, claim/lease, fencing และประวัติ |
| การประมวลผล | [processor](app/processor.py), [Storage adapter](app/gcs_objects.py), [event parser](app/storage_events.py), [worker HTTP](app/worker_http.py) | อ่าน input generation เดิม เขียนหรือยืนยันผล แล้วบันทึกสถานะ |
| Portal และสิทธิ์ชั่วคราว | [Portal API](app/portal_http.py), [signed access](app/signed_access.py), [runtime](app/portal_runtime.py), [retry dispatch](app/retry_dispatch.py) | Login, owner checks, signed POST/GET และ operator retry |
| หน้าจอ | [HTML](app/static/index.html), [JavaScript](app/static/app.js), [CSS](app/static/style.css) | ส่งไฟล์ ดูสถานะ ดาวน์โหลด และแก้คำขอที่ไม่ทราบผล |
| บัญชีทดลอง | [create-secrets.py](scripts/create-secrets.py) | สร้าง auth bundle และรหัสสังเคราะห์ไว้ในโฟลเดอร์ส่วนตัวใหม่ ไม่เขียนทับ |
| เครื่องมือผู้เรียน | [verify-report.py](scripts/verify-report.py), [Portal client](scripts/portal_client.py), [upload boundary runner](scripts/test-upload-boundary.py), [change fixtures](scripts/create-change-fixtures.py), [event replay](scripts/replay-storage-event.py) | เทียบผล ทดสอบข้อจำกัด Storage และสร้างข้อมูลเปลี่ยนขนาด |
| Container | [Dockerfile](Dockerfile), [entry point](scripts/run-container.py) | Image เดียวเลือกบทบาท Portal หรือ worker และรันด้วย UID 10001 |
| Infrastructure | [foundation](infra/foundation/main.tf), [workloads](infra/workloads/main.tf) | แยกฐานระบบออกจากบริการ เพื่อทราบ Portal URL ก่อนตั้ง CORS |
| การทดสอบ | [domain](tests/test_csv_domain.py), [Firestore integration](tests/test_firestore_jobs.py), [browser journey](tests/test_browser_journey.py), [guide checks](tests/test_guide.py) | ตรวจ business invariants, race/recovery, การใช้งานจริงใน CI และตัวอย่างคำสั่ง |

### รูปแบบ CSV และผลที่ควรได้

ไฟล์ valid มี 3 รายการ รวม 6 หน่วย ยอด 72,400 สตางค์ เทียบกับ expected summary โดยคำนวณ SHA256 จาก bytes ของไฟล์ที่ส่งจริง ไม่คัดลอก hash ของไฟล์ที่อาจมี line ending ต่างกัน

ตัวตรวจรับ UTF-8 BOM หนึ่งชุดที่ต้นไฟล์, LF/CRLF และ quoted fields แต่ไม่รับ newline ใน field, blank record, null byte, คอลัมน์เกิน, whitespace รอบตัวเลข, leading zero เช่น 01, exponent หรือ float ราคาเป็นศูนย์ได้ แต่ quantity ต้องมากกว่าศูนย์ SKU ใช้ตัวพิมพ์ใหญ่ตาม allowlist ไม่ประเมินสูตรหรือรัน macro

Storage adapter อ่านแบบ raw และตรึง generation ตรวจขนาดจาก metadata และจำกัด buffer ซ้ำ ปฏิเสธ content encoding/MIME ที่ไม่ตรง ผลลัพธ์ไม่เกิน 8 MiB เขียนด้วย if_generation_match=0 และ CRC32C หากมีผลอยู่แล้วต้องเทียบ bytes/hash/metadata ก่อน reuse ไม่เขียนทับสิ่งที่ไม่ตรง

### คำขอซ้ำ งานค้าง และประวัติ

การสร้าง job, idempotency record และ quota อยู่ใน Firestore transaction เดียวกัน key เดิมคืนงานเดิม แม้ quota เต็ม แต่เปลี่ยนชื่อ/limits/version ด้วย key เดิมจะ conflict หาก record ชี้งานที่หายหรือหมดอายุจะไม่สร้างงานใหม่เงียบ ๆ

Quota จำกัด 5 active jobs และ 20 งานใหม่ต่อ owner ต่อ UTC day งานที่สำเร็จ ถูกปฏิเสธ หรือหมดอายุคืน active slot เมื่อสร้างงานถัดไป งาน failed ที่ยัง retry ได้ยังนับ active และงาน awaiting_upload ไม่คืน slot ทันทีที่หมด upload deadline เพราะ event ของไฟล์ที่ส่งทันอาจมาช้า ต้อง reconcile หรือรออายุงาน ไม่ใช้ TTL เป็นตัวปล่อย quota ทันที

callback ของ transaction ไม่อ่าน Storage และอ่านเวลาใหม่เมื่อ SDK retry ส่วน history บันทึกพร้อม state change สูงสุด 100 รายการ พร้อม count/truncated flag โดยไม่มี token หรือ credentials รายการงานแบ่งหน้าครั้งละไม่เกิน 20 รายการ cursor เป็นตำแหน่ง ไม่ใช่สิทธิ์อ่านของผู้อื่น

Operator retry เตรียม epoch ก่อนเรียก network คำขอเดิมใช้ epoch เดิม หาก Portal ตอบ 202 แบบ acknowledged หรือ unconfirmed ต้องอ่านสถานะงานต่อ ทั้งสองไม่ใช่ผลธุรกิจว่าสำเร็จ จำกัด manual retry เพิ่มอีกสอง epoch และไม่เปิดให้ใช้ข้าม validation/integrity failure

### Browser และขอบเขตความลับ

Portal ใช้ session cookie แบบ Secure/HttpOnly/SameSite=Lax และ CSRF ทุก mutation ก่อนสร้างงาน Browser เก็บเฉพาะ request key, SHA ของไฟล์, ชื่อไฟล์ และ job ID สำหรับ resume ไม่เก็บ password, CSRF, policy หรือ signed URL ใน sessionStorage หน้าจอใช้ textContent ไม่รัน HTML จากชื่อไฟล์

หากคำตอบ create หาย ให้เลือกไฟล์เดิมเพื่อ resolve key เดิมก่อนเริ่มงานใหม่ เมื่อ upload สำเร็จต้องตรวจ Storage ตอบ 201 แล้วจึงติดตามสถานะ โดย poll ไม่เกิน 30 รอบ ข้อมูลที่ดาวน์โหลดเป็น bearer capability อายุสั้น ไม่เผย URL ในภาพหรือ logs

Runtime อ่าน Secret version แบบตัวเลขและ attached identity ไม่ใช้ private key หรือ emulator ใน Cloud Run ค่า Secret mount 0444 ให้อ่านได้ด้วย non-root container แต่ไม่ได้แยกสิทธิ์แต่ละ process ภายใน container จึงต้องถือ container เป็น trusted boundary

### Infrastructure และสิ่งที่ CI พิสูจน์ได้

Foundation สร้าง buckets แบบ private/ไม่ force destroy, named Firestore พร้อม deletion protection, TTL, service accounts ห้าชุด, custom get/create/signBlob roles, Secret container และ Artifact Registry โดยไม่ใส่ Secret payload ใน Terraform ตั้ง CORS เฉพาะ origin จริงหลัง workloads พร้อม

Workloads ตรึง image digest, ให้ worker invoker เฉพาะ Portal/trigger SA, เปิดหน้า login ของ Portal ผ่าน App auth และตั้ง fault flags เป็น false ค่าเริ่มต้น ใช้ /livez สำหรับ startup/liveness ไม่ทำให้ความขัดข้องของ Firestore กลายเป็น process-health โดยอัตโนมัติ

[CI 39994451947](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39994451947) ของ source `58b8f719b6a881c40936fd95c88c6c1733dec19f` ผ่านทั้ง workflow: 52 domain/state/tooling/guide tests และ 53 SDK/HTTP/runtime/Firestore/browser tests รวม 105 tests พร้อม container build/import/non-root/private-file exclusion และ Terraform validate สอง roots

[CI 39994675895](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39994675895) job lab006-domain ตรวจคู่มือหลังเพิ่มภาพแล้วผ่าน: Bash 25 blocks, JavaScript Console 7 blocks, Tasks 0–13/8B และ relative links ส่วนภาพ SVG/PNG สองชุดตรวจด้วยสายตาที่ 960px จาก source เดียวกับ generator ที่เผยแพร่ โดยเก็บที่มาไอคอนและ source commit ไว้ใน provenance

การตรวจชุดนี้ไม่ใช่ผลสร้างระบบบน GCP: Firestore ใช้ emulator, browser ใช้ HTTPS loopback, Storage/signing ใช้ test doubles ไม่พิสูจน์ IAM, ลายเซ็นจริง, Eventarc delivery, CORS หรือ performance บน GCP การตรวจ Terraform ไม่ใช่ plan/apply และช่อง Actual ของผู้เรียนยังว่าง

Image base ใช้ official Python 3.12.15-slim-bookworm ซึ่งอาจได้รับ rebuild ต้องบันทึก resolved image digest ของการ build จริง ไม่อ้าง bit-reproducible จาก tag หรือ dependencies ที่ไม่ได้ล็อกทุกชั้น

## หลักฐาน UI จาก CI (ไม่ใช่ผล Deploy GCP)

![Portal หลัง resume งานเดิมใน Chrome บน GitHub Actions](assets/ui-ci-preview.png)

[CI39991195096](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39991195096) / job120543077262 ผ่าน Browserlost-create-response→reload→samekey→onejob/oneoutput รวมถึง 18Firestoreintegrationtests และชุด SDK/HTTP/runtime ที่อยู่ใน job เดียวกัน ภาพนี้ใช้ HTTPSloopback/Firestoreemulator จริง ส่วน Storage/signing เป็น testdouble ไม่ใช่ GoogleCloudConsole หรือ GCS/IAMverification [รายละเอียดที่มาภาพ](assets/ui-ci-provenance.json)

ตรวจภาพรอบนี้แล้ว: แถบสถานะและแถวงานแสดง succeeded ตรงกัน อ่านรายละเอียด job/limits/attempt ได้ครบ ภาพไม่แสดง signedURL/password ส่วน containerbuild/import/nonroot/privatefileexclusion และ Terraformvalidate ทั้งสอง roots ผ่านใน workflow เดียวกัน ผลเหล่านี้ยังไม่พิสูจน์ Cloud Run IAM/Eventarc/GCS จริง


## เริ่มทำ Lab — สร้างระบบจาก sandbox ว่าง

ส่วนนี้เป็นคู่มือที่ผู้เรียนใช้สร้างทรัพยากรมีค่าใช้จ่าย ไม่ใช่คำสั่งที่ผู้จัดทำรันแทนคุณ ช่อง Actual ยังไม่มีผล GCP บันทึกไว้ล่วงหน้า คู่มือมีร่าง Tasks 0–13 แล้ว ยังต้องตรวจ Diagram และทบทวนทั้งชุดก่อน Guide-ready

### Task 0 — เตรียม project สิทธิ์ และพื้นที่ทำงาน

**ทำที่ไหน:** Google Cloud Console → เลือก sandbox project → Activate Cloud Shell ใช้ Bash ของ Cloud Shell ไม่ใช่ PowerShell และไม่ใช่ terminal บน laptop

1. เลือก project สำหรับ Lab นี้โดยเฉพาะ เปิด Billing และตั้งเวลาปิดระบบ/งบก่อนเริ่ม Budget alert ไม่ใช่ hard cap ค่า Cloud Run, builds/images, Storage operations/soft delete, Firestore และ Eventarc/PubSub อาจยังมีหลังหยุด Browser
2. เปิด IAM & Admin → Quotas & System Limits ตรวจ Cloud Run ใน asia-southeast1, Firestore named databases, Eventarc triggers และ Artifact Registry ตรวจนโยบายองค์กรเรื่อง public invoker ด้วย เพราะ Portal เปิดให้เข้า login แต่ worker ไม่เปิด anonymous
3. ผู้ทำต้องสร้าง APIs/SA/custom roles/IAM bindings/Storage/Firestore/Run/Eventarc/Secret containers ได้ และมี actAs ของ runtime/trigger identities อย่าแก้การติดสิทธิ์ด้วยการให้ Owner กับ runtime SA
4. ใน Firestore → Databases ตรวจว่าไม่มี lab006-files ของงานอื่นอยู่แล้ว ไม่เปลี่ยน default database หรือ import ของทีมอื่นเข้าระบบนี้
5. Clone ใหม่ใน persistent Cloud Shell home โดยไม่ทับงานเดิม:

```bash
export PROJECT_ID='ใส่-sandbox-project-id'
export INCOMING_BUCKET='ใส่ชื่อ-incoming-bucketใหม่ที่ไม่ซ้ำทั่วโลก'
export RESULTS_BUCKET='ใส่ชื่อ-results-bucketใหม่ที่ไม่ซ้ำทั่วโลก'
export REGION='asia-southeast1'
gcloud config set project "$PROJECT_ID"
gcloud auth list --filter=status:ACTIVE --format='value(account)'
gcloud config get-value project
umask 077
export CHECKOUT_PARENT="$(mktemp -d "$HOME/lab006-work-XXXXXX")"
git clone --branch main --single-branch https://github.com/somkid-s5/Portfolio-Lab.git "$CHECKOUT_PARENT/Portfolio-Lab"
export REPO_DIR="$CHECKOUT_PARENT/Portfolio-Lab"
export LAB_DIR="$REPO_DIR/GCP/LAB-006-private-file-processing"
cd "$LAB_DIR"
export SOURCE_COMMIT="$(git rev-parse HEAD)"
printf 'Source commit: %s\n' "$SOURCE_COMMIT"
terraform version
gcloud version
docker version
python3 --version

```

**Expected:** active account/project ตรง sandbox, SHA เต็ม 40 ตัว, Terraform1.9.x (CI ใช้ 1.9.8), Docker ใช้งานได้ และ Python3.12 ที่รองรับ dependencies ถ้าไม่มี Terraform ให้ติดตั้งรุ่นที่รองรับจาก HashiCorp ก่อน ไม่ลด constraint เพื่อข้ามการตรวจ provider ตรึง 6.50.0 ไม่ใช้ init-upgrade ระหว่างทำ Lab โดยไม่ทบทวน diff

พื้นที่นี้อยู่ persistent home ไม่ใช่ /tmp เก็บ path และ state ของทั้งสอง Terraformroots ไว้จน Cleanup จบ หากเปิด CloudShell ใหม่ให้กลับ checkout/state เดิมและตั้ง variables คืน ไม่ clone ใหม่แล้ว apply ซ้ำโดยไม่ตรวจ state ไฟล์ state/plan/Secretbundle เป็น private ห้าม commitGitHub หากองค์กรไม่ให้เก็บ state ใน CloudShell ต้องเตรียม controlledremote backend ก่อน provision

**จุดบันทึก T00:** project/account ที่ตรวจ …; SOURCE_COMMIT …; versions …; persistentdirectory/ผู้มีสิทธิ์เข้าถึง …; budget/เวลาปิด …; quotas/orgpolicy …; prefix ชื่อที่ยืนยันว่าไม่ชนระบบอื่น …  
**เกณฑ์ไปต่อ:** project/สิทธิ์/งบ/พื้นที่ state ครบ ถ้ายังไม่ครบหยุดก่อน apply ไม่เปลี่ยน worker เป็น public เพื่อให้ขั้นตอนผ่าน

### Task 1 — สร้าง foundation โดยยังไม่เปิดบริการ

**เป้าหมาย:** privatebuckets สองใบ, Firestoredatabase แยก, identities, IAM, authSecretcontainer ว่าง และ ArtifactRegistry ไม่มี Secretpayload ใน Terraformstate

**ทำที่ไหน:** Cloud Shell ที่ LAB_DIR จาก T00 ทุก apply ด้านล่างผู้เรียนต้องอ่าน plan และยืนยันเอง

```bash
cd "$LAB_DIR"
export TF_VAR_project_id="$PROJECT_ID"
export TF_VAR_bucket_names="{\"incoming\":\"$INCOMING_BUCKET\",\"results\":\"$RESULTS_BUCKET\"}"
export TF_VAR_portal_origin=''
terraform -chdir=infra/foundation init -input=false
terraform -chdir=infra/foundation validate
terraform -chdir=infra/foundation plan -out=foundation.tfplan
terraform -chdir=infra/foundation show -no-color foundation.tfplan

```

ตรวจ plan: database ชื่อ lab006-files/FIRESTORE_NATIVE/asia-southeast1 ไม่ใช่(default), protection เปิด/PREVENT, buckets ชื่อตรงตัวแปรไม่ซ้ำกัน/publicaccessprevention/uniform/force_destroyfalse, lifecycle2 วัน/softdelete7 วัน, SA5 ชุดและ customroleget/create/signBlob ตาม matrix ไม่มี Secretversion/privatekey/CloudRun/Eventarctrigger หรือ resource ลบของระบบอื่น ถ้าไม่ตรงอย่า apply

```bash
terraform -chdir=infra/foundation apply foundation.tfplan
terraform -chdir=infra/foundation output
gcloud firestore databases describe --database=lab006-files --format='yaml(name,locationId,type,concurrencyMode,deleteProtectionState)'
gcloud storage buckets describe "gs://$INCOMING_BUCKET"
gcloud storage buckets describe "gs://$RESULTS_BUCKET"
gcloud storage buckets get-iam-policy "gs://$INCOMING_BUCKET"
gcloud storage buckets get-iam-policy "gs://$RESULTS_BUCKET"
gcloud secrets get-iam-policy lab006-auth

```

เปิด Console → Firestore → Databases → lab006-files ตรวจ location/type/protection แล้วเปิด TTLpolicies ตรวจ delete_after ของ jobs/idempotency/owner_quotas รอ policy พร้อมตาม operation เดิม ไม่สร้าง database ซ้ำชื่ออื่นเพราะรอ จากนั้น Storage → buckets แต่ละใบ → Permissions/Protection/Lifecycle ตรวจไม่ public และ retention ตามแบบ

**Expected:** ไม่มี allUsers/allAuthenticatedUsers ที่ bucket; upload signer มี createincoming อย่างเดียว, workergetincoming/create+getresults, download signergetresults, portal ไม่มี objectaccess โดยตรง ส่วน authSecretAccessor ให้ portal เท่านั้น ต้องตรวจ inheritedproject/orggrants ร่วมด้วย policy ระดับ bucket ไม่ได้ถอนสิทธิ์กว้างที่มีอยู่ก่อน

FirestoreIAMcondition ต้องชี้ database นี้โดยเฉพาะ ไม่ได้แยกสิทธิ์เป็นราย collection หรือราย Appuser และ Console ผู้ดูแลไม่ใช่หลักฐานว่า runtimeSA ถูกจำกัดจริง TTL/lifecycle ไม่รับประกันลบตรงเวลา softdelete อาจเก็บของต่อ 7 วันและคิดค่าใช้จ่าย

**ถ้าไม่ผ่าน:** bucketname ชนให้เลือกชื่อใหม่ก่อน apply ไม่ importbucket คนอื่น; permissioncustomrole/SA ให้แก้สิทธิ์ผู้ deploy ไม่ให้ runtimeOwner; API/TTLoperation ยังรันให้ตรวจ operation เดิมจน terminal ก่อน apply ใหม่; Firestorelocation ผิดให้หยุด ไม่ลบ database เพื่อแก้แบบเดาสุ่ม

**จุดบันทึก T01:** reviewedplan …; bucketpolicy/retention …; database/location/protection …; TTL สถานะ …; IAMcondition/runtimeSA ที่ตรวจ …; inheritedgrants/ข้อจำกัด …; error/วิธีแก้ …  
**เกณฑ์ไปต่อ:** foundation ตรง Design และ state ถูกเก็บ ไม่ใช่เพียง exit0

### Task 2 — สร้างบัญชีสังเคราะห์และ Secret version

**ทำที่ไหน:** Cloud Shell ที่ LAB_DIR ห้าม set-x, gcloud--log-http หรือถ่ายภาพไฟล์ที่มีรหัส

```bash
cd "$LAB_DIR"
umask 077
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/create-secrets.py --out secrets
export AUTH_VERSION_NAME="$(gcloud secrets versions add lab006-auth --data-file=secrets/auth.json --format='value(name)')"
export AUTH_VERSION="$(basename "$AUTH_VERSION_NAME")"
printf 'Auth version: %s\n' "$AUTH_VERSION"
gcloud secrets versions list lab006-auth --format='table(name,state)'

```

**Expected:** generator พิมพ์เฉพาะ event ไม่พิมพ์รหัส, secretsdirectorymode700/auth.json กับ demo-logins.jsonmode600, AUTH_VERSION เป็นเลขและ ENABLED auth.json มี hash/sessionkey ไม่มี plaintextpassword ส่วน demo-logins.json เป็น private สำหรับอ่านรหัสตอน Browserlogin ไม่อัปโหลดไฟล์นี้เป็น Secret ที่ App ไม่ต้องใช้

ถ้า directory มีอยู่ generator จะปฏิเสธ อย่าลบเพื่อข้ามการป้องกันหรือออก bundle ใหม่แล้วเปลี่ยน version โดยไม่รู้ว่าใช้อะไรอยู่ หาก uploadversion ล้มให้ตรวจ versionslist ก่อนรันใหม่ ไม่ใช้ latest เพื่อเลี่ยงการตัดสินใจ deployment จะ mountnumericversion และ App อ่านตอน startup ถ้า mount อ่านไม่ได้ต้องแก้ IAM/version ไม่ปิด auth

**จุดบันทึก T02:** AUTH_VERSION …; versionENABLED/IAM …; privatefilepermissions ที่ตรวจ …; ข้อผิดพลาด/retest …  
ไม่บันทึกรหัส/passwordhash/sessionkey/payload ลงช่องนี้  
**เกณฑ์ไปต่อ:** version ที่ตั้งใจใช้ชัดเจนและ runtimeportal อ่านได้ตาม policy worker ไม่มีสิทธิ์อ่าน authSecret

### Task 3 — Build และบันทึก image digest

**ทำที่ไหน:** Cloud Shell ที่ LAB_DIR; build จาก checkoutSOURCE_COMMIT ที่สะอาด ไม่คัดลอก secrets เข้า app โครง Docker ใช้ explicitCOPY/dockerignore แต่ผู้เรียนยังต้องตรวจไฟล์ก่อน build

```bash
cd "$LAB_DIR"
git status --short
export IMAGE_REPOSITORY="$(terraform -chdir=infra/foundation output -raw image_repository)"
export IMAGE_TAG="$IMAGE_REPOSITORY/files:$SOURCE_COMMIT"
gcloud auth configure-docker asia-southeast1-docker.pkg.dev
docker pull python:3.12.15-slim-bookworm
docker image inspect python:3.12.15-slim-bookworm --format '{{json .RepoDigests}}'
docker build -t "$IMAGE_TAG" .
docker push "$IMAGE_TAG"
gcloud artifacts docker images describe "$IMAGE_TAG" --format=json
export IMAGE_DIGEST="$(gcloud artifacts docker images describe "$IMAGE_TAG" --format='value(image_summary.digest)')"
export PINNED_IMAGE="$IMAGE_REPOSITORY/files@$IMAGE_DIGEST"
printf 'Pinned image: %s\n' "$PINNED_IMAGE"

```

**Expected:** digest เป็น sha256 ตามด้วย 64hex, PINNED_IMAGE อยู่ repository/project นี้และอ้าง@sha256 ไม่ใช่ tag ตรวจ JSON จาก describe ร่วมด้วย หาก field ว่างหรือ push ไม่สำเร็จให้หยุด ไม่แต่ง digest หรือใช้ tag แทน [Artifact Registry describe](https://docs.cloud.google.com/sdk/gcloud/reference/artifacts/docker/images/describe)

Sourceimage รวม Portal และ worker เลือก SERVICE_ROLE ตอน runtime USER10001:10001 ไม่มี tests/fixtures/privatebundle ใน image การ build สำเร็จยังไม่พิสูจน์ Firestore/Storage/IAM หรือ CloudRunstartup Baseimage แม้ตรึง versiontag ยังอาจถูก rebuild และ pipdependencies ชั้นล่างอาจเปลี่ยน จึงจด base/image digest จริง ไม่อ้าง bit-identicalrebuild จากชื่อ tag อย่างเดียว

หาก dockerpermission/daemon ไม่พร้อมให้แก้ CloudShellruntime หรือเลือก cloudbuildenvironment ที่ได้รับอนุญาตก่อน ไม่ย้ายไปทำบน laptop เพื่อพึ่งเครื่องเปิดค้าง หาก push403 ตรวจ ArtifactRegistrywriter ของผู้ deploy ไม่เพิ่ม storageadmin ให้ signer

**จุดบันทึก T03:** commit/workingtreestatus …; baseRepoDigests …; build เวลา …; IMAGE_TAG/digest/PINNED_IMAGE …; registrydescribe ที่ตรวจ …; ปัญหา/retest …  
**เกณฑ์ไปต่อ:** image มีอยู่จริงใน registry และ digest ถูกต้อง เก็บ v1digest ไว้ใช้ backout ภายหลัง

### Task 4 — เปิด Portal/worker และ Eventarc แล้วตั้ง CORS เฉพาะ origin

**ทำที่ไหน:** Cloud Shell ที่ LAB_DIR ใช้ foundationstate/variables ชุดเดิมและ authversion/image จาก T02–03

```bash
export TF_VAR_image="$PINNED_IMAGE"
export TF_VAR_auth_version="$AUTH_VERSION"
export TF_VAR_upload_limit_mode='baseline'
export TF_VAR_worker_fail_after_output_once=false
export TF_VAR_worker_fail_before_read=false
terraform -chdir=infra/workloads init -input=false
terraform -chdir=infra/workloads validate
terraform -chdir=infra/workloads plan -out=workloads.tfplan
terraform -chdir=infra/workloads show -no-color workloads.tfplan

```

ตรวจ plan: Portal/worker คนละ SA/role แต่ image เดียว@digest, maxinstances2, Portalconcurrency8/30s worker1/60s, numericSecretmount เฉพาะ Portal, /livezprobes, Eventarctypefinalized+incomingbucket ใน asia-southeast1/path/events/storage; workerinvoker เฉพาะ portal/triggerSA ไม่มี allUsers มี publicinvoker เฉพาะ Portal เพื่อเข้า login ไม่ให้ portal อ่านไฟล์ตรงหรือ worker อ่าน authSecret

```bash
terraform -chdir=infra/workloads apply workloads.tfplan
export PORTAL_URL="$(terraform -chdir=infra/workloads output -raw portal_uri)"
export WORKER_URL="$(terraform -chdir=infra/workloads output -raw worker_uri)"
gcloud run services describe lab006-portal --region="$REGION" --format=yaml
gcloud run services describe lab006-worker --region="$REGION" --format=yaml
gcloud run services get-iam-policy lab006-worker --region="$REGION"
gcloud eventarc triggers describe lab006-incoming-finalized --location="$REGION" --format=yaml

```

Console → Cloud Run → แต่ละ service → Revisions/Logs ตรวจ readyrevision, digest, runtimeSA, Secretmount และ containerstartup ไม่ถือว่า applyexit0 แทน HTTPready Eventarc → Triggers → lab006-incoming-finalized ตรวจ source/region/destination/identity และสถานะพร้อม หาก serviceagent/IAMpropagation ยังไม่พร้อมให้ดู operation/error เดิม ไม่สร้าง trigger ชื่อใหม่ซ้ำ

worker มี HTTPSURL ที่เข้าถึง network ได้แต่ต้อง IAMauthentication ไม่ใช่ privateVPCendpoint ต้องไม่มี publicinvoker ที่ Portalstartup อ่าน authmountmode0444 ภายใน trustedcontainer สำหรับ nonroot ไม่อ้าง filemode แทน per-processCloudIAM

เมื่อได้ PortalURL จริงจึงกลับ foundation ตั้ง CORS:

```bash
export TF_VAR_portal_origin="$PORTAL_URL"
terraform -chdir=infra/foundation plan -out=cors.tfplan
terraform -chdir=infra/foundation show -no-color cors.tfplan
terraform -chdir=infra/foundation apply cors.tfplan
curl --fail --show-error --silent --max-time 15 "$PORTAL_URL/livez"
curl --fail --show-error --silent --max-time 15 "$PORTAL_URL/healthz"
curl --silent --show-error --max-time 15 --output /dev/null --write-out '%{http_code}\n' "$WORKER_URL/livez"

```

**ReviewCORSplan:** เปลี่ยนเฉพาะ incomingCORS ให้ตรง PortalURL ไม่มี wildcard ไม่มีผลกับ resultsbucket/Secret/IAM ถ้ามี diff อื่นต้องเข้าใจก่อน apply **Expected:** Portal/livez200 และ/healthzready; anonymous worker ต้องถูก platform ปฏิเสธ(โดยทั่วไป 403) หากได้ 200 ให้หยุดตรวจ IAM/inheritedgrants ก่อนทดสอบไฟล์ CORS ไม่ได้ทำให้ bucketpublic และไม่ใช่ authentication

| อาการ | จุดเริ่มตรวจ |
|---|---|
| Portalrevision ไม่ ready | AUTH_FILE/mount/numericversion/SecretAccessor, startupJSON และ error ที่ปลอดภัย ไม่พิมพ์ Secret |
| livez200 แต่ healthz503 | namedFirestore/condition/runtimeSA/metadataread ไม่เพิ่ม Editor เพื่อข้าม |
| upload ถูก BrowserCORSblock | exactPortalorigin/POSTpolicyendpoint และ CORSpropagation ไม่ตั้ง wildcard/ปิด Browsersecurity |
| Workeranonymous200 | serviceIAM/inheritedrun.invoker ต้องแก้ก่อนทำ Lab ต่อ |
| Trigger ไม่ส่งงาน | filterbucket/location, Storageagentpublisher, triggerSAeventReceiver/workerinvoker และ operation ไม่ใช้ manualHTTP แทนแล้วอ้าง Eventarc ผ่าน |

**จุดบันทึก T04:** image/Secretversion/revisionIDs …; Portal/workerSA …; workerIAM/anonymousstatus …; triggerregion/filter/destination/status …; CORSdiff/origin …; livez-healthz ผล …; error/แก้/retest …  
**เกณฑ์ไปต่อ:** Portal พร้อม, worker ไม่ anonymous, trigger ตรงแบบและ CORS เฉพาะ origin ตอนนี้ยังไม่ถือว่า businessflow หรือ GCSsignedpermission ผ่าน ต้องพิสูจน์ด้วยไฟล์จริงใน Tasks ถัดไป

### Task 5 — อัปโหลด CSV และพิสูจน์รายงานจากไฟล์จริง

**ทำที่ไหน:** Browser ที่ PORTAL_URL ของคุณ และ Cloud Shell สำหรับเทียบผล ไม่ใช้ภาพหรือผล CI เป็น Actual ของ GCP

1. ใน Cloud Shell Editor เปิดโฟลเดอร์ fixtures แล้วดาวน์โหลด valid-sales.csv แบบไฟล์เดิม ไม่คัดลอกผ่านโปรแกรมตารางที่อาจเปลี่ยน encoding/ราคา/lineendings ไฟล์นี้มี 3 รายการ/6 หน่วย/ยอดรวม 72,400 สตางค์
2. เปิด private file secrets/demo-logins.json ใน Cloud Shell Editor อ่านรหัส alice แล้วปิดไฟล์ ห้ามพิมพ์ทั้งไฟล์ลง terminal/ถ่ายภาพรหัส
3. Browser เปิด Portal login alice เลือก valid-sales.csv กด “ส่งไฟล์ / ทำคำขอเดิมต่อ” หนึ่งครั้ง จด jobUUID ที่รายการงาน
4. ตรวจสถานะ awaiting_upload/processing/succeeded ตามที่เห็นจริง งานเล็กอาจจบเร็วจนไม่เห็นสถานะกลาง ไม่แต่ง timeline ให้ครบทุกสถานะ หาก poll ครบ 30 รอบให้กดรายละเอียด/โหลดรายการใหม่ ไม่ถือว่าครบ poll แล้ว worker ต้อง failed
5. เมื่อ succeeded กดดาวน์โหลด JSON ของงานนี้ ข้อมูลรายงานต้องมี rows3/units6/total_satang72400, BOOK-01 จำนวน 5 ยอด 62500 และ USB-01 จำนวน 1 ยอด 9900 พร้อม input_sha256 กับ processor_versionv1
6. ไม่เปิดหรือแชร์ signedURL ให้คนอื่น ผู้ที่ได้ลิงก์อาจใช้ได้จนหมดอายุ การ logout ไม่เพิกถอนลิงก์ที่ออกไปแล้ว
7. นำไฟล์ summary.json ที่ดาวน์โหลดจริงขึ้น CloudShell ผ่านเมนู Upload file ไปยังพื้นที่ส่วนตัว แล้วใช้คำสั่งตรวจด้านล่าง โดยใส่ path ของไฟล์จริง อย่าใช้ fixtures/valid-sales.expected.json แทนไฟล์ดาวน์โหลด

```bash
cd "$LAB_DIR"
sha256sum fixtures/valid-sales.csv
.venv/bin/python scripts/verify-report.py --source fixtures/valid-sales.csv --report 'ใส่-path-summary.json-ที่ดาวน์โหลดจริง' --processor-version v1

```

**Expected:** eventreport_matches_fixture, rows3/units6/total_satang72400 และ SHA ตรง bytes ต้นฉบับ เครื่องมือนี้ตรวจทุก field กับ canonicaldomainresult อ่านแบบ bounded และปฏิเสธ duplicateJSONkeys/NaN/ผลผิด ไม่ติดต่อ GCP หรือพิมพ์ credentials ถ้าไม่ตรงให้เก็บไฟล์/UUID/sourcecommit/เวลาและตรวจ inputgeneration/workerimage ก่อน ไม่แก้รายงานให้ตัวเลขผ่าน

Cloud Shell → Console → Firestore → lab006-files → jobs → UUID นี้ ตรวจ state/input_generation/input_sha256/output_generation/output_sha256 สัมพันธ์กับไฟล์ที่สร้างจริง และ Storage → incoming/results ตรวจชื่อ object ตาม job/generation/processorversion ไม่ใช้จำนวน eventIDs แทนจำนวน logicalresults

**เมื่อ response หาย:** UI เก็บ key/ชื่อไฟล์/SHA ก่อน create และเก็บ jobID เมื่อได้รับคำตอบ หากค้างให้เลือกไฟล์เดิมแล้วกดทำคำขอเดิมต่อ ไม่ล้าง sessionStorage หรือสร้าง key ใหม่เพื่อหลบ error ตรวจ job/list/Storage ก่อนสรุปว่าการอัปโหลดไม่สำเร็จ หาก Storage ตอบ duplicateobject ในช่วงรอ event ให้ตรวจงานเดิมต่อ ไม่ลบ incoming แล้วอัปโหลดทับ

**ถ้าไม่สำเร็จ**

| อาการ | เริ่มตรวจ |
|---|---|
| awaiting_upload ค้าง | BrowserStorageHTTP/CORS, policyexpiry/key/MIME/size และ object มีจริงหรือไม่ |
| object มีแต่ job ยังรอ | Eventarctrigger/filter/transport/workerIAM และ logs ไม่สร้าง job ใหม่ |
| processing ค้าง | lease/attempt/history, workerdependencyerror, generation ที่อ่าน และ expiry |
| rejected | safe_reason/fixturebytes ไม่ใช่แก้ IAM เพื่อให้ CSV ผิดผ่าน |
| failed_integrity | output เดิมผิด bytes/metadata ให้หยุดตรวจ ไม่ overwrite หรือ operatorretry กลบ |
| succeeded แต่ download ไม่ได้ | owner/expiry/downloadsignergetresults/signBlob ไม่เปิด bucketpublic |

**จุดบันทึก T05**

| จุดตรวจ | Expected | Actual / หลักฐานของคุณ |
|---|---|---|
| Sourcefixture/SHA | ไฟล์เดิมจาก commit ที่บันทึก | … |
| jobUUID/owner | alice/งานเดียวตาม logicalrequest | … |
| StorageHTTP/status ที่เห็น | ส่งสำเร็จแล้วประมวลผล ไม่เดาสถานะที่ไม่เห็น | … |
| รายงานที่ดาวน์โหลด | 3rows/6units/72400satang/SHA ตรง | … |
| input/outputgenerations/workerrevision | เชื่อมกับ job และ report ได้ | … |
| response ขาดหายถ้ามี | key เดิม/วิธี resolve/ผลแน่นอน | … |

**เกณฑ์ไปต่อ:** แยกได้ว่าระบบรับไฟล์ ประมวลผล และคืนรายงานถูกต้องจากหลักฐานจริง ไม่ใช่เพียง status ชื่อ succeeded หรือหน้าเว็บเปิดได้

### Task 6 — ทดสอบไฟล์ผิดเงื่อนไขและสิทธิ์ข้ามบัญชี

**ก่อนเริ่ม:** T05 ปกติ, budget/จำนวนงานยังอยู่ในเพดาน ใช้ข้อมูลสังเคราะห์ ไม่มี writer อื่นกดทดสอบพร้อมกัน แต่ละ fixture ที่ผิดคือ logical job ใหม่ที่ตั้งใจสร้าง ไม่ใช้การเปลี่ยนไฟล์ใน pending request เดิมเพื่อเลี่ยง fingerprint guard

#### Validation ที่ worker ต้องตรวจ

ใช้ fixtures/duplicate-sale-id.csv, fixtures/invalid-header.csv และ fixtures/invalid-quantity.csv จาก checkout เดียวกัน ส่วนไฟล์ UTF-8 เสียให้สร้างใน Cloud Shell โดยไม่แก้หรือบันทึกใหม่ผ่าน text editor เพราะ editor อาจซ่อม encoding ให้เอง:

```bash
cd "$LAB_DIR"
mkdir -p .build
.venv/bin/python scripts/create-change-fixtures.py --out .build/validation-fixtures --validation-only

```

เครื่องมือสร้างโฟลเดอร์ใหม่ส่วนตัวและไม่เขียนทับ หากมีอยู่แล้วให้ตรวจ manifest/ไฟล์ของรอบเดิมก่อน ไม่ลบทิ้งเพื่อให้คำสั่งผ่าน ดาวน์โหลด invalid-utf8.csv จาก .build/validation-fixtures โดยตรง แล้วใช้ alice ส่งแต่ละ fixture เป็นงานใหม่ รอผลแน่นอนก่อนเริ่มไฟล์ถัดไป:

| Fixture | Expected / สิ่งที่ต้องพิสูจน์ |
|---|---|
| duplicate-sale-id.csv | rejected/duplicate_sale_id ไม่มี published output ของ job นี้ |
| invalid-header.csv | rejected/invalid_header ไม่มี published output |
| invalid-quantity.csv | rejected/integer_out_of_range ไม่มี published output |
| invalid-utf8.csv จากตัวสร้าง | rejected/invalid_utf8 ไม่มี published output ไม่ใช่ header error |
| ไฟล์เกิน baseline1MiB | UI ปฏิเสธก่อน create/upload; นี่พิสูจน์เฉพาะ Browser guard ไม่ใช่ GCS policy enforcement |

ตรวจ Firestore job state/safe_reason และ Storage prefix ของ UUID แต่ละตัวด้วยสิทธิ์ผู้ดูแล การที่ job ไม่มีปุ่ม download ยังไม่พิสูจน์ว่าไม่มี output object ต้องตรวจทั้ง metadata กับ Storage ส่วน invalid CSV อาจถูกเก็บใน incoming จน lifecycle cleanup ไม่อ้างว่า rejected หมายถึงลบไฟล์ต้นฉบับทันที

Validation failure ต้อง ack เป็น terminal ไม่วน attempt ขึ้นเรื่อย ๆ เก็บ history สองจุดเวลาที่ห่างกันอย่างเหมาะสมและดู worker logs หาก attempt เพิ่มไม่จบให้หยุด fault/retry และแก้การแยก terminal/transient ไม่เพิ่ม retry budget เพื่อให้ดูสำเร็จ

การตรวจ oversized ที่ Storage จริงและ MIME ปลอมต้องทำผ่าน signed request ที่เปลี่ยนข้อมูลโดยตั้งใจและยังไม่เผย policy/token ใน log ใช้ bounded tool ใน Task 7 ไม่ใช้ผล UI guard แทนการพิสูจน์ R3 ทั้งหมด

#### Owner/role และ CSRF แยกจาก Cloud IAM

เปิด Browser profile หรือ private window อีกชุด login bob ใส่ alice job UUID จาก T05 ในตัวอย่างด้านล่าง เปิด DevTools → Console บน Portal origin ของคุณ คำสั่งนี้พิมพ์เฉพาะ HTTP status ไม่พิมพ์ cookie/CSRF/response ที่มี signedURL:

```javascript
const aliceJob = 'ใส่-jobUUID-ของ-alice';
const sessionInfo = await fetch('/api/session', {cache:'no-store'}).then(r => r.json());
const statusReply = await fetch('/api/jobs/' + aliceJob, {cache:'no-store'});
const linkReply = await fetch('/api/jobs/' + aliceJob + '/download-link', {
  method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':sessionInfo.csrf},
  body:'{}'
});
const operatorReply = await fetch('/api/operator/jobs', {cache:'no-store'});
console.log({otherOwnerStatus:statusReply.status, otherOwnerLink:linkReply.status, operatorList:operatorReply.status});

```

**Expected:** bob ได้ 404/404/403 แม้รู้ UUID ไม่เห็นไฟล์หรือออก link แทน alice ได้ รายการ bob ไม่รวม alice อย่า copy ทั้ง linkReply body หรือ HAR เป็นหลักฐาน

ในหน้าที่ login alice อยู่ ตรวจ mutation ที่ไม่มี CSRF โดยไม่ส่ง token:

```javascript
const csrfDenied = await fetch('/api/jobs/' + 'ใส่-jobUUID-ของ-alice' + '/download-link', {
  method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'
});
console.log({missingCsrf:csrfDenied.status});

```

**Expected:**403 ไม่ปิด CSRF เพื่อให้คำสั่งผ่าน จากนั้นใน profile ที่ยังไม่ login เปิด/api/jobs ต้อง 401 ส่วน login operator ต้องเห็นรายการ/รายละเอียด safe history ได้ แต่ไม่ได้สิทธิ์ download ของ alice โดยอัตโนมัติ หากเรียก download-link ของ alice ใน session operator พร้อม CSRF ที่ถูกต้องต้อง 404 เหมือน non-owner

ลองรหัสผิดเพียงครั้งเดียวต้อง login ไม่สำเร็จ ไม่ยิง bruteforce หรือโหลด login endpoint เพื่อวัด performance และไม่ใช้ App role แทน Cloud Run IAM: anonymous worker ต้องถูก platform ปฏิเสธตาม T04 แยกอีกหลักฐาน

**จุดบันทึก T06:** UUID/fixture/rejected reason/output prefix แต่ละกรณี …; history ก่อน/หลัง …; bob status/link/operator list …; anonymous401 …; missingCSRF403 …; operator อ่าน metadata ได้แต่ไม่ download …; ข้อจำกัด เช่นยังไม่ทดสอบ Storage-level size/MIME …  
**เกณฑ์ไปต่อ:** ผล negative เชื่อมกับ identity/เวลา/UUID ได้ ไม่มีข้อมูลหรือ capability รั่ว และระบุส่วนที่ยังไม่ได้พิสูจน์ตามจริง ไม่ติ๊ก R2/R3 ครบจาก test ใด test หนึ่ง


### Task 7 — ทดสอบ signed POST ที่ Storage โดยไม่พึ่ง UI guard

**ทำที่ไหน:** Cloud Shell ที่ LAB_DIR หลัง T05–06 ปกติ เครื่องมือนี้สร้างงานและส่ง HTTP จริง มีค่า operations/metadata ตามบัญชีคุณ ใช้เฉพาะ sandbox/Portal ของ Lab ไม่ส่งไปบริการทีมอื่น

ก่อนเริ่มตรวจ activejobs ของ alice ยังไม่ถึง 5 และ dailyquota ยังไม่ถึง 20 งาน negative ที่ Storage ไม่รับอาจยังอยู่ awaiting_upload และนับ active อยู่ ไม่ลบ metadata ด้วยมือเพื่อหลบ quota เก็บ UUID ไว้ตรวจ/cleanup ท้าย Lab

```bash
cd "$LAB_DIR"
.venv/bin/python scripts/test-upload-boundary.py --base-url "$PORTAL_URL" --logins-file secrets/demo-logins.json --journal secrets/boundary-positive.json --bucket "$INCOMING_BUCKET" --case positive
.venv/bin/python scripts/test-upload-boundary.py --base-url "$PORTAL_URL" --logins-file secrets/demo-logins.json --journal secrets/boundary-oversize.json --bucket "$INCOMING_BUCKET" --case oversize
.venv/bin/python scripts/test-upload-boundary.py --base-url "$PORTAL_URL" --logins-file secrets/demo-logins.json --journal secrets/boundary-mime.json --bucket "$INCOMING_BUCKET" --case mime

```

รันทีละบรรทัดและอ่านผลก่อนต่อ ใช้ journal คนละไฟล์ตาม case ไม่รันสอง process กับ journal เดียวกัน เครื่องมือเก็บ key ก่อน create/เก็บ jobID ก่อนขอ policy อ่านรหัสจาก privatefile ไม่พิมพ์ password/cookie/CSRF/policy/signature และไม่ตาม redirect

| Case | สิ่งที่ส่ง | สิ่งที่ต้องตรวจ |
|---|---|---|
| positive | CSV เล็กตาม contract/MIME ตรง | Storage201 และ job นี้ประมวลผลได้ เป็น positivecontrol ของ signer/policy ทางเข้า |
| oversize | bytes มากกว่า signedmax1byte แต่ MIME เดิม | Storage ปฏิเสธเพราะเงื่อนไขขนาด พร้อม errorcode/เหตุผลที่ตรง และไม่มี incomingobject ของ UUID นี้ |
| mime | ขนาดเล็กแต่ Content-Type เปลี่ยนเป็น application/octet-stream | Storage ปฏิเสธเงื่อนไข MIME/ลายเซ็น policy พร้อมไม่มี object ของ UUID นี้ |

ผลอาจเป็น 400 หรือ 403 ตามสาเหตุ เครื่องมือรายงาน status/errorcode ที่อ่านได้เท่านั้น **exit0 หมายถึงเก็บ observation ได้ ไม่ใช่ PASS** หาก positivecontrol ล้มให้หยุดแก้ signBlob/Storagepermissions/expiry ก่อนตีความ negative403 อย่าใช้ AccessDenied ทั่วไปเพียงอย่างเดียวพิสูจน์ size/MIME หาก negative กลับ 201 ให้ถือว่า acceptance ไม่ผ่าน เก็บ UUID และตรวจงานที่อาจถูกสร้าง ไม่ลบผลแล้วทดลองซ้ำจนดูผ่าน

ใช้ Console → Storage → incomingbucket → ค้น prefix incoming/UUID/source.csv ของแต่ละ job ตรวจว่างาน positive มี object ส่วน negative ไม่มี ตรวจ Firestorestatus กับ event/log เวลาเดียวกันประกอบ การที่ workerreject ภายหลังไม่ใช่หลักฐานว่า Storagepolicy ปฏิเสธตั้งแต่ทางเข้า

ถ้า timeout/response หาย เครื่องมือออก boundary_unresolved และเก็บ journal เดิม ตรวจ Portaljob กับ Storage ก่อนรันคำสั่งเดิม ห้ามใช้ journal ใหม่เพื่อเลี่ยงผลไม่แน่นอน หากมี terminalresult แล้วรันซ้ำจะได้ stored_result_not_retest โดยไม่ยิง network **ไม่ใช่การ retest** ทดลองใหม่ด้วย journal ใหม่ได้เมื่อ resolve และบันทึกรอบเดิมแล้วเท่านั้น

**จุดบันทึก T07:** positiveUUID/status/processing ผล …; oversizeUUID/status/errorcode/objectabsence …; mimeUUID/status/errorcode/objectabsence …; policyversion/workerrevision/เวลา …; ข้อจำกัดหรือสาเหตุที่ยังสรุปไม่ได้ …; journals ที่ต้องเก็บ private/งานค้าง …  
**เกณฑ์ไปต่อ:** positivecontrol สำเร็จและ negative มีหลักฐานตรงเงื่อนไขจริง แยก Storage-levelrejection จาก Browser guard และ workerCSVvalidation ไม่แชร์ policy หรือ signedURL ลงหลักฐาน

### Task 8 — กู้ช่องว่าง “เขียนรายงานแล้วแต่ยังไม่บันทึก success”

**ขอบเขต:** fault สังเคราะห์ใน worker เฉพาะ sandbox นี้ ไม่ใช่การทำให้ GCS/Firestore ล่มทั้งบริการ ต้องไม่มีผู้ใช้อื่น upload ระหว่างทดลอง และต้องมี baselineT05–07 ที่ตรวจแล้ว

**ทำที่ไหน:** Cloud Shell ใช้ variables/state/image/authversion เดิมจาก T04 เปลี่ยนเฉพาะ workerfaultconfig:

```bash
cd "$LAB_DIR"
export TF_VAR_worker_fail_before_read=false
export TF_VAR_worker_fail_after_output_once=true
terraform -chdir=infra/workloads plan -out=worker-output-gap.tfplan
terraform -chdir=infra/workloads show -no-color worker-output-gap.tfplan
terraform -chdir=infra/workloads apply worker-output-gap.tfplan
gcloud run services describe lab006-worker --region="$REGION" --format='yaml(status.conditions,status.latestReadyRevisionName,status.traffic)'

```

Reviewplan ต้องเปลี่ยนเฉพาะ workerrevision/env ไม่เปลี่ยน image/Secret/Portal/Firestore/IAM ถ้ามี diff อื่นหยุดตรวจ รอ readyrevision/traffic ชัดเจนก่อนส่งไฟล์ใหม่หนึ่งงานจาก alice ใช้ valid-sales.csv ผ่าน Browser ตาม T05 ถ้า UI มี pending request เดิมให้ resolve ก่อน ไม่เปลี่ยนไฟล์หรือ key เพื่อเริ่ม fault

**Expected:** workerclaim → เขียน outputcreate-only → บันทึก durablefaultmarker → ตอบ 503 → Eventarc ส่งใหม่ → verify/reuseoutput เดิม → fencedsuccess ไม่รับประกันว่า Browser จะเห็นช่องว่างก่อน retry จบ เพราะอาจเกิดเร็ว ต้องใช้ logs/history/Storagegeneration เป็นหลักฐาน

จด jobUUID แล้วตรวจ logs แบบไม่พิมพ์ payload:

```bash
export JOB_ID='ใส่-jobUUID-ของการทดลองนี้'
gcloud logging read "resource.type=\"cloud_run_revision\" AND resource.labels.service_name=\"lab006-worker\" AND jsonPayload.job_id=\"$JOB_ID\"" --project="$PROJECT_ID" --freshness=30m --limit=30 --format='table(timestamp,resource.labels.revision_name,jsonPayload.request_id,jsonPayload.event_id,jsonPayload.status,jsonPayload.result_reason)'
gcloud storage ls --long "gs://$RESULTS_BUCKET/results/$JOB_ID/**"

```

Console → Firestore → lab006-files/jobs/UUID ดู output_fault_consumed=true, input_generation เดิม, history/attempts และ output_generation จากนั้น Storage ดู generation ของ summaryobject และเทียบ report ตาม T05 ควรมี logicaloutput เดียว ไม่ใช้ eventIDs ที่ต่างกันตีความว่าเป็นคนละ businessjob

หากไม่พบ intentional_after_output ใน logs แต่มี succeeded ไม่อ้างว่า fault เกิดแล้ว ตรวจ readyrevision/env/งานที่ใช้ให้ตรง หากพบ 503 แต่ไม่ recover ให้ตรวจ Eventarc/metadata/Storagepermissions และ lease ก่อน ไม่ลบ output เพื่อให้ retry เขียนใหม่ หากมี failed_integrity ให้หยุดตรวจ bytes/metadata ห้าม overwrite

จำกัดช่วงสังเกตรอบแรก 10 นาที ถ้ายังไม่จบให้บันทึกอาการ/ช่วงเวลาที่เห็น แล้วปิด fault ก่อนหาสาเหตุต่อ ไม่ทิ้ง faultrevision ค้างไว้:

```bash
export TF_VAR_worker_fail_after_output_once=false
terraform -chdir=infra/workloads plan -out=worker-output-gap-backout.tfplan
terraform -chdir=infra/workloads show -no-color worker-output-gap-backout.tfplan
terraform -chdir=infra/workloads apply worker-output-gap-backout.tfplan

```

หลังคืน baseline ส่ง validfixture เป็นงานใหม่ที่ตั้งใจสร้าง ตรวจ succeeded/report/flagsfalse ถ้างาน fault เดิมยังไม่แน่นอนต้องเก็บ UUID/resolve ต่อ อย่าสรุปว่า backout หมายถึงงานค้างสำเร็จแล้ว

**จุดบันทึก T08:** before/fault/backoutrevision …; UUID/inputgeneration …; first503/retry/success เวลา …; faultmarker …; outputgeneration/จำนวน logicaloutputs …; reportverification …; backout/retest …; ข้อจำกัดที่สังเกตไม่ทัน …  
**เกณฑ์ไปต่อ:** ผลเดียวเชื่อมกับ generation เดิมและผลตรวจจริง หรือบันทึก failure ที่ต้องแก้ก่อนต่อ ไม่อ้าง exactly-oncedelivery/zeroerror จาก recovery นี้

### Task 8B — ส่ง event ซ้ำและตรวจว่าผลไม่เปลี่ยน

**ทำหลัง T08 กลับสู่ baseline:** ใช้งานที่ succeeded แล้วและยังไม่หมดอายุ จด input generation, output generation/hash, owner และ attempt history ก่อนเริ่ม เป้าหมายคือเปรียบเทียบงานเดิม ไม่สร้างไฟล์หรือ job ใหม่

เครื่องมือ [replay-storage-event.py](scripts/replay-storage-event.py) อ่าน metadata ของ incoming generation จริงก่อนประกอบ event ไม่รับ timestamp ที่เดาเอง ส่งไม่เกินสามครั้ง: event ID เดิมสองครั้ง แล้วเปลี่ยน event ID โดยคง bucket/name/generation เดิม ทุกคำขอเรียก worker ด้วย ID token ที่ audience ตรง URL และไม่ตาม redirect

**สิทธิ์เพิ่มเติมเฉพาะการทดสอบ:** บัญชีผู้เรียนต้องอ่าน incoming object generation ได้ และ impersonate trigger service account ของ Lab ได้ ไม่ใช่การเปิด worker ให้ anonymous หรือให้ Token Creator ทั้ง project หากยังไม่มีสิทธิ์ ให้ผู้ดูแล sandbox ตรวจตามขั้นนี้ก่อน:

1. Console → IAM & Admin → Service Accounts → เลือกอีเมล trigger ที่ได้จาก output ด้านล่าง → Permissions
2. บันทึก policy เดิมและตรวจว่าบัญชีผู้เรียนได้รับสิทธิ์ impersonation อยู่แล้วหรือไม่ อย่าเพิ่มซ้ำหรือใช้บัญชีคนอื่น
3. หากต้องเพิ่ม ให้ Grant access บน service account นี้เท่านั้น เลือก principal เป็นบัญชีผู้เรียน และ role **Service Account Token Creator** ใช้ condition วันหมดอายุที่ครอบคลุมช่วงทดสอบสั้น ๆ ตามนโยบาย sandbox
4. Role นี้ให้สิทธิ์มากกว่าการขอ ID token อย่างเดียว จึงใช้เฉพาะ trigger SA ของ Lab ไม่ใช้กับ signer/Portal/production SA และไม่สร้าง private key จด binding/condition ที่เพิ่มเพื่อลบเฉพาะรายการนี้หลังจบ หากองค์กรไม่อนุญาต ให้บันทึก T08B ว่า Not run และขอแนวทางผู้ดูแล ไม่ขยายสิทธิ์เอง

อ้างอิง [CLI ID token และ audience](https://docs.cloud.google.com/sdk/gcloud/reference/auth/print-identity-token) และ [ขอบเขต role สำหรับ impersonation](https://docs.cloud.google.com/iam/docs/service-account-permissions)

**ทำที่ไหน:** Cloud Shell ใน LAB_DIR ใช้ project/region/state/venv เดิม:

```bash
cd "$LAB_DIR"
export TRIGGER_SA="$(terraform -chdir=infra/foundation output -json service_accounts | python3 -c 'import json,sys; print(json.load(sys.stdin)["trigger"])')"
export JOB_ID='ใส่-jobUUID-ที่-succeeded-และยังไม่หมดอายุ'
export INPUT_GENERATION='ใส่-input_generation-จากงานเดียวกัน'
.venv/bin/python scripts/replay-storage-event.py --project "$PROJECT_ID" --bucket "$INCOMING_BUCKET" --job-id "$JOB_ID" --generation "$INPUT_GENERATION" --worker-origin "$WORKER_URL" --service-account "$TRIGGER_SA" --confirm-sandbox

```

เครื่องมือใช้ Application Default Credentials ของ Cloud Shell อ่าน Storage และใช้ gcloud account ปัจจุบันขอ ID token หากอ่าน metadata ไม่ได้ ให้ตรวจ account/project/ADC และสิทธิ์อ่าน generation ก่อน ไม่ export token ลงไฟล์หรือใส่ key ลง repository หากสภาพแวดล้อมยังไม่มี ADC ให้ทำ gcloud auth application-default login ตามนโยบายของ sandbox แล้วรันคำสั่งเดิม ไม่ใช้ service account key แทน

**Expected ของ transport:** JSON แสดงสามคำขอที่ HTTP 204 และ business_verification เป็น required_separately ข้อนี้หมายถึง worker รับและตอบคำขอ ไม่ใช่ PASS ของ business requirement เครื่องมือไม่อ่านหรือพิมพ์ token/response body และหยุดเมื่อ HTTP ไม่ใช่ 204 หรือผลไม่แน่นอน

**ตรวจผลธุรกิจต่อ:** เปิดงานเดิมใน Portal/Firestore ตรวจ owner, input generation, output generation และ hash ต้องไม่เปลี่ยน ดาวน์โหลด report ใหม่แล้วเทียบตาม T05 ตรวจ Storage ว่าไม่มี logical result เพิ่ม และดู worker logs ตาม T08 ว่ามี event ID เดิม/ใหม่ตรงกับสามคำขอ Terminal duplicate ไม่ควรเพิ่ม attempt เพื่อทำงานซ้ำ ถ้าเห็น 204 แต่หา job ไม่พบหรือ output ไม่ตรง ห้ามนับผ่าน

ถ้า 401/403 ให้ตรวจ audience, trigger SA invoker และสิทธิ์ impersonation ไม่ให้ allUsers เพื่อแก้ ถ้า 400 ให้ตรวจ event contract/source/bucket/namespace ถ้า 503 หรือ unknown ให้ตรวจ logs/สถานะ/generation ก่อนตัดสินใจรอบใหม่ ไม่วนยิงเพื่อให้ได้ 204

การส่งตรงนี้พิสูจน์ receiver และ business deduplication ไม่ใช่หลักฐานว่า Eventarc เป็นผู้ส่ง retry จริง ใช้ T08 ร่วมกับ Eventarc logs แยกหลักฐาน ส่วน concurrent claim/lease fencing ใช้ผล emulator tests ประกอบ ไม่อ้างจากสามคำขอเรียงลำดับว่าได้พิสูจน์ race บน GCP

หลังจบกลับไป Permissions ของ trigger SA ลบเฉพาะ binding/condition ที่เพิ่มสำหรับ T08B อย่าลบสิทธิ์เดิมหรือ run.invoker ของระบบ ตรวจ policy เทียบก่อนทำ Token ที่ออกไปแล้วอาจยังใช้ได้จนหมดอายุ จึงอย่าเผยแพร่และอย่าอ้างว่าลบ role แล้วเพิกถอนทุก token ทันที

**จุดบันทึก T08B:** UUID …; owner/input/output generation/hash ก่อน–หลัง …; event IDs/HTTP …; จำนวน logical results …; report verification …; IAM binding ก่อน/เพิ่ม/คืน …; เวลาและข้อจำกัด …  
**เกณฑ์ไปต่อ:** แยก transport acknowledgement จากผลธุรกิจได้ และมีหลักฐานว่าคำขอซ้ำไม่สร้างผลเพิ่ม หากไม่รันจริงให้ระบุ Not run

### Task 9 — งานล้มเหลวครบ budget และ operator retry ไฟล์เดิม

ทำเมื่อ T08 คืนปกติ ไม่มี unresolved งานที่ปะปน ใช้ fault ก่อนอ่านไฟล์เพื่อจำลอง dependencyfailure ซ้ำ ไม่ถอน IAM ของ project หรือเปิด workerpublic

```bash
export TF_VAR_worker_fail_after_output_once=false
export TF_VAR_worker_fail_before_read=true
terraform -chdir=infra/workloads plan -out=worker-pre-read-fault.tfplan
terraform -chdir=infra/workloads show -no-color worker-pre-read-fault.tfplan
terraform -chdir=infra/workloads apply worker-pre-read-fault.tfplan

```

รอ workerrevision พร้อม แล้ว alice ส่ง validfixture ใหม่หนึ่ง job จด UUID ดู operatorprofile → รายการ/รายละเอียด และ logs ตาม T08 ควรเห็น intentional_before_read/503 แล้ว attemptcount เพิ่มไม่เกิน 5 ต่อ epoch การส่งครั้งถัดไปเมื่อ budget ครบทำให้ failed/retry_budget และ ack แทนวนไม่จบ ยังไม่มี output จากการอ่านไฟล์รอบนี้

Eventarcretry อาจหน่วงและเวลาไม่คงที่ สังเกตเป็นช่วงไม่เกิน 10 นาทีก่อนตัดสินใจ ไม่สร้าง job เพิ่มเพื่อเร่งให้ครบ budget ถ้าไม่ถึง failed ใน window นี้ให้บันทึกว่า scenario ยังไม่ครบ ปิด fault และตรวจ delivery/backoff ต่อ ห้ามแก้ Firestorecount/state ด้วยมือให้ดูผ่าน

**ก่อนกด operatorretry ต้องปิด fault และรอ readyrevision ใหม่ก่อน:**

```bash
export TF_VAR_worker_fail_before_read=false
terraform -chdir=infra/workloads plan -out=worker-pre-read-backout.tfplan
terraform -chdir=infra/workloads show -no-color worker-pre-read-backout.tfplan
terraform -chdir=infra/workloads apply worker-pre-read-backout.tfplan
gcloud run services describe lab006-worker --region="$REGION" --format='yaml(status.conditions,status.latestReadyRevisionName,status.traffic)'

```

ใน operatorprofile เปิด job ที่ failed/retry_budget กด “Retry คำขอเดิม” หนึ่งครั้ง Portal ต้อง prepareepoch1 ก่อน dispatch Worker อ่าน inputgeneration/finalizedtime จาก job ไม่รับ path ใหม่จาก Browser สถานะ HTTP202/dispatchacknowledged ไม่ใช่ businesssuccess ต้องอ่าน job ต่อจนได้ผลแน่นอน

หาก response หายหรือ dispatchunconfirmed ให้กดคำขอเดิมต่อ ไม่ล้าง sessionStorage หรือเปิด epoch ใหม่เพราะไม่แน่ใจ key เดิมต้องคืน epoch เดิม ไม่กิน manualbudget ซ้ำ หากงานล้มครบ budget อีกจริงจึงพิจารณาปุ่ม “เปิดรอบ retry ใหม่” พร้อมยืนยัน ไม่เกิน 2manualepochs ห้ามใช้ rejected/expired/failed_integrity เพื่อหลบ validation/integrityfailure

**Expected หลังแก้:** owner/inputgeneration/processorversion/limits เดิม, epoch เพิ่มหนึ่งครั้ง, summary/report ถูกต้องและ outputlogical เดียว customer เรียก operatorretry ไม่ได้ และ operator ยังไม่ได้สิทธิ์ download ไฟล์ของ alice แทนเจ้าของ

**จุดบันทึก T09:** UUID/faultrevision …; window/attempttimeline …; failedreason/budget …; faultfalse-readyrevision …; retryrequest/epoch แรกและ replay …; dispatch ผลและการ reconcile …; finalgeneration/report …; negativecustomer403 …; ข้อจำกัด/งานที่ยังไม่จบ …  
**เกณฑ์ไปต่อ:** faultflagsfalse ทั้งคู่, ไม่เหลือ unknownoutcome และอธิบายได้ว่ากู้ด้วยข้อมูลเดิมโดยไม่เพิ่มรอบซ้ำ การทดลองนี้เป็น dependencyfault สังเคราะห์ ไม่ใช่หลักฐานว่า Firestore/GCS outage จริง

### Task 10 — Change Request: เพิ่มขนาดไฟล์จาก 1 เป็น 5 MiB โดยไม่เปลี่ยนสัญญางานเก่า

**โจทย์ทีม:** ไฟล์ยอดขายเริ่มใหญ่ขึ้น ต้องรับได้ถึง 5MiB/50,000rows โดยไม่เปิด bucketpublic ไม่เพิ่ม concurrency แบบเดาสุ่ม และงานที่สร้างไว้ก่อนเปลี่ยนยังใช้ limits/version เดิม

**ก่อนเริ่ม:** faultflagsfalse ทั้งคู่, ไม่มี unknownoutcome, จด image/authversion/revision และค่า baseline ตรวจ active/dailyjobquota ก่อนจัดชุดทดลอง งานทั้ง Lab อาจใกล้ 20newjobs/UTCday ให้จดจำนวนและเว้นงานเสริม ไม่แก้ counter หรือเปลี่ยน owner เพื่อหลบ guard หากเต็มให้รอรอบ UTCday ใหม่และบันทึกไว้ ไม่เรียกผ่านว่า change ล้มเพราะ capacity ของ GCP

Cloud Shell สร้าง fixtures ใหม่โดยไม่ทับของเดิม:

```bash
cd "$LAB_DIR"
mkdir -p .build
.venv/bin/python scripts/create-change-fixtures.py --out .build/change-fixtures

```

**Expected:** manifest มี bytes/SHA ของ 6 ไฟล์ ทุกไฟล์ deterministic ไม่ใช่ข้อมูลธุรกิจจริง ถ้า directory มีอยู่แล้วให้ตรวจ manifest เดิมหรือเลือก directory ใหม่ ไม่ลบเพื่อบังคับให้ผ่าน ดาวน์โหลดไฟล์จาก CloudShellEditor ไปใช้ Browser แบบ bytes เดิม

| Fixture | Baseline1MiB/10krows | หลัง Change5MiB/50krows |
|---|---|---|
| exact-1mib.csv | succeeded10000rows/10000units/1,000,000,000,000satang | ต้องยังผ่าน |
| byte-change.csv | UI/Storage ขนาดปฏิเสธ; validCSV10000rows แต่ bytes>1MiB | ต้องผ่านโดยไม่มีการลด validation |
| row-change.csv | rejected/too_many_rows แม้ bytes<1MiB | ต้องผ่าน 10001rows |
| exact-5mib.csv | เกินขนาด baseline | ต้องผ่าน 50000rows ที่ 5MiB พอดี |
| too-many-rows.csv | ไม่ใช้เป็น baseline หลัก | rejected/too_many_rows แม้ bytes อยู่ใน 5MiB |
| too-large.csv | เกินขนาด | UI/Storage ต้องปฏิเสธ 5MiB+1byte ไม่ถือว่า UI guard แทน policytest |

เลือก baseline ที่ต้องเก็บก่อนเปลี่ยน ไม่จำเป็นต้องสร้างงานซ้ำทุกช่อง หากตัวเลขรายงานใหญ่ให้คงหน่วยสตางค์/จำนวนเต็ม ไม่แปลง float หรือใส่ percentageimprovement จาก sample เดียว

#### สร้างงานค้างหนึ่งรายการเพื่อพิสูจน์ immutable job contract

ใน Browser ที่ login alice อยู่ เปิด DevTools → Console ใช้ key เดิมถ้าคำตอบหาย คำสั่งนี้สร้าง metadatajob แต่ยังไม่อัปโหลด ไม่พิมพ์ CSRF หรือลิงก์:

```javascript
const contractSession = await fetch('/api/session', {cache:'no-store'}).then(r => r.json());
const contractKey = sessionStorage.getItem('lab006.contractKey') || 'contract-' + crypto.randomUUID();
sessionStorage.setItem('lab006.contractKey', contractKey);
const contractResponse = await fetch('/api/jobs', {
  method:'POST',
  headers:{'Content-Type':'application/json','X-CSRF-Token':contractSession.csrf,'Idempotency-Key':contractKey},
  body:JSON.stringify({display_name:'prechange-contract.csv'})
});
const contractResult = await contractResponse.json();
console.log({status:contractResponse.status, job_id:contractResult.job_id, replayed:contractResult.replayed});

```

จด UUID และรายละเอียด max_bytes1048576/max_rows10000/processor_versionv1 ไว้ หลังเปลี่ยนตรวจ UUID เดิมอีกครั้งต้องยังคงค่าเดิม หาก uploaddeadline ของงานค้างหมดแล้วไม่แก้ deadline ใน DB หรือขอ policy ใหม่ให้ผ่าน ใช้ metadata พิสูจน์ contract เดิมและระบุว่าไม่ได้ทดสอบ upload ของงานนั้น

#### วิเคราะห์และเปลี่ยนเฉพาะ admission contract สำหรับงานใหม่

ก่อน apply จดทางเลือก เช่นแบ่งไฟล์ฝั่งผู้ส่ง, เพิ่ม limits แบบ bounded หรือทำ stream/batchprocessor แยก เป้าหมายรอบนี้เลือกเพิ่ม limits โดยยัง workermax2/concurrency1/memory512MiB/60s เดิม ต้องวัดจริงว่าพอหรือไม่ ไม่อ้างว่าตารางไฟล์แปลว่า memory/RTO รับประกันแล้ว

```bash
export TF_VAR_worker_fail_before_read=false
export TF_VAR_worker_fail_after_output_once=false
export TF_VAR_upload_limit_mode='large'
terraform -chdir=infra/workloads plan -out=large-upload.tfplan
terraform -chdir=infra/workloads show -no-color large-upload.tfplan
terraform -chdir=infra/workloads apply large-upload.tfplan
gcloud run services describe lab006-portal --region="$REGION" --format='yaml(status.conditions,status.latestReadyRevisionName,status.traffic)'

```

**Review:** เปลี่ยน Portalrevision/envUPLOAD_LIMIT_MODE เท่านั้น ไม่เปลี่ยน worker/image/Secret/IAM/Firestoreschema หรือ limits ของ documents เดิม รอ readyrevision และ logout/login หรือ refreshPortal เพื่ออ่าน sessionlimits ใหม่ UI ต้องแสดง 5MiB งานใหม่ต้องมี max_bytes5242880/max_rows50000 ตรวจ immutablejob จากก่อนหน้าแยก อย่าใช้ตัวเลข UI อย่างเดียวพิสูจน์ metadata

ส่ง fixtures ที่เลือกทีละไฟล์ ดู/ดาวน์โหลดรายงานและใช้ verify-report.py กับ sourcefile นั้นตาม T05 สำหรับ exact5MiB ให้ใช้ .build/change-fixtures/exact-5mib.csv เป็น source ไม่ใช้ valid-sales.csv แทน จดเวลา upload/finalized/firstprocessing/success และ workerCPU/memory/requestlatency จาก CloudRunMonitoring ในช่วงเดียวกัน ถ้าไม่มีสิทธิ์ metric ให้ระบุข้อจำกัด ไม่ใช้ wallclockBrowser แทน processorCPU

ทดสอบ Storagepolicy ขนาดใหม่ด้วย boundaryrunner จาก T07 แต่ใช้ journal ชื่อใหม่ของ large เช่น secrets/large-oversize.json และ caseoversize เพื่อให้เครื่องมืออ่าน max จาก policy ใหม่แล้วส่งเกิน 1byte ตรวจ positivecontrol และ objectabsence เช่นเดิม ผล stored ของรอบ baseline ไม่ใช่ retest หลัง change

**ถ้าขนาดใหญ่ timeout/OOM/ผลผิด:** เก็บ UUID/generation/metrics/attempthistory ปิดการรับงานใหม่ที่เกิน baseline โดย backout ด้านล่างก่อน ไม่เพิ่ม memory/concurrency จนผ่านโดยไม่ทบทวน plan งาน large ที่สร้างไปแล้วมี contract เดิมจึงยังต้อง reconcile/resolve ไม่หายไปเพราะลดค่า Portal

#### Backout และยืนยันขอบเขตงานเดิม

```bash
export TF_VAR_upload_limit_mode='baseline'
terraform -chdir=infra/workloads plan -out=large-upload-backout.tfplan
terraform -chdir=infra/workloads show -no-color large-upload-backout.tfplan
terraform -chdir=infra/workloads apply large-upload-backout.tfplan

```

รอ Portalready/UI กลับ 1MiB ตรวจงานใหม่ baseline อีกหนึ่งงาน และอ่าน joblarge ที่สร้างก่อน backout ว่าค่า 5MiB ยังอยู่ ไม่แก้ document เหล่านั้นตามค่า global หรือเรียกว่าคืน limits ของทุกงานแล้ว

**จุดบันทึก T10:** เหตุผล/ทางเลือก/trade-off …; baselinejobquota/limits/metrics …; oldjobUUID และ contract ก่อน–หลัง …; reviewedchange/revision …; fixturebytes/SHA/outcomes/report …; largepolicynegative/objectabsence …; workerresource/timing และข้อจำกัด …; backout/newbaseline/งาน large ค้าง …  
**เกณฑ์ไปต่อ:** พิสูจน์ contract ใหม่และเก่าแยกได้ ข้อมูลรายงานถูกต้อง และคืน baseline หรือระบุ finalconfiguration ที่ตัดสินใจ ไม่อ้าง productionthroughput จากไฟล์ไม่กี่ชุด

### Task 11 — แยกอายุ capability, อายุงาน และเวลาเก็บข้อมูล

**ก่อนเริ่ม:** faultfalse ทั้งคู่ งานตัวอย่าง T05 สำเร็จและยังไม่เกิน expires_at ใช้ Browser ส่วนตัว ไม่มีการแชร์ signedURL/policy/Cookie หรือ HAR

| ชั้น | ค่า baseline | ความหมาย |
|---|---|---|
| Upload policy | ไม่เกิน 300s และ upload_deadline | สิทธิ์ส่ง object เฉพาะ key ข้อมูลยังไม่เกิดถ้ายังไม่ upload |
| Download link | ไม่เกิน 60s และเวลางานที่เหลือ | beareraccess เฉพาะ outputgeneration การ logout ไม่เพิกถอน link เดิม |
| App job expiry | created_at+24h | App ไม่ออก capability ใหม่หลังหมดอายุ แม้ document/object ยังอยู่ |
| Firestore TTL | delete_after=created_at+48h | ลบ metadata ภายหลัง ไม่ใช่ access-control และไม่ลบ Storage ให้เอง |
| Storage lifecycle/softdelete | lifecycle2 วัน/softdelete7 วัน | physicalretention/ค่าใช้จ่ายต่างจาก Appexpiry ไม่ลบตรงวินาที |

#### Download link หมดอายุโดยไม่ขอ link ใหม่มาปะปน

ใน Browser ที่ login alice อยู่ เปิด DevToolsConsole ใช้ jobUUID ที่ succeeded ยังไม่ expired ตัวแปร capability เป็นข้อมูลลับชั่วคราวใน Browser นี้ ไม่พิมพ์ URL ออก console หรือถ่ายภาพ:

```javascript
const expiryJob = 'ใส่-jobUUID-ที่-succeeded';
const expirySession = await fetch('/api/session', {cache:'no-store'}).then(r => r.json());
const expiryReply = await fetch('/api/jobs/' + expiryJob + '/download-link', {
  method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':expirySession.csrf}, body:'{}'
});
const expiryCapability = expiryReply.ok ? await expiryReply.json() : null;
console.log({status:expiryReply.status, expires_at:expiryCapability ? expiryCapability.expires_at : null});

```

ถ้า status ไม่ 200 ให้หยุดตรวจ owner/state/expiry/signing ก่อน เมื่อ 200 ให้เปิด URL เดิมโดยไม่แสดงค่าใน console:

```javascript
window.open(expiryCapability.url, '_blank', 'noopener,noreferrer');

```

**Expected ก่อนหมดอายุ:** download สำเร็จ ใช้ Networktab ตรวจ status ของ request จริง หลังเวลาที่ expires_at ระบุผ่านไปแล้วเผื่อ clock เล็กน้อย ให้เปิด URL ตัวเดิมอีกครั้งด้วยคำสั่งเดิม **ไม่กดปุ่ม download ใหม่** ต้องถูก GCS ปฏิเสธ เก็บเฉพาะ status/errorcode/เวลาที่ไม่มี query ในภาพ ถ้า Browser ใช้ไฟล์เดิมหรือ cache ไม่ใช่ networkrequest ใหม่ ให้บันทึกว่ายังพิสูจน์ไม่ได้ ไม่เดาว่า access ยังใช้ได้จากไฟล์ที่ดาวน์โหลดไว้ก่อน

ลิงก์อาจยังใช้ได้หลัง logout แต่ก่อนหมดอายุ นี่คือ bearersemantics ไม่ใช่ ownercheck พัง คนที่ไม่มี URL ยังต้องผ่าน ownerAPIcheck ตาม T06 การลบไฟล์ที่ดาวน์โหลดในเครื่องก็ไม่ใช่การเพิกถอน capability

#### Upload policy อายุสั้น กับงานที่ยังไม่ได้รับไฟล์

ใช้ alice สร้าง job ใหม่ที่ตั้งใจทดสอบ ไม่ใช้ key ของงานเก่า เก็บ UUID/เวลาโดยไม่แสดง policy:

```javascript
const uploadExpirySession = await fetch('/api/session', {cache:'no-store'}).then(r => r.json());
const uploadExpiryKey = sessionStorage.getItem('lab006.uploadExpiryKey') || 'expiry-' + crypto.randomUUID();
sessionStorage.setItem('lab006.uploadExpiryKey', uploadExpiryKey);
const uploadExpiryCreate = await fetch('/api/jobs', {
  method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':uploadExpirySession.csrf,'Idempotency-Key':uploadExpiryKey},
  body:JSON.stringify({display_name:'upload-expiry-check.csv'})
});
const uploadExpiryJob = await uploadExpiryCreate.json();
const uploadExpiryPolicyReply = await fetch('/api/jobs/' + uploadExpiryJob.job_id + '/upload-policy', {
  method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':uploadExpirySession.csrf}, body:'{}'
});
const uploadExpiryPolicy = uploadExpiryPolicyReply.ok ? await uploadExpiryPolicyReply.json() : null;
console.log({createStatus:uploadExpiryCreate.status, job_id:uploadExpiryJob.job_id,
  policyStatus:uploadExpiryPolicyReply.status, expires_at:uploadExpiryPolicy ? uploadExpiryPolicy.expires_at : null});

```

ต้อง create200/201 และ policy200 ก่อนต่อ **อย่า upload ก่อนหมดอายุ** เพื่อไม่ให้ overwrite-denial มาปน เมื่อผ่าน expires_at แล้ว ส่ง policy เดิมกับ CSV เล็กตามนี้:

```javascript
const expiredForm = new FormData();
for (const [field, value] of Object.entries(uploadExpiryPolicy.fields)) expiredForm.append(field, value);
expiredForm.append('file', new Blob(['sale_id,sku,quantity,unit_price_satang\nS1,BOOK-01,1,100\n'], {type:'text/csv'}), 'source.csv');
try {
  const expiredUpload = await fetch(uploadExpiryPolicy.url, {
    method:'POST', body:expiredForm, credentials:'omit', redirect:'error', referrerPolicy:'no-referrer'
  });
  console.log({expiredUploadStatus:expiredUpload.status});
} catch (_) { console.log({result:'ดู Network และ Storage เพิ่มเติม; fetch error อย่างเดียวไม่พิสูจน์ expiry'}); }

```

**Expected:** GCS ปฏิเสธด้วยเหตุ expiry และไม่มี incomingobject ของ UUID นี้ ต้องดู Networkstatus/errorcode กับ Storageabsence หาก CORS บัง errorbody หรือมีเหตุอื่นให้บันทึกยังสรุปไม่ได้ ไม่ถือ TypeError เป็น PASS การขอ policy ใหม่หลัง deadline ต้องถูก App ปฏิเสธด้วย 409 ไม่แก้ deadline ใน Firestore เพื่อให้ต่อได้

เมื่อจบปิด DevTools/privatewindows ที่มี capability ไม่ใส่ตัวแปรหรือ fullURL ใน evidence อย่าเรียกทุก result ที่ยังอยู่ awaiting_upload ว่า access ยังใช้ได้ ต้องดู deadline กับ request จริงด้วย

#### Job expiry และ retention ไม่ใช้การแก้เวลาแทนการรอจริง

หากจะพิสูจน์ App24h บน GCP ให้เลือก job สังเคราะห์หนึ่งรายการและจด expires_at จาก metadata จริงก่อน ตัดสินใจเรื่องงบ/retention แล้วจึงเลือกว่าจะเก็บ environment ถึงเวลานั้นหรือไม่ ไม่เปิด poll/browser/workerfault ค้างรอทั้งคืน งานนี้ไม่ได้อนุญาต agent ให้เปิดระบบรอแทนคุณ

หลัง expires_at ให้ login ใหม่และอ่าน job เดิม: status แสดง expired; owner ขอ download/uploadcapability ใหม่ต้อง 409 แม้ document/object ยังเห็นใน Console ได้ ตรวจเวลา UTC และอายุ session แยกจาก jobexpiry ไม่แก้ expires_at/ระบบ clock แล้วอ้างว่าเป็น elapsed24h จริง

ถ้าไม่รอให้บันทึก“Cloud job-expiry: Not run; ตรวจ logic ใน emulator แล้วเท่านั้น” ไม่ติ๊ก R6 ครบจาก CI ส่วน TTL/lifecycle ต้องตรวจ operation/metrics และ inventory ภายหลังตาม [Firestore TTL](https://firebase.google.com/docs/firestore/ttl) ไม่มีคำรับประกันว่าจะลบตรงเวลา 48h

**จุดบันทึก T11:** UUID/expiry แต่ละชั้น …; freshdownload ก่อน/หลัง URL เดิมหมดอายุ …; uploadpolicy ก่อนสร้าง object/expiredrequest/absence …; App24h ผลจริงหรือ Notrun …; TTL/lifecycle/softdelete สถานะและข้อจำกัด …  
**เกณฑ์ไปต่อ:** อธิบายได้ว่าหมดสิทธิ์กับข้อมูลถูกลบเป็นคนละเหตุการณ์ และไม่มี capability รั่วในหลักฐาน

### Task 12 — สรุปหลักฐานและส่งมอบ Case Study

ทำก่อน Cleanup เมื่อทุกงานได้ผลแน่นอนแล้ว หากยังมี dispatchunconfirmed/pendingunknown ให้ resolve หรือบันทึกเป็นข้อจำกัดชัดเจน ไม่เขียน PASS เพราะทรัพยากรชื่อครบ

| Requirement | หลักฐานจากการทำของคุณ / ข้อจำกัด |
|---|---|
| R1 journey/report | T05: UUID/sourceSHA/input-outputgenerations/reportverified … |
| R2 owner/identity | T04/T06: anonworkerIAMdeny, bob404/operator403, Secret/bucket/SApolicies … |
| R3 validation/bounds | T06/T07: rejected reason, Storagepositivecontrol/negativecode/objectabsence … |
| R4 duplicate/convergence | T08/T08B: event IDs เดิม–ใหม่, owner/input/output generation/hash ก่อน–หลัง, ผลเดียว และขอบเขตของ sequential replay เทียบกับ emulator race tests … |
| R5 fault/recovery | T08–09: revision/marker/budget/epoch/samekeyreplay/reconcile … |
| R6 accessage/retention | T11: URL/policyexpiry, App24h ผลจริงหรือ Notrun, retainedinventory … |
| R7 change | T10: ทางเลือก/limitsimmutable/fixtures/metrics/backout … |
| R8 operations/handover | runbook, versions, unresolveditems, Cleanup/rebuild/costreview … |

สรุปด้วยคำของคุณ: ปัญหาทีม …; เหตุผลเลือก directupload/Eventarc/Firestore …; ส่วนที่ทำเอง/ใช้ samplecode/ตัดสินใจเพิ่ม …; incident หนึ่งเรื่องแบบอาการ→หลักฐาน→สาเหตุ→แก้→retest …; changetrade-off และผลจริง …; สิ่งที่จะปรับก่อน production เช่น SSO/abusecontrols/streaming/alerting …; ค่าใช้จ่าย/เวลาระบบเปิด …; สิ่งที่ยังไม่ได้พิสูจน์ …

Diagram ต้องตรง finalconfiguration ไม่วาด worker เป็น privateVPC เพราะมี IAM อย่างเดียว และไม่อ้าง exactly-once/zero-downtime/productioncapacity หรือ malwarescanning จาก CSVvalidation ตรวจทุกภาพ/log ว่าไม่มี password/sessionkey/passwordhash/cookie/CSRF/policy/fullsignedURL/state/planbinary/HAR เก็บ privatejournals ต่างหาก ผลที่ไม่มีหลักฐานให้ระบุ Notrun/ยังสรุปไม่ได้

### Task 13 — Cleanup พร้อม inventory และวิธีสร้างกลับ

**คำเตือน:** ขั้นนี้ลบข้อมูลและทรัพยากรของ Lab จริง ทำเฉพาะ sandbox และ state ที่ยืนยันแล้ว เก็บรายงาน/evidence/ข้อมูลที่ต้องการก่อน ไม่มี undo ที่รับประกันจะคืนทุกอย่าง

| เจ้าของ | เป้าหมาย |
|---|---|
| workloadstate | Eventarctrigger/transport ที่ระบบสร้าง, CloudRunPortal/worker/revisions/IAMinvokers |
| foundationstate | privatebuckets/objects, namedFirestore/TTL/IAM, 5SAs/customroles, authSecretcontainer/versions, ArtifactRegistry/images, bindings |
| นอก state | localprivatebundle/journals, downloadedreports, softdeletedobjects/buckets, logs/budgets และ CloudShellworkspace |
| ไม่ใช่เป้าลบ | project/Billing/(default)database/ข้อมูลทีมอื่น/remoteTerraformbackend/sharedrepositories |

1. หยุด writers/tools/polling และ operatorretry ตรวจทุก UUID ที่มีผลไม่แน่นอน เก็บ finalreport/metadata/history ที่ sanitized
2. หยุดออก capability ใหม่และรอสิทธิ์เก่าที่ออกไปหมดอายุตามที่บันทึก ไม่คิดว่าปิด Portal แล้ว signedpolicy เดิมหายทันที หากมีผู้ใช้อื่นต้องประสานให้หยุดก่อน ไม่ทำ cleanup ขณะยัง upload
3. ตั้ง faultfalse ทั้งคู่/limitmodebaseline และ variables เดิมให้ตรง state Review ปลด workloadsdeletiongate ก่อน destroy:

```bash
cd "$LAB_DIR"
gcloud config get-value project
export TF_VAR_worker_fail_before_read=false
export TF_VAR_worker_fail_after_output_once=false
export TF_VAR_upload_limit_mode='baseline'
terraform -chdir=infra/workloads plan -var=allow_destroy=true -out=workloads-unlock.tfplan
terraform -chdir=infra/workloads show -no-color workloads-unlock.tfplan
terraform -chdir=infra/workloads apply workloads-unlock.tfplan
terraform -chdir=infra/workloads plan -destroy -var=allow_destroy=true -out=workloads-cleanup.tfplan
terraform -chdir=infra/workloads show -no-color workloads-cleanup.tfplan
terraform -chdir=infra/workloads apply workloads-cleanup.tfplan
terraform -chdir=infra/workloads state list

```

Plan ต้องลบเฉพาะ Labservices/trigger/IAM ไม่มีระบบอื่น หลัง destroy ตรวจ Eventarc/CloudRunConsole และ transportPubSub ที่ trigger เคยใช้ ถ้าพบค้างให้ตรวจ owner/resource reference ก่อนลบ ไม่ลบ topic/subscription ทั้ง project แบบเหมารวม

4. ตรวจชื่อ bucket จาก foundationstate ให้ตรงตัวแปรก่อนเลือกข้อมูลลบ:

```bash
export EXPECTED_INCOMING="$(terraform -chdir=infra/foundation output -raw incoming_bucket)"
export EXPECTED_RESULTS="$(terraform -chdir=infra/foundation output -raw results_bucket)"
test -n "$INCOMING_BUCKET"
test -n "$RESULTS_BUCKET"
test "$INCOMING_BUCKET" = "$EXPECTED_INCOMING"
test "$RESULTS_BUCKET" = "$EXPECTED_RESULTS"
gcloud storage buckets describe "gs://$INCOMING_BUCKET"
gcloud storage buckets describe "gs://$RESULTS_BUCKET"
gcloud storage ls --all-versions --long "gs://$INCOMING_BUCKET/incoming/**"
gcloud storage ls --all-versions --long "gs://$RESULTS_BUCKET/results/**"

```

ถ้า test เปรียบเทียบตัวใดไม่ผ่านให้หยุด ไม่ทำคำสั่งลบ หากรายการตรง Lab และตัดสินใจไม่เก็บข้อมูลแล้วจึงลบเฉพาะ prefix เหล่านี้:

```bash
gcloud storage rm --all-versions "gs://$INCOMING_BUCKET/incoming/**"
gcloud storage rm --all-versions "gs://$RESULTS_BUCKET/results/**"
gcloud storage ls --all-versions --long "gs://$INCOMING_BUCKET/**"
gcloud storage ls --all-versions --long "gs://$RESULTS_BUCKET/**"

```

ไม่มี matchingobject ให้บันทึก empty ไม่ retrydelete ไม่จำกัด หากมีไฟล์นอก prefix ให้ตรวจทีละไฟล์/ที่มา ไม่เปลี่ยน force_destroy=true เพื่อข้ามข้อมูลไม่รู้จัก softdeletedobjects อาจยังอยู่ 7 วันตาม policy และคิดค่าเก็บ ตรวจ ConsoleProtection/Soft-deletedobjects พร้อม expiry ไม่ใช้ live-list ว่างแทน zero-cost

5. ReviewArtifactRegistry ของ Lab และบันทึก images/digests ที่ต้องเก็บก่อนลบ repository ด้วย foundation ห้ามลบ sharedrepo หรือเผย privatebundle ใน image:

```bash
gcloud artifacts docker images list "$IMAGE_REPOSITORY" --include-tags --limit=50
gcloud firestore databases describe --database=lab006-files --format='yaml(name,locationId,type,deleteProtectionState)'
terraform -chdir=infra/foundation plan -var=allow_destroy=true -out=foundation-unlock.tfplan
terraform -chdir=infra/foundation show -no-color foundation-unlock.tfplan
terraform -chdir=infra/foundation apply foundation-unlock.tfplan
terraform -chdir=infra/foundation plan -destroy -var=allow_destroy=true -out=foundation-cleanup.tfplan
terraform -chdir=infra/foundation show -no-color foundation-cleanup.tfplan
terraform -chdir=infra/foundation apply foundation-cleanup.tfplan
terraform -chdir=infra/foundation state list

```

**Review ก่อนยืนยัน:** database เป้าลบต้องเป็น lab006-files เท่านั้น ไม่ใช่(default)หรือ database ทีมอื่น การลบนี้ลบ metadata/history ไม่ใช่ exportbackup ส่วน Secret/image/bucket/SA/customroles ตาม inventory จะหายหรือถูก softdelete ตามบริการ หาก resourceinuse ให้หาว่า workloads/trigger ยังค้าง ไม่ใช้ state-rm/force-unlock เพื่อหลบ dependency

6. ตรวจ state เทียบของจริง:

```bash
gcloud run services list --region="$REGION" --filter='metadata.name~^lab006-'
gcloud eventarc triggers list --location="$REGION" --filter='name:lab006-'
gcloud firestore databases list --format='table(name,locationId,type)'
gcloud secrets list --filter='name:lab006-'
gcloud iam service-accounts list --filter='email:lab006-'
gcloud artifacts repositories list --location="$REGION" --filter='name:lab006-files'

```

ตรวจ Storage/retainedobjects, PubSubtransport, deletedcustomroles/SAs, logsretention และ BillingReports ช่วง project/labels ของ Lab ด้วย Billing อาจตามหลัง inventory ว่างจึงยังไม่ใช่ค่าใช้จ่ายศูนย์ APIs ที่ foundation เปิดตั้ง disable_on_destroy=false จึงยัง enabled ไม่จำเป็นต้องปิด API ที่คนอื่นใช้เพื่อทำให้หน้าดูว่าง

7. เก็บหรือลบ privatebundle/journals/state/plan/report ตามอายุที่กำหนดหลังยืนยัน cleanup ไม่ recursive ลบ home/checkout ไม่ commit ของเหล่านี้หรือ fullsignedURL และไม่ลบ remotebackend/budget ที่มี owner อื่นโดยไม่ตกลงกัน

**จุดบันทึก T13:** capabilities หมดอายุ/งานค้าง …; reviewedunlock/destroyplans …; workloads/foundationstate …; liveinventory เทียบ state …; softdelete/transport/logs/role-retention และ expiry …; Billing ตรวจเมื่อใด/รายการค้าง …; privatefilepolicy …; ปัญหา/การแก้ …

#### Rebuild ไม่ใช่ restore ข้อมูลธุรกิจ

ใช้ SOURCE_COMMIT และ image@digest ที่บันทึกหรือ build ใหม่พร้อมจด digest ที่เปลี่ยน เริ่ม checkoutpersistent ใหม่เมื่อยืนยัน state เก่า empty และทรัพยากรเดิมไม่ค้าง เลือก bucket ชื่อใหม่หากชื่อเดิมยังมีข้อจำกัดจาก softdelete สร้าง Secretbundle ใหม่สำหรับ environment ใหม่ ไม่ reuseorder/retryjournals ของ database ที่ถูกลบ

Customroles อาจยังอยู่ในสถานะ deleted ระหว่าง retention จึงอย่าสมมติว่าใช้ roleID เดิมได้ทันที หาก create แจ้ง alreadyexists ให้ตรวจ IAMRoles ที่ deleted เฉพาะ 3roles ของ Lab นี้ก่อน ทางเลือกคือรอรอบ retention หรือ recover/importresource เดิมที่ยืนยัน owner แล้วพร้อม reviewplan ไม่สร้าง customrole กว้าง/เปลี่ยนชื่อสุ่มทุกครั้งเพื่อให้ apply ผ่าน

ทำ Task0→1→2→3→4 ใหม่แล้วทดสอบ journey/report/access ใหม่ ถ้าต้อง recoverSA/role/bucket ให้บันทึกสิ่งที่กู้และผล IAM จริง ไม่อ้าง identicalrebuild จาก email/ชื่ออย่างเดียว การสร้าง schema/บริการใหม่ไม่ได้คืนไฟล์ยอดขายหรือ report ที่ลบแล้ว หากต้อง restore ข้อมูลต้องมี export/backup และ runbook แยก
