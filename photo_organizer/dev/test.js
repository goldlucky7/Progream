const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const SP = __dirname; // photo_organizer/dev
const PICS = path.join(SP, 'testpics');
const URL = 'http://127.0.0.1:8901/index.html';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  const R = { ok: [], fail: [] };
  const check = (name, cond, extra) => (cond ? R.ok.push(name) : R.fail.push(name + (extra ? ' → ' + extra : '')));

  await page.goto(URL);
  check('title', (await page.title()) === '사진 정리 도우미');
  check('empty hero visible', await page.locator('#emptyState .hero h2').isVisible());

  // 0) 왕창 불러오기 도움말 + 폴더 불러오기
  await page.click('#btnBulkHelp');
  const helpTxt = await page.locator('#trashListText').textContent();
  check('bulk help opens', helpTxt.includes('DCIM') && helpTxt.includes('Camera.zip'));
  check('help hides copy', await page.locator('#btnCopyList').isHidden());
  await page.click('#modalClose');
  // 사진 추가 → 선택 시트
  await page.click('#btnAdd');
  check('add sheet opens', await page.locator('#addDim .sheet').isVisible());
  check('add sheet has file-app option', (await page.locator('#addDim').textContent()).includes('파일 앱에서 골라 담기'));
  await page.click('#addCancel');
  // 파일 앱 경로(allIn): 형식 제한 없는 입력 + 미디어만 걸러서 불러오기
  const someFiles = fs.readdirSync(PICS).slice(0, 3).map(f => path.join(PICS, f));
  await page.setInputFiles('#allIn', someFiles);
  await page.waitForFunction(() => typeof state !== "undefined" && state.photos.length === 3 && !state.importing, null, { timeout: 20000 });
  check('allIn import 3', true);
  await page.evaluate(() => { idbClearAll(); });
  await page.reload();
  await page.waitForFunction(() => typeof state !== "undefined" && state.photos.length === 0, null, { timeout: 20000 });
  // ZIP 통째 불러오기: 미디어 11개(한글 이름 포함)만 들어오고 잡파일은 제외
  await page.setInputFiles('#allIn', path.join(SP, 'camera_test.zip'));
  await page.waitForFunction(() => typeof state !== "undefined" && state.photos.length === 11 && !state.importing, null, { timeout: 30000 });
  check('zip import 11', true);
  check('zip exif month', await page.locator('#libGroups').textContent().then(tx => tx.includes('2024년 5월')));
  check('zip korean name', await page.evaluate(() => state.photos.some(p => p.name === '한글사진.jpg')));
  check('zip thumbs ok', await page.evaluate(() => state.photos.filter(p => p.thumb).length) === 11);
  check('zip dup group', await page.evaluate(() => state.dupGroups.some(g => g.length >= 4)));
  await page.evaluate(() => { idbClearAll(); });
  await page.reload();
  await page.waitForFunction(() => typeof state !== "undefined" && state.photos.length === 0, null, { timeout: 20000 });
  try {
    await page.setInputFiles('#dirIn', PICS);
    await page.waitForFunction(() => typeof state !== "undefined" && state.photos.length === 10 && !state.importing, null, { timeout: 20000 });
    check('folder import 10', true);
    // 초기화하고 원래 시나리오로 (샘플 18 + 파일 10 = 28 유지되도록 전체 삭제)
    await page.evaluate(() => { idbClearAll(); });
    await page.reload();
    await page.waitForFunction(() => typeof state !== "undefined" && state.photos.length === 0, null, { timeout: 20000 });
  } catch (e) { check('folder import 10', false, String(e).slice(0, 120)); }

  // 1) 샘플 불러오기
  await page.click('#btnSample');
  await page.waitForFunction(() => typeof state !== "undefined" && state.photos.length === 18 && !state.importing, null, { timeout: 30000 });
  const tileCount = await page.locator('#libGroups .tile').count();
  check('sample 18 tiles', tileCount === 18, 'got ' + tileCount);
  check('month header 2026-09', await page.locator('#libGroups').textContent().then(t => t.includes('2026년 9월')));
  const chipN = await page.locator('#monthChips .chip').count();
  check('month chips = 3', chipN === 3, 'got ' + chipN);

  // 2) 실제 EXIF 사진 불러오기
  const files = fs.readdirSync(PICS).map(f => path.join(PICS, f));
  await page.setInputFiles('#fileIn', files);
  await page.waitForFunction(() => state.photos.length === 28 && !state.importing, null, { timeout: 30000 });
  check('exif month 2024-05', await page.locator('#libGroups').textContent().then(t => t.includes('2024년 5월')));
  check('exif month 2025-01', await page.locator('#libGroups').textContent().then(t => t.includes('2025년 1월')));

  // 분석 수치 확인
  const stats = await page.evaluate(() => {
    const s = cleanSets();
    return {
      dupGroups: s.dup.map(g => g.map(p => p.name)),
      shot: s.shot.map(p => p.name),
      blur: s.blur.map(p => [p.name, Math.round(p.blur)]),
      dark: s.dark.map(p => [p.name, Math.round(p.bright)]),
      allBlurVals: state.photos.filter(p=>!p.isVideo&&p.hasHash).map(p => [p.name, Math.round(p.blur), Math.round(p.bright)]),
      exifSrc: state.photos.filter(p => p.dateSrc === 'exif').length,
    };
  });
  console.log('STATS', JSON.stringify(stats, null, 1));
  check('exif parsed >= 8', stats.exifSrc >= 8, 'got ' + stats.exifSrc);
  check('dup groups >= 2', stats.dupGroups.length >= 2, JSON.stringify(stats.dupGroups));
  check('dup contains test dups', stats.dupGroups.some(g => g.includes('dup_1.jpg') && g.includes('dup_2.jpg')));
  check('shots = 3', stats.shot.length === 3, JSON.stringify(stats.shot));
  const badMix = stats.dupGroups.some(g => g.some(n => n.includes('바다여행')) && g.some(n => n.includes('산책길') || n.includes('스크린샷') || n.includes('노을') || n.includes('Screenshot')));
  check('no false dup mixing', !badMix, JSON.stringify(stats.dupGroups));
  check('blurry found', stats.blur.some(([n]) => n === 'blurry_1.jpg'), JSON.stringify(stats.blur));
  check('dark found', stats.dark.some(([n]) => n === 'dark_1.jpg') && stats.dark.some(([n]) => n === '샘플_노을.jpg'), JSON.stringify(stats.dark));

  // 3) 테마 탭
  await page.click('#tabbar button[data-go="themes"]');
  const foodCard = page.locator('.tCard[data-open="음식"]');
  check('food card count 4', (await foodCard.locator('.meta span').textContent()).trim() === '4장');
  await foodCard.click();
  check('food grid 4', (await page.locator('#themeBody .grid .tile').count()) === 4);
  await page.click('[data-tagmode="음식"]');
  check('tag banner shown', await page.locator('.tagBanner').isVisible());
  const restFirst = page.locator('#themeBody .grid').nth(1).locator('.tile').first();
  await restFirst.click();
  await page.waitForFunction(() => document.querySelectorAll('#themeBody .grid')[0].querySelectorAll('.tile').length === 5);
  check('tagged -> 5', true);
  await page.click('[data-tagdone]');

  // 폴더에 담으면 원본까지 보관되는지: 실제 파일 하나를 사용자 폴더에 담기
  await page.evaluate(() => { const p = state.photos.find(x => x.name === 'dup_1.jpg'); toggleThemeOn(p, '보관테스트'); });

  // 폴더 ZIP 내보내기: 만들어진 zip을 파이썬으로 무결성 검사(CRC)
  check('folder view has save button', (await page.locator('#themeBody').textContent()).includes('휴대폰에 저장'));
  const zres = await page.evaluate(async () => {
    const ps = state.photos.filter(p => !p.trash && themesOf(p).includes('음식') && p.file);
    const entries = ps.map(p => ({ name: p.name, blob: p.file, ms: p.date }));
    const b = await buildZip(entries, () => {});
    const ab = await b.arrayBuffer();
    let s = ''; const u = new Uint8Array(ab);
    for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode.apply(null, u.subarray(i, i + 0x8000));
    return { n: entries.length, b64: btoa(s) };
  });
  fs.writeFileSync(path.join(SP, 'export_test.zip'), Buffer.from(zres.b64, 'base64'));
  const py = require('child_process').spawnSync('python3', ['-c',
    "import zipfile;z=zipfile.ZipFile('" + SP + "/export_test.zip');print(z.testzip());print(len(z.namelist()))"], { encoding: 'utf8' });
  const pyl = (py.stdout || '').trim().split('\n');
  check('export zip valid crc', pyl[0] === 'None' && +pyl[1] === zres.n && zres.n >= 5, py.stdout + py.stderr);

  // 4) 정리 탭
  await page.click('#tabbar button[data-go="clean"]');
  const cleanTxt = await page.locator('#cleanHome').textContent();
  check('clean home has dup card', cleanTxt.includes('중복'));
  await page.click('[data-clean="dup"]');
  await page.click('[data-dupall]');
  const badge = await page.locator('#trashBdg').textContent();
  check('trash badge > 0', +badge > 0, badge);
  await page.click('[data-cleanback]');
  await page.click('#btnTrashList');
  const listTxt = await page.locator('#trashListText').textContent();
  check('trash list has dup file', listTxt.includes('dup_'), listTxt.slice(0, 120));
  await page.click('#modalClose');

  // 5) 검색 탭
  await page.click('#tabbar button[data-go="search"]');
  await page.fill('#q', '음식');
  await page.waitForTimeout(400);
  const meta1 = await page.locator('#searchMeta').textContent();
  check('search 음식 >= 4', parseInt(meta1) >= 4, meta1);
  await page.fill('#q', '');
  await page.click('[data-stype="shot"]');
  await page.waitForTimeout(250);
  check('search shot = 3', (await page.locator('#searchMeta').textContent()).startsWith('3'), await page.locator('#searchMeta').textContent());
  await page.click('[data-syear="2024"]');
  await page.click('[data-stype=""]');
  await page.waitForTimeout(250);
  check('search year 2024 = 3', (await page.locator('#searchMeta').textContent()).startsWith('3'));
  await page.click('[data-syear=""]');

  // 6) 뷰어
  await page.click('#tabbar button[data-go="library"]');
  await page.locator('#libGroups .tile').first().click();
  await page.waitForSelector('#viewer:not([hidden])');
  check('viewer image', await page.locator('#vStage img').count() > 0);
  await page.click('#vFav');
  check('viewer fav on', await page.locator('#vFav.on').count() === 1);
  await page.click('#vNext');
  await page.click('#vClose');

  // 7) 새로고침: 자동 저장 복원 + 원본 재연결 + 백업 + 정리 완료 비우기
  const trashCached = await page.evaluate(() => state.photos.filter(p => p.trash && !p.sample).length);
  await page.reload();
  await page.waitForFunction(() => typeof state !== "undefined" && state.photos.length === 10, null, { timeout: 20000 });
  check('cache restored 10', true);
  check('cached thumbs all', await page.evaluate(() => state.photos.every(p => !!p.thumb)));
  check('cached month 2024-05', await page.locator('#libGroups').textContent().then(tx => tx.includes('2024년 5월')));
  const trashAfter = await page.evaluate(() => state.photos.filter(p => p.trash).length);
  check('trash restored from cache', trashAfter === trashCached && trashAfter >= 1, trashCached + '/' + trashAfter);
  check('dups recomputed from cache', await page.evaluate(() => state.dupGroups.length) >= 1);
  // 재시작 후에도 폴더 사진의 원본이 보관되어 내보내기 가능한지
  const orig = await page.evaluate(async () => {
    const p = state.photos.find(x => x.name === 'dup_1.jpg');
    const b = await idbGetOriginal(recKey(p));
    return b ? b.size : 0;
  });
  check('original persisted for folder photo', orig > 1000, 'size=' + orig);
  const recover = await page.evaluate(async () => {
    const ps = state.photos.filter(p => themesOf(p).includes('보관테스트'));
    for (const p of ps) if (!p.file) { const b = await idbGetOriginal(recKey(p)); if (b) p.file = b; }
    return { n: ps.length, ok: ps.filter(p => p.file).length };
  });
  check('export recover from originals', recover.n === 1 && recover.ok === 1, JSON.stringify(recover));
  // 캐시 상태에서 뷰어 열기 (원본 없음 → 미리보기 + 안내)
  await page.locator('#libGroups .tile').first().click();
  await page.waitForSelector('#viewer:not([hidden])');
  check('viewer hint without original', await page.locator('#vStage .vHint').count() === 1);
  await page.click('#vClose');
  // 원본 재연결
  await page.setInputFiles('#fileIn', [path.join(PICS, 'dup_2.jpg'), path.join(PICS, 'dup_3_slight.jpg')]);
  await page.waitForFunction(() => !state.importing && ['dup_2.jpg','dup_3_slight.jpg'].every(n => state.photos.some(p => p.name === n && p.file)), null, { timeout: 15000 });
  check('relink keeps 10', await page.evaluate(() => state.photos.length) === 10);
  // 백업 만들기 → 내용 조작 → 불러오기
  const backup = await page.evaluate(() => buildBackupJSON());
  const bk = JSON.parse(backup);
  check('backup has records', Object.keys(bk.records).length >= 10, String(Object.keys(bk.records).length));
  const dupKey = Object.keys(bk.records).find(k => k.startsWith('dup_2.jpg|'));
  bk.records[dupKey].manT = ['백업테마'];
  const bkPath = path.join(SP, 'backup_test.json');
  fs.writeFileSync(bkPath, JSON.stringify(bk));
  await page.locator('#backupIn').setInputFiles(bkPath);
  await page.waitForTimeout(500);
  check('backup theme applied', await page.evaluate(() => { const p = state.photos.find(q => q.name === 'dup_2.jpg'); return !!p && p.manT.has('백업테마'); }));
  // 정리 완료 → 목록 비우기 → 새로고침 후에도 유지
  await page.click('#tabbar button[data-go="clean"]');
  await page.click('[data-clean="trash"]');
  await page.click('[data-trashdone]');
  await page.waitForTimeout(300);
  const afterDone = await page.evaluate(() => state.photos.length);
  check('trashdone removed', afterDone === 10 - trashAfter, afterDone + ' vs ' + (10 - trashAfter));
  await page.reload();
  await page.waitForFunction(() => typeof state !== "undefined" && !state.importing, null, { timeout: 20000 });
  await page.waitForTimeout(800);
  const persisted = await page.evaluate(() => state.photos.length);
  check('removal persisted', persisted === afterDone, persisted + ' vs ' + afterDone);

  console.log('\n=== OK (' + R.ok.length + ') ===\n' + R.ok.join('\n'));
  console.log('\n=== FAIL (' + R.fail.length + ') ===\n' + (R.fail.join('\n') || '(none)'));
  console.log('\n=== JS ERRORS (' + errors.length + ') ===\n' + (errors.join('\n') || '(none)'));
  await browser.close();
  process.exit(R.fail.length || errors.length ? 1 : 0);
})();
