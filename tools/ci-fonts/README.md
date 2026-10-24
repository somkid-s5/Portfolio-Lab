# CI Thai preview font

ใช้ Noto Sans Thai จาก Google Fonts แบบไม่แก้ไขไฟล์ เพื่อให้ภาพ browser ใน CI อ่านภาษาไทยได้โดยไม่ต้องดาวน์โหลดแพ็กเกจ fonts-noto-core ทั้งชุด

- แหล่งที่มา: [Google Fonts ที่ตรึง commit](https://github.com/google/fonts/tree/e7db6ca603fd4862010383ff17ffd6cc4ffac1c0/ofl/notosansthai)
- Copyright 2022 The Noto Project Authors; SIL Open Font License 1.1 เก็บฉบับเต็มไว้ใน [OFL.txt](OFL.txt)
- ที่มาและ Git blob hashes: [PROVENANCE.json](PROVENANCE.json)
- Helper scripts/install-ci-thai-font.sh ทำงานเฉพาะ GitHub Actions Linux ตรวจ Git blob identity ก่อน copy ไป user-font directory และตรวจ fc-match หลังติดตั้ง
- ภาพที่สร้างด้วย font นี้ยังต้องตรวจความอ่านง่าย/การตัดข้อความจริง ไม่ใช้การติดตั้งผ่านแทน visual review
