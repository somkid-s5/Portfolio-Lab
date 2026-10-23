---
lab: LAB-006
platform: GCP
guide_status: authoring
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

## Design — สัญญาที่ใช้สร้าง Materials

### Resource map และขอบเขตจริง

| Resource | ขอบเขต / ค่าตั้งต้น |
|---|---|
| Portal/API | Cloud Run service lab006-portal, asia-southeast1; HTTPS URL ของบริการ; min0/max2 instances, concurrency8, timeout30s, memory512MiB |
| Worker | Cloud Run service lab006-worker, asia-southeast1; ต้องผ่าน Cloud Run IAM, min0/max2, concurrency1, timeout60s, memory512MiB |
| Incoming / results | bucketคนละใบ ชื่อ globally unique ที่ผู้เรียนกำหนด, regional ASIA-SOUTHEAST1, uniform access/public-access prevention; ไม่มี static website/public ACL |
| Metadata | Firestore Native Standard named database lab006-files ใน asia-southeast1 ไม่ใช้หรือเปลี่ยน default database; server SDKเลือก database IDชัดเจน |
| Events | Eventarc Standard trigger lab006-incoming-finalized, asia-southeast1, filter finalized+incoming bucket, destination worker path /events/storage |
| Image / Secret | Artifact Registry repositoryของLab, image digestที่บันทึกไว้; auth Secret versionเป็นเลข, ไม่มีpayloadในTerraform |
| Signing | แยก service accounts upload-signer และ download-signer; portalขอ signBlob ไม่ใช้keyfile |
| Observability | structured stdout/stderr และ Cloud Run metrics; job_id/request_id/event_id/attempt tokenใช้เชื่อมเหตุการณ์ ไม่มีCSV/policy/signedqueryในlogs |

ทุกresourceอยู่projectเดียวกัน Eventarc locationตรงincoming bucket; Firestoreเป็นmanaged regional service ไม่วาดอยู่ในVPCsubnet และCloud Runในโจทย์นี้ไม่ได้ใช้VM/privateVPC/NATเพิ่มเพียงเพื่อให้Diagramใหญ่ Workerใช้ingress allพร้อมIAMauthenticationเพื่อให้Eventarcและเครื่องมือoperatorที่ได้รับอนุญาตเรียกได้ **ไม่อ้างว่าเป็นprivate network endpoint** Public portalต้องผ่านAppauthสำหรับทุกbusinessendpoint ยกเว้นlogin/health/static

Named Firestore databaseแยกจากข้อมูลระบบอื่นเพื่อลดความเสี่ยงตอนCleanup แต่IAMต้องตรวจscopeตามdatabaseที่ใช้จริง ไม่อ้างว่าแยกdatabaseแล้วproject-widegrantsจะหายไปโดยอัตโนมัติ

### Identity และ permission matrix

| Identity | อนุญาต | ไม่อนุญาต / จุดตรวจ |
|---|---|---|
| portal SA | อ่านauth Secretที่ระบุ; อ่าน/สร้าง/แก้jobผ่านFirestore; signBlobบนsignerทั้งสอง; invoke workerเฉพาะserviceเพื่อmanualretry | ไม่มีStorageobjectadmin/ไม่อ่านincomingbytes; ไม่มีprivatekey; signBlobไม่จำเป็นต้องgrantTokenCreatorทั้งproject |
| upload signer | storage.objects.create เฉพาะincoming bucket | ไม่มีget/list/delete/update; replaypolicyต้องไม่overwriteobjectเดิม |
| download signer | storage.objects.get เฉพาะresults bucket | ไม่มีcreate/delete/list; portalต้องตรวจownerก่อนออกGET URL |
| worker SA | Firestorejob transactions; getincoming generation; create/getresults | ไม่มีsignBlob/ไม่มีauth Secret/ไม่ลบหรือแก้incoming; ไม่ให้Editor |
| Eventarc trigger SA | eventarc.eventReceiverตามscopeที่บริการกำหนด และrun.invokerเฉพาะworker | ไม่มีpermissionอ่านไฟล์เพื่อทำแทนworker |
| Cloud Storage service agent | pubsub.publisherสำหรับdirecteventtransportตามเอกสาร | แยกจากtrigger SA/runtimeworker ไม่ให้StorageAdminแทน |
| ผู้ดูแลLab | deploy/actAs/inspectตามความจำเป็นและreviewIAM | สิทธิ์ผู้ดูแลไม่ใช้เป็นหลักฐานว่ารันtimeidentityทำได้ |

สร้างcustom roleสำหรับ iam.serviceAccounts.signBlob แล้วbindบนsignerแต่ละตัวให้portal แทนroleที่รวมgetAccessTokenโดยไม่จำเป็น หากนโยบายองค์กรไม่อนุญาตcustom roleต้องบันทึกทางเลือก/สิทธิ์ส่วนเกินก่อนdeploy ไม่เพิ่มOwnerเพื่อให้ผ่าน สิทธิ์Firestoreต้องใช้IAMcondition/database scopeที่providerรองรับและตรวจpolicyจริงก่อนเรียกleast-privilege; tests emulatorไม่พิสูจน์IAM

### HTTP และ upload contract

Portalใช้Flask signed session, Secure/HttpOnly/SameSite=Lax, CSRFสำหรับทุกmutation, hashedsyntheticpasswordsและoperatorrole; HTML/JSใช้same-originAPI ไม่มีpasswordหรือCSRFในlocalStorage ไม่มีinlineexecutionจากfilename/CSV

| Endpoint | สัญญา |
|---|---|
| POST /api/login, POST /api/logout | จำกัดrequestbody, CSRFที่เหมาะกับsession, genericbadlogin, ไม่logcredentials |
| GET /api/session | คืนuser/role/CSRFสำหรับsessionที่เปิดอยู่ ไม่คืนpasswordhash |
| POST /api/jobs | ownerจากsession ไม่รับownerจากbody; รับdisplaynameที่จำกัดและidempotencykey; สร้างjob+quotareservationในtransaction |
| POST /api/jobs/{id}/upload-policy | ownerผ่านก่อน; ออกpolicyเฉพาะawaiting_uploadและภายในupload deadline; retryได้แต่ใช้objectkeyเดิม |
| GET /api/jobs, GET /api/jobs/{id} | queryownerฝั่งserver, จำกัดpage size20/cursor; other-owner404; ไม่คืนpolicyหรือobjectstorageURL |
| POST /api/jobs/{id}/download-link | owner+CSRF+success+notexpired; signedGETตรึงoutputgeneration; Cache-Control:no-store |
| POST /api/operator/jobs/{id}/retry | operator+CSRF; จำกัดepoch/attempt; preservegeneration/limits/version; เรียกworkerด้วยIDtokenและaudienceของworker |
| POST worker /events/storage | Cloud Run IAMก่อนเข้าApp; CloudEvents binary headers+JSONdata; จำกัดbody64KiB; ตรวจeventtype/source/bucket/key/generationซ้ำ |
| GET /livez, GET /healthz | ไม่แก้ข้อมูล; livezprocess/config, healthz boundedmetadataread ไม่มีlistทุกjob |

Baseline: input1,048,576bytes/10,000rows; change5,242,880bytes/50,000rows; แต่ละfieldไม่เกิน128chars, SKUรูปแบบallowlist, quantity1..1,000,000และunit_price_satang0..100,000,000; จำกัดผลรวมไม่เกินsigned64-bit integer ปฏิเสธNaN/decimal/bool/extra columns/nullbytes/quotednewlineถ้าparsercontractไม่รองรับ BOM/CRLFต้องกำหนดและทดสอบชัดเจนก่อนประกาศใช้งานได้

POSTpolicyอายุสูงสุด300s และไม่เกินupload_deadline; keyตรงincoming/{jobUUID}/source.csv, Content-Type=text/csv, lengthrange1..job.max_bytes ไม่มีstarts-withkeyที่เปิดให้เลือกpathเอง Browserใช้FormDataส่งpolicyfieldsตามที่APIให้และfileเป็นfieldสุดท้าย ไม่ตั้งmultipartboundaryเอง กำหนดsuccess_action_status201แล้วตรวจresponseก่อนpolljob

Storagepolicyตรวจheaders/size แต่ไม่รู้ว่าbytesเป็นCSVจริง Workerdownloadแบบbounded max_bytes+1และตรึงgeneration ไม่ใช้download_as_bytesแบบไม่จำกัดกับeventsizeที่เชื่อจากclient ไม่followURLในevent ไม่evalformulaหรือเปิดspreadsheetเพื่อรันmacro

Uploadpolicyเป็นbearerpermissionและreplayได้ระหว่างTTL การcreateobjectชื่อเดิมอีกรอบต้องถูกปฏิเสธจากsignerที่ไม่มีdelete/update; ต้องพิสูจน์บนGCPจริง หากstorageAPI/libraryต้องการpermissionเกินที่ตั้งไว้ให้ทบทวนcontract ไม่ให้overwriteเพื่อทำให้testผ่าน

DownloadTTLสูงสุด60sและไม่เกินเวลาที่jobเหลือก่อนexpires_at ออกURLเฉพาะgenerationที่ตรวจแล้ว Content-Disposition attachmentชื่อserverกำหนดและContent-Type application/json; ผลใกล้หมดอายุจนเหลือไม่ถึง1sให้ปฏิเสธ การlogoutไม่เพิกถอนlinkที่ออกไปแล้ว

### Metadata และ state machine

jobs/{UUID} มี owner, display_name, object_name, created_at/upload_deadline/expires_at/delete_after, max_bytes/max_rows, processor_version, state, input_generation, input_sha256, attempt_epoch/count/token/lease_until, output_name/generation/sha256, safe_reason และtimestamps ส่วนidempotencyrecordsใช้hash(owner+key)พร้อมfingerprintและjobreference ไม่เก็บrawkeyในlogs

ตั้งexpires_at=created+24hสำหรับAppaccess; upload_deadline=created+5min; delete_after=created+48hสำหรับTTLcleanup งานที่ไม่uploadหลังdeadlineเป็นexpiredเมื่ออ่าน/ตรวจreconcile ไม่ต้องอ้างว่ามีdaemonเปลี่ยนสถานะตรงเวลา TTLdeleteอาจล่าช้าและไม่ลบStorageobjectsโดยอัตโนมัติ

| สถานะเดิม | เหตุการณ์ | ผล |
|---|---|---|
| awaiting_upload | finalizedeventที่ตรงkey/bucketและไม่เลยdeadline/expiry | transactionbindgenerationครั้งเดียวแล้วclaimprocessing |
| processing / leaseยังไม่หมด | duplicategenerationเดิม | retryable503 ไม่ackแล้วพึ่งworkerเดิมเพียงตัวเดียว |
| processing / leaseหมด | eventเดิมส่งใหม่ | claimtokenใหม่; workerเก่าไม่มีสิทธิ์publishstatus |
| processing | validationไม่ผ่าน | rejected+safe_reason แล้วack204; ไม่มีpublishedoutput |
| processing | outputverified + tokenยังตรง | succeededพร้อมgeneration/hashแล้วack204 |
| processing | transientstorage/metadata failure | ปล่อยleaseให้หมดหรือreleaseโดยtoken; return503สำหรับtransportretry |
| succeeded/rejected/expired | duplicateevent | ack204โดยไม่สร้างผลใหม่ |
| ทุกสถานะที่bindแล้ว | generationต่างจากที่bind | ignore+reasonlogged ไม่เปลี่ยนowner/input/result |
| retrybudgetครบ | transientครั้งถัดไป | failedพร้อมsafe_reasonและack; operatorretryได้ตามpolicy ไม่วนตลอดไป |

Lease120sยาวกว่าworkerrequest60sบวกช่วงcleanup; processdeadline45s และclienttimeout/retrybudgetย่อยต้องรวมไม่เกินdeadline ไม่ต่อleaseไม่จำกัด attemptไม่เกิน5ต่อepoch, manualretryไม่เกิน2epochsเพิ่มจากครั้งแรก; rejected/expiredไม่เปิดretryเพื่อหลบvalidation ต้องสร้างjobใหม่ผ่านขั้นตอนปกติ งานfailedเก็บgenerationเดิมและนำoutputที่ถูกต้องกลับมาใช้ได้

Unknown/malformedevents: invalidenvelope400เพื่อให้เห็นconfigurationerror; authenticแต่ไม่อยู่bucket/key/jobnamespaceของLabให้ack204และsafeignoredreason ไม่สร้างjobจากevent หากmetadataอ่านไม่ได้เป็น503ไม่เหมาว่าunknownแล้วack งานที่หาไม่เจอจริงต้องlogignoredและให้runbookreconcile ไม่สร้างownerจากobjectmetadataที่clientปลอมได้

### Output commit และการกู้ช่องว่างข้ามบริการ

คำนวณsummaryแบบdeterministic ใช้integer, sortedSKU, canonicalUTF-8JSON ไม่มีcurrenttime/attempttokenในbusinessbytes Outputkeyคือ results/{jobUUID}/{inputGeneration}/{processorVersion}/summary.json เขียนif_generation_match=0 พร้อมmetadatainputSHA/processorversion ไม่updateobjectที่มีอยู่

ถ้าได้preconditionfailed ให้GETexistinggenerationแบบboundedและเทียบcanonicalbytes/SHA/inputgeneration/versionก่อนreuse หากไม่ตรงให้failed_integrityและหยุด ไม่overwriteเพื่อให้เลขตรง ส่วนtimestampการattemptเก็บในFirestoreแยกจากผลสรุป

หลังเขียนหรือverifyoutputแล้วจึงFirestoretransactionตรวจtoken/generation/version/expiryก่อนpublishsuccess ถ้าworkerเก่าถูกfenceoutputที่คำนวณเหมือนกันอาจยังเกิดได้ แต่ไม่เปลี่ยนstateและไม่มีผลธุรกิจซ้ำ workerใหม่verifyreuseแล้วcommitต่อ ถ้างานexpireระหว่างทำต้องไม่publishdownloadable success; เก็บorphanoutputให้cleanupตามretention

Faultcontrolเป็นrevisionconfigสำหรับsandbox: fail_after_output_onceตามjobmarkerที่เก็บในFirestore ไม่รับflagจากclientทั่วไป ปิดfaultแล้วreplayeventgenerationเดิมต้องจบได้ด้วยoutputเดิม ไม่อ้างexactly-oncedelivery แต่พิสูจน์logicalresultconvergence

### Test matrix และจุดส่งมอบถัดไป

1. Domain parserfixtures: valid/CRLF/BOMcontract, duplicateID, invalidUTF8/header/quantity/price, maxbytes/rows/field/total bounds; exactexpectedsummary
2. Firestore emulatorจริง: owner/idempotencytransaction, concurrentclaim, generationbinding, leaseexpiry, stale-tokencommit, retrybudget/manualepoch, expiration และquotareservation ไม่ใช้fakeอย่างเดียว
3. Storageadapter: boundedgenerationread, create-onlyoutput, existinghashmismatch, signedpolicyexactconditions/keylesssigner; mockrequestใช้ตรวจAPIcontractแต่ไม่เรียกGCPจริง
4. HTTP/browser: aliceupload/status/download, bob404, anonymous401, operator403, CSRF, workerIAMแยกจากAppunit checks, UIerror/retry/pollboundedโดยไม่เผยsignedquery
5. Recoveryintegration: outputcreated→fault→duplicateevent→sameoutputgeneration→success; invalidfileackterminal; failedtransientสามารถmanualretry; expiredjobไม่ออกlink
6. Terraform: fmt/init-backendfalse/validate; IAM/triggerlocation/Firestoreisolation/staticconfigtests; actualplan/applyและsignedupload/permission/expiryต้องผู้เรียนรันบนGCP
7. Guide: expected/actualข้างทุกTask, fixtures+boundedtools, resourceinventoryและcleanuporder; ไม่มีCloudPASSล่วงหน้า

Quotaฝึก: ไม่เกิน5activejobs/ownerและ20newjobs/owner/UTCdayด้วยtransactioncounter; จำกัดรวมชุดทดสอบ40jobsและไฟล์changeสูงสุด5MiBต่อไฟล์ นี่เป็นAppguardไม่ใช่Billinghardcap publicloginยังไม่ใช่productionabuseprotection ต้องตั้งเวลาเปิดและmaxinstancesร่วมด้วย

Retention: incoming/results lifecycledeleteหลัง2วันและบันทึกsoftdeletepolicyจริง; FirestoreTTLใช้delete_afterเมื่อเปิดpolicyแล้ว Appตรวจexpiryเองก่อนTTL; ไม่เปิดbucketversioningโดยไม่จำเป็น แต่ทุกread/resultbindingยังใช้generation Lifecycle/TTLไม่ใช่backupstrategyและไม่รับประกันไม่มีค่าใช้จ่ายหลังUIซ่อนงาน

แหล่งอ้างอิงDesign: [Eventarc Storage routing/location](https://docs.cloud.google.com/eventarc/standard/docs/run/route-trigger-cloud-storage), [Eventarc identities](https://docs.cloud.google.com/eventarc/docs/roles-permissions), [Python signed POST policy API](https://docs.cloud.google.com/python/docs/reference/storage/latest/google.cloud.storage.client.Client), [Firestore database locations](https://docs.cloud.google.com/firestore/native/docs/locations), [Firestore transaction retries](https://firebase.google.com/docs/firestore/manage-data/transactions)

**Design checkpoint:** contractsนี้เป็นเป้าหมายที่Materialsต้องทำให้จริง ไม่ใช่ผลว่าระบบถูกสร้างแล้ว ขั้นถัดไปสร้างparser/fixtures/transactionrepositoryและtestsก่อนต่อHTTP/UI/Storage/IaC หากข้อจำกัดSDK/APIเปลี่ยนให้แก้Designพร้อมเหตุผลก่อนเขียนTask


## Materials — CSV domain checkpoint

[ตัวตรวจและคำนวณรายงาน](app/csv_domain.py) รับbytesแบบจำกัดขนาด ตรวจheader/จำนวนคอลัมน์/UTF-8/identifiers/ตัวเลข/duplicate sale_id/จำนวนแถว และคืนcanonicalJSONที่เรียงSKU พร้อมSHA256ของbytesต้นฉบับ ไม่มีstorage/networkหรือการเขียนไฟล์ในdomain layer

รับUTF-8 BOMหนึ่งชุดที่ต้นไฟล์, LF/CRLFและquotedfieldsตามCSV แต่ไม่รับnewlineในfield, blankrecord, whitespaceรอบตัวเลข, leadingzeroเช่น01, exponent, floatหรือformulaเป็นidentifier ตัวเลขราคา0ได้แต่quantityต้องมากกว่า0 ชื่อSKUต้องuppercaseตามallowlist

[ไฟล์ตัวอย่าง](fixtures/valid-sales.csv) มี3รายการ/6หน่วย/72,400สตางค์ เทียบกับ [expected business summary](fixtures/valid-sales.expected.json); inputSHAคำนวณจากไฟล์จริงไม่ตรึงhashที่อาจเปลี่ยนตามlineendings มี [duplicate fixture](fixtures/duplicate-sale-id.csv) และ [10 domain tests](tests/test_csv_domain.py) รวมboundedstream/max+1, inputผิดและchange1→5MiB/10k→50krows กำลังรอcloudCIยืนยันผล ไม่ใช่ผลGCPหรือFirestoretransaction verification


### Job-state transition materials

เพิ่ม [state transitions](app/job_state.py) และ [9 tests](tests/test_job_state.py) สำหรับgenerationbinding, duplicate/busy, lease120s/reclaim, stale-tokenfencing, expiry, outputbinding, rejection, retrybudgetและmanualepochs การเปลี่ยนสถานะไม่อ่านclock/networkและไม่แก้dictต้นฉบับ จึงนำไปใช้ในFirestoretransactioncallbackได้ แต่ยัง **ไม่ได้พิสูจน์concurrencyของFirestore** จนกว่าจะต่อrepositoryและรันemulatortests

เงื่อนไขuploaddeadlineใช้เวลาที่object finalizedจากStorageevent ไม่ใช่เวลาeventมาถึงworker เพราะtransportอาจส่งช้า; workerต้องvalidateเวลาจากeventที่ผ่านIAM/source/bucketbindingแล้ว ไม่รับtimestampจากclientเอง งานยังต้องไม่เกินexpires_atตอนclaim/publish ผลfailed_integrityห้ามoperatorretryเพื่อกลบoutputที่ไม่ตรง ต้องตรวจเหตุผิดปกติก่อน


### Firestore transaction adapter checkpoint

เพิ่ม [Firestore repository](app/firestore_jobs.py) นำstate transitionsไปใช้ในSDKtransactionจริง: อ่านjob/ตรวจtoken-generation/เขียนสถานะในtransactionเดียว callbackไม่อ่านStorageและclockถูกอ่านใหม่เมื่อSDKretry มี [4emulator integration tests](tests/test_firestore_jobs.py) สำหรับสองworkerclaimพร้อมกัน, lease-reclaim/stalecommitrollback, owner/generationboundary และretrybudget/manualepoch

GitHubCIใช้Firestoreemulatorบนrunner, projectdemo-lab006/named databaselab006-filesและAnonymousCredentials พร้อมบังคับloopbackhostก่อนtest ไม่fallbackไปGCPเมื่อไม่มีemulator ยังรอผลชุดนี้ ไม่อ้างว่าtransactionผ่านจากpurestate tests และemulatorไม่พิสูจน์IAM/index/quota/productionlatency ส่วนjobcreationพร้อมidempotency/quotaและboundedlistยังต้องต่อก่อนHTTP


### Job creation และ quota checkpoint

เพิ่มtransactionสร้างjob+idempotencyrecord+ownerquotaพร้อมกัน คำขอเดิมคืนjobเดิมแม้quotaเต็ม; keyเดิมเปลี่ยนdisplayname/limits/versionเป็นconflict ไม่มีrawkeyในdocumentID ใช้SHA256(owner+key) หากrecordชี้jobที่ถูกลบหรือหมดอายุจะปฏิเสธ ไม่แอบสร้างjobใหม่

Quota5active/20newjobsต่อUTCdayถูกอ่านและปรับในtransactionเดียวกัน งานsuccess/rejected/expiredคืนactive slotเมื่อสร้างงานถัดไป; failedที่ยังretryได้ยังนับactive งานawaiting_uploadจะไม่ถูกปล่อยslotเพียงเพราะเลยuploaddeadline เพื่อไม่ให้eventที่finalizeทันแต่ส่งช้าทำให้จำนวนactiveทะลุguard ต้องตรวจreconcileก่อนexpireหรือรอjobexpiry ไม่ใช้TTLลบเป็นmechanismปล่อยquotaทันที

[CI39932700165](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39932700165) joblab006-firestoreผ่าน4emulatortestsของclaim/fencing/owner/retryแล้ว ชุดcreate/quotaเพิ่ม4testsยังรอCI ไม่มีGCPidentity/permissionsverification และยังไม่มีHTTP/UI/Storageworkerสำเร็จ


### Worker orchestration checkpoint

เพิ่ม [processor](app/processor.py) เชื่อมCSVdomainกับFirestoreclaim/finishและStorageadaptercontract: readsourcegenerationที่bind, canonicalsummary, create-or-verifyผล, fencedpublish และsafeack/retryreason มีdurablefaultmarkerสำหรับจำลองช่องว่างoutputเขียนแล้วแต่metadataยังไม่success

[CI39932999988](https://github.com/somkid-s5/Portfolio-Lab/actions/runs/39932999988) ผ่านชุดก่อนหน้า รวม8Firestoreemulatortestsและ19puretestsแล้ว ชุดworkerเพิ่ม4integrationtestsใช้Firestoreemulatorจริงแต่Storageเป็นtestdouble จึงยังไม่พิสูจน์GCSgenerationpreconditions/permissions ชุดใหม่นี้รอCI ต้องต่อStorageadapterจริงและCloudEvent/HTTPก่อนใช้งานได้


### GCS adapter checkpoint

เพิ่ม [GCS adapter](app/gcs_objects.py) สำหรับgeneration-pinnedrawrange reads พร้อมmetadata-size check/boundedbuffer และrejectcontent-encoding/MIMEผิด; outputเขียนif_generation_match=0พร้อมCRC32C ถ้ามีอยู่แล้วจะตรึงgenerationและเทียบbytes/SHA/processor metadataก่อนreuse ไม่overwriteผลที่ไม่ตรง จำกัดoutputต่ำกว่า8MiBและปิดSDKretryเพื่อให้workerคุมdeadlineได้

[7SDKcontracttests](tests/test_gcs_objects.py) ใช้autospecของBlobที่ติดตั้งจริงแต่mocktransport ตรวจprecondition/range/bounds/mismatch/nooverwrite ยังไม่ใช่ผลGCSจริง ต้องผู้เรียนพิสูจน์IAM/preconditions/CRC/latencyในการทำLab และยังรอCIชุดนี้ [Blob API](https://docs.cloud.google.com/python/docs/reference/storage/latest/google.cloud.storage.blob.Blob)


### CloudEvent validation checkpoint

เพิ่ม [binary CloudEvent parser](app/storage_events.py) และ [5tests](tests/test_storage_events.py) ตรวจspec/type/id/contenttype/body64KiB, bucket/source/subject/objectnamespace, numericgenerationและtimeCreatedแบบUTC ปฏิเสธduplicateJSONkeys/NaN/invalidencoding ไม่ตามmediaLinkและไม่ใช้eventIDเป็นbusinessdeduplicationkey

Parserนี้ไม่ใช่authentication ต้องใช้หลังCloudRunIAMเท่านั้น โดยjobIDจากservernamespace/generationจะถูกตรวจซ้ำในFirestoreclaim ส่วนforeignbucket/namespaceคืนignored ไม่สร้างjobจากmetadataที่clientใส่เอง [Eventarc HTTP binding](https://docs.cloud.google.com/eventarc/docs/cloudevents)

CI39933281841ของworkerชุดก่อนผ่านlab006-domainและlab006-firestoreแล้ว; GCScontractชุด39933551789ยังin_progressตอนตรวจ CloudEventชุดใหม่นี้ยังรอCI และยังต้องต่อHTTPreceiverจริง
