"""Real browser checks; run with .venv/bin/python tests/test_browser.py."""
import json
import os
from pathlib import Path
import unittest
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(ROOT / '.browsers'))
TARGET_URL = os.environ.get('TEST_BASE_URL', ROOT.joinpath('index.html').as_uri())
BROWSER = os.environ.get('TEST_BROWSER', 'chromium')
RESULTS = ROOT / 'test-results' / (BROWSER + ('-http' if TARGET_URL.startswith('http') else '-file'))

def open_intro(page):
    """Progress, export/import, save status and the view switch live inside the
    collapsed intro; expand it before touching any of them."""
    if not page.evaluate("document.getElementById('intro-collapse').open"):
        page.locator('#intro-collapse > summary').click()


def ensure_cards_view(page):
    """The table is the default view now; switch to cards for tests that drive
    the per-word dropdown and note fields directly."""
    open_intro(page)
    if page.locator('#cards-view').is_hidden():
        page.locator('#view-cards').click()


def open_group(page, index=0, container='.main-groups'):
    """Groups render collapsed; open one before touching its rows."""
    ensure_cards_view(page)
    if page.locator(f'{container} > .group').nth(index).get_attribute('open') is None:
        page.locator(f'{container} > .group > summary').nth(index).click()


class FormTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = getattr(cls.pw, BROWSER).launch()
        print(f'Browser: {BROWSER} {cls.browser.version}; target: {TARGET_URL}', flush=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1440, 'height': 1000})
        self.page = self.context.new_page()
        self.page.goto(TARGET_URL)

    def tearDown(self):
        self.context.close()

    def open_group(self, index=0, container='.main-groups'):
        open_group(self.page, index, container)

    def test_01_table_and_labels(self):
        self.assertEqual(self.page.locator('select[data-answer]').count(), 148)
        self.assertEqual(self.page.locator('.main-groups > .group').count(), 5)
        self.assertEqual(self.page.locator('.thought-groups > .group').count(), 5)
        self.assertEqual(self.page.locator('option[value="remember"]').count(), 148)
        self.assertEqual(self.page.locator('option[value="not-yet"]').count(), 148)
        self.assertEqual(self.page.locator('.item-name', has_text='Вина, стыд').count(), 1)
        ids = self.page.locator('select[data-answer]').evaluate_all('(els) => els.map(e=>e.dataset.answer)')
        self.assertEqual(len(ids), len(set(ids)))

    def test_02_autosave_reload(self):
        self.open_group()
        self.page.locator('#answer-main-0-0').select_option('remember')
        self.page.locator('[data-id="main-0-0"] .note > summary').click()
        self.page.locator('#note-main-0-0').fill('Тестовая заметка\nНовая строка')
        self.page.reload()
        self.assertEqual(self.page.locator('#answer-main-0-0').input_value(), 'remember')
        self.assertEqual(self.page.locator('#note-main-0-0').input_value(), 'Тестовая заметка\nНовая строка')
        self.assertEqual(self.page.locator('#progress-text').inner_text(), 'Отмечено 1 из 148')
        self.assertEqual(self.page.locator('.main-groups > .group').first.locator('.tally').all_text_contents(),
                         ['1 вспоминаю', '0 пока нет', '15 без ответа'])
        self.assertIsNotNone(self.page.evaluate("localStorage.getItem('emotions-form:v1')"))

    def download(self, selector):
        with self.page.expect_download(timeout=30000) as pending:
            self.page.locator(selector).click()
        return Path(pending.value.path()).read_text(encoding='utf-8-sig')

    def upload(self, data):
        raw = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
        self.page.locator('#import-file').set_input_files({'name': 'backup.json', 'mimeType': 'application/json', 'buffer': raw.encode()})

    def test_03_export_import_roundtrip(self):
        self.open_group()
        self.page.locator('#answer-main-0-0').select_option('remember')
        self.page.locator('[data-id="main-0-0"] .note > summary').click()
        self.page.locator('#note-main-0-0').fill('Тестовая запись')
        exported = json.loads(self.download('#export-json'))
        self.assertEqual(exported['answers']['main-0-0'], {'state': 'remember', 'note': 'Тестовая запись'})
        self.page.once('dialog', lambda dialog: dialog.accept())
        self.page.locator('#reset').click()
        self.assertEqual(self.page.locator('#answer-main-0-0').input_value(), 'unanswered')
        self.upload(exported)
        expect(self.page.locator('#answer-main-0-0')).to_have_value('remember')
        self.assertEqual(json.loads(self.download('#export-json')), exported)
        txt = self.download('#export-txt')
        self.assertIn('Бешенство — Вспоминаю', txt)
        self.assertIn('Тестовая запись', txt)
        self.assertIn('Страх оценки — Без ответа', txt)
        self.assertIn('Мысли (или состояния человека), вызванные гаммой чувств', txt)

    def test_04_source_fidelity(self):
        source = json.loads((ROOT / 'tests/source.json').read_text())
        for section, selector in [('main', '.main-groups'), ('thoughts', '.thought-groups')]:
            for index, names in enumerate(source[section]):
                group = self.page.locator(selector + ' > .group').nth(index)
                self.assertEqual(group.locator('.item-name').all_text_contents(), names)
                self.assertEqual(group.locator('.group-title').inner_text(), source['groups'][index])
        self.assertEqual(self.page.locator('#fears .item-name').all_text_contents(), source['fears'])

    def test_05_import_rejection_and_xss(self):
        open_intro(self.page)
        clean = json.loads(self.download('#export-json'))
        bad_cases = ['{bad', json.dumps(clean) + ' trailing', 'x' * (2 * 1024 * 1024 + 1)]
        for change in [lambda x: x.update(version=2), lambda x: x.update(extra=1),
                       lambda x: x['answers'].update(unknown={'state': 'remember', 'note': ''}),
                       lambda x: x['answers'].pop('main-0-0'),
                       lambda x: x['answers']['main-0-0'].update(state='bad'),
                       lambda x: x['answers']['main-0-0'].update(state=['remember']),
                       lambda x: x['answers']['main-0-0'].update(note=12),
                       lambda x: x['answers']['main-0-0'].update(note='x' * 2001),
                       lambda x: x['answers']['main-0-0'].update(extra='bad')]:
            case = json.loads(json.dumps(clean)); change(case); bad_cases.append(case)
        for case in bad_cases:
            self.page.locator('#notice').evaluate('(el)=>el.textContent=""')
            self.upload(case)
            expect(self.page.locator('#notice')).to_contain_text('Копия не загружена')
            self.assertEqual(self.page.locator('#progress').get_attribute('value'), '0')
            self.assertIsNone(self.page.evaluate("localStorage.getItem('emotions-form:v1')"))
        payload = '<img src=x onerror="window.XSS=1"><script>window.XSS=2</script>'
        clean['answers']['main-0-0'] = {'state': 'not-yet', 'note': payload}
        self.upload(clean)
        expect(self.page.locator('#answer-main-0-0')).to_have_value('not-yet')
        self.assertEqual(self.page.locator('#note-main-0-0').input_value(), payload)
        self.assertIsNone(self.page.evaluate('window.XSS'))
        self.assertEqual(self.page.locator('.item img,.item script').count(), 0)
        self.assertEqual(json.loads(self.download('#export-json')), clean)

    def test_06_confirmations(self):
        self.open_group()
        blank = json.loads(self.download('#export-json'))
        self.page.locator('#answer-main-0-0').select_option('remember')
        self.page.once('dialog', lambda dialog: dialog.dismiss())
        self.upload(blank)
        expect(self.page.locator('#notice')).to_contain_text('Загрузка отменена')
        self.assertEqual(self.page.locator('#answer-main-0-0').input_value(), 'remember')
        self.page.once('dialog', lambda dialog: dialog.dismiss())
        self.page.locator('#reset').click()
        self.assertEqual(self.page.locator('#answer-main-0-0').input_value(), 'remember')
        self.page.once('dialog', lambda dialog: dialog.accept())
        self.upload(blank)
        expect(self.page.locator('#answer-main-0-0')).to_have_value('unanswered')
        self.page.reload()
        self.assertEqual(self.page.locator('#answer-main-0-0').input_value(), 'unanswered')

    def test_07_corrupt_storage_preserved_and_recovery(self):
        self.open_group()
        damaged = '{broken secret data'
        self.page.evaluate('(raw)=>localStorage.setItem("emotions-form:v1",raw)', damaged)
        self.page.reload()
        self.assertTrue(self.page.locator('#storage-warning').is_visible())
        self.open_group()
        self.page.locator('#answer-main-0-0').select_option('remember')
        self.assertEqual(self.page.evaluate("localStorage.getItem('emotions-form:v1')"), damaged)
        self.assertEqual(self.download('#download-damaged'), damaged)
        self.page.once('dialog', lambda dialog: dialog.dismiss())
        self.page.locator('#recover-storage').click()
        self.assertEqual(self.page.evaluate("localStorage.getItem('emotions-form:v1')"), damaged)
        self.page.once('dialog', lambda dialog: dialog.accept())
        self.page.locator('#recover-storage').click()
        self.assertFalse(self.page.locator('#storage-warning').is_visible())
        self.page.reload()
        self.assertEqual(self.page.locator('#answer-main-0-0').input_value(), 'remember')

    def test_08_blocked_and_full_storage(self):
        for method in ['getItem', 'setItem']:
            context = self.browser.new_context()
            context.add_init_script(f"Storage.prototype.{method}=function(){{throw new DOMException('blocked','QuotaExceededError')}}")
            page = context.new_page(); page.goto(TARGET_URL)
            open_group(page)
            page.locator('#answer-main-0-0').select_option('remember')
            self.assertTrue(page.locator('#storage-warning').is_visible())
            self.assertIn('приостановлено', page.locator('#save-status').inner_text())
            with page.expect_download() as pending:
                page.locator('#export-json').click()
            data = json.loads(Path(pending.value.path()).read_text())
            self.assertEqual(data['answers']['main-0-0']['state'], 'remember')
            context.close()

    def test_09_layout_and_touch_targets(self):
        out = RESULTS; out.mkdir(parents=True, exist_ok=True)
        for width in [320, 390, 768, 1440]:
            self.page.set_viewport_size({'width': width, 'height': 960})
            self.page.reload()
            ensure_cards_view(self.page)
            self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth > innerWidth'), width)
            self.assertIsNone(self.page.locator('.main-groups > .group').first.get_attribute('open'), width)
            if width < 900:
                self.assertIsNone(self.page.locator('.main-groups > .group').nth(1).get_attribute('open'))
                self.page.locator('.main-groups > .group > summary').nth(1).click()
                self.assertTrue(self.page.locator('#answer-main-1-0').is_visible())
                self.page.locator('[data-id="main-1-0"] .note > summary').click()
                self.page.locator('#note-main-1-0').fill('ДлиннаяЗаметка' * 100)
                self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth > innerWidth'), width)
                box = self.page.locator('[data-id="main-1-0"] .note > summary').bounding_box()
                self.assertGreaterEqual(box['height'], 44)
            else:
                xs = [self.page.locator('.main-groups > .group').nth(i).bounding_box()['x'] for i in range(5)]
                self.assertEqual(xs, sorted(set(xs)))
                self.assertEqual(len(self.page.locator('.main-groups').evaluate('(el)=>getComputedStyle(el).gridTemplateColumns').split()), 5)
            self.page.evaluate('localStorage.clear()')
            self.page.reload()
            ensure_cards_view(self.page)
            self.page.evaluate('window.scrollTo(0,0)')
            self.page.screenshot(path=str(out / f'layout-{width}.png'), full_page=True)
            if width in [390, 1440]:
                self.page.screenshot(path=str(out / ('mobile.png' if width == 390 else 'desktop.png')))
                self.page.locator('#feelings').evaluate('(el)=>window.scrollTo(0,el.getBoundingClientRect().top+window.scrollY)')
                self.page.screenshot(path=str(out / ('mobile-form.png' if width == 390 else 'desktop-form.png')))

    def test_10_no_requests_console_or_url_answers(self):
        requests=[]; errors=[]
        self.page.on('request', lambda request: requests.append((request.url, request.resource_type, request.method)))
        self.page.on('pageerror', lambda error: errors.append(str(error)))
        self.page.reload()
        self.open_group()
        self.page.locator('#answer-main-0-0').select_option('remember')
        self.assertEqual(requests, [(self.page.url, 'document', 'GET')])
        self.assertEqual(errors, [])
        self.assertNotIn('?', self.page.url)
        policy = self.page.locator('meta[http-equiv="Content-Security-Policy"]').get_attribute('content')
        for directive in ["connect-src 'none'", "base-uri 'none'", "form-action 'none'"]:
            self.assertIn(directive, policy)

    def test_11_conflicting_storage_is_not_overwritten(self):
        self.open_group()
        self.page.locator('#answer-main-0-0').select_option('remember')
        original = self.page.evaluate("localStorage.getItem('emotions-form:v1')")
        other = json.loads(original); other['answers']['main-0-0']['state'] = 'not-yet'
        self.page.evaluate('(x)=>localStorage.setItem("emotions-form:v1",x)', json.dumps(other))
        self.page.locator('#answer-main-0-1').select_option('remember')
        self.assertTrue(self.page.locator('#storage-warning').is_visible())
        saved = json.loads(self.page.evaluate("localStorage.getItem('emotions-form:v1')"))
        self.assertEqual(saved, other)

    def test_12_mobile_keyboard_and_text_size(self):
        context = self.browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True, device_scale_factor=3)
        page = context.new_page(); page.goto(TARGET_URL)
        open_group(page)
        self.assertGreaterEqual(page.locator('#answer-main-0-0').evaluate('(el)=>parseFloat(getComputedStyle(el).fontSize)'), 16)
        page.locator('#answer-main-0-0').select_option('not-yet')
        page.locator('[data-id="main-0-0"] .note > summary').tap()
        page.locator('#note-main-0-0').fill('Проверка мобильного ввода')
        page.reload()
        self.assertEqual(page.locator('#note-main-0-0').input_value(), 'Проверка мобильного ввода')
        self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'))
        context.close()
        self.page.set_viewport_size({'width': 390, 'height': 844})
        ensure_cards_view(self.page)
        summary = self.page.locator('.main-groups > .group > summary').nth(1)
        summary.focus(); self.page.keyboard.press('Enter')
        self.assertTrue(self.page.locator('#answer-main-1-0').is_visible())
        self.page.locator('#answer-main-1-0').focus(); self.page.keyboard.press('ArrowDown')
        self.assertEqual(self.page.locator('#answer-main-1-0').input_value(), 'remember')

    def test_13_storage_reminder_reachable_behind_collapsed_intro(self):
        """The disclaimer no longer sits on the first screen (the table does
        now, see test_19), but it must still exist, intact, once expanded."""
        for width in [320, 390]:
            self.page.set_viewport_size({'width': width, 'height': 844})
            self.page.evaluate('localStorage.clear()')
            self.page.reload()
            self.assertFalse(self.page.evaluate("document.getElementById('intro-collapse').open"), width)
            open_intro(self.page)
            reminder = self.page.locator('#storage-reminder')
            expect(reminder).to_be_visible()
            for phrase in ['браузере', 'устройстве', 'удалить', 'JSON']:
                self.assertIn(phrase, reminder.inner_text())

    def test_14_note_never_exceeds_stored_limit(self):
        """A note longer than the limit must never be persisted: the app would
        refuse to load its own copy and would lock autosave."""
        self.page.evaluate("""()=>{const t=document.getElementById('note-main-0-0');
            t.value='a'.repeat(2500); t.dispatchEvent(new Event('input'));}""")
        stored = self.page.evaluate("()=>JSON.parse(localStorage.getItem('emotions-form:v1')).answers['main-0-0'].note.length")
        self.assertEqual(stored, 2000)
        self.assertEqual(len(self.page.locator('#note-main-0-0').input_value()), 2000)
        self.page.reload()
        self.assertFalse(self.page.locator('#storage-warning').is_visible())
        self.assertEqual(len(self.page.locator('#note-main-0-0').input_value()), 2000)
        self.assertIn('Осталось 0 из 2 000', self.page.locator('#help-main-0-0').text_content())
        self.page.evaluate("""()=>{const t=document.getElementById('note-main-0-0');
            t.value='a'.repeat(1700); t.dispatchEvent(new Event('input'));}""")
        self.assertIn('Осталось 300 из 2 000', self.page.locator('#help-main-0-0').text_content())
        self.page.evaluate("""()=>{const t=document.getElementById('note-main-0-0');
            t.value='a'.repeat(10); t.dispatchEvent(new Event('input'));}""")
        self.assertIn('До 2 000 символов', self.page.locator('#help-main-0-0').text_content())
        self.assertEqual(self.page.locator('#progress-text').text_content(), 'Отмечено 0 из 148')

    def test_15_groups_start_collapsed_and_tally_every_state(self):
        for index in range(5):
            self.assertIsNone(self.page.locator('.main-groups > .group').nth(index).get_attribute('open'))
            self.assertIsNone(self.page.locator('.thought-groups > .group').nth(index).get_attribute('open'))
        group = self.page.locator('.main-groups > .group').first
        self.assertEqual(group.locator('.tally').all_text_contents(),
                         ['0 вспоминаю', '0 пока нет', '16 без ответа'])
        self.open_group()
        self.assertIsNotNone(group.get_attribute('open'))
        self.assertTrue(self.page.locator('#answer-main-0-0').is_visible())
        self.page.locator('#answer-main-0-0').select_option('remember')
        self.page.locator('#answer-main-0-1').select_option('not-yet')
        self.page.locator('#answer-main-0-2').select_option('not-yet')
        self.assertEqual(group.locator('.tally').all_text_contents(),
                         ['1 вспоминаю', '2 пока нет', '13 без ответа'])
        self.assertEqual(sum(int(t.split()[0]) for t in group.locator('.tally').all_text_contents()), 16)
        # a group opened by hand stays open across a width change
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.page.wait_for_timeout(120)
        self.assertIsNotNone(group.get_attribute('open'))
        # and collapsing is available on a wide screen too
        self.page.set_viewport_size({'width': 1440, 'height': 1000})
        self.page.locator('.main-groups > .group > summary').first.click()
        self.assertIsNone(group.get_attribute('open'))

    def test_16_max_fill_export_stays_importable(self):
        """NOTE_MAX and the 2 MB import cap are coupled: the fullest form the UI
        allows must still produce a backup this same form accepts."""
        self.page.evaluate("""()=>{
            document.querySelectorAll('select[data-answer]').forEach(s=>{s.value='remember';s.dispatchEvent(new Event('change'));});
            document.querySelectorAll('textarea[id^=note-]').forEach(t=>{t.value='ы'.repeat(2000);t.dispatchEvent(new Event('input'));});
        }""")
        open_intro(self.page)
        self.assertEqual(self.page.locator('#progress-text').text_content(), 'Отмечено 148 из 148')
        raw = self.download('#export-json')
        self.assertLess(len(raw.encode('utf-8')), 2 * 1024 * 1024)
        self.page.once('dialog', lambda dialog: dialog.accept())
        self.page.locator('#reset').click()
        self.assertEqual(self.page.locator('#progress-text').text_content(), 'Отмечено 0 из 148')
        self.upload(raw)
        expect(self.page.locator('#progress-text')).to_have_text('Отмечено 148 из 148')
        self.assertEqual(len(self.page.locator('#note-main-0-0').input_value()), 2000)

    def test_17_table_view_controls_and_persistence(self):
        open_intro(self.page)
        self.page.locator('#view-table').click()
        self.assertTrue(self.page.locator('#table-view').is_visible())
        self.assertFalse(self.page.locator('#cards-view').is_visible())
        self.assertEqual(self.page.locator('.cell').count(), 148)
        cell = self.page.locator('.cell[data-id="main-0-0"]')
        # plus / minus toggle, and the same answer shows up in the cards view controls
        cell.locator('.cell-plus').click()
        self.assertEqual(cell.get_attribute('data-state'), 'remember')
        self.assertEqual(cell.locator('.cell-plus').get_attribute('aria-pressed'), 'true')
        self.assertEqual(self.page.locator('#answer-main-0-0').input_value(), 'remember')
        cell.locator('.cell-plus').click()
        self.assertEqual(cell.get_attribute('data-state'), 'unanswered')
        cell.locator('.cell-minus').click()
        self.assertEqual(cell.get_attribute('data-state'), 'not-yet')
        self.assertEqual(cell.locator('.cell-minus').get_attribute('aria-pressed'), 'true')
        self.assertEqual(cell.locator('.cell-plus').get_attribute('aria-pressed'), 'false')
        # header tallies follow
        header = self.page.locator('#table-grid .hcell').first
        self.assertEqual(header.locator('.tally').all_text_contents(), ['0 вспоминаю', '1 пока нет', '15 без ответа'])
        # note through the sheet
        self.assertEqual(cell.locator('.cell-note').get_attribute('data-has-note'), 'false')
        cell.locator('.cell-note').click()
        expect(self.page.locator('#note-sheet')).to_be_visible()
        self.assertEqual(self.page.locator('#sheet-title').inner_text(), 'Бешенство')
        self.assertEqual(self.page.evaluate('document.activeElement.id'), 'sheet-note')
        self.page.keyboard.type('Табличная заметка')
        self.assertEqual(self.page.locator('#note-main-0-0').input_value(), 'Табличная заметка')
        self.page.keyboard.press('Escape')
        expect(self.page.locator('#note-sheet')).to_be_hidden()
        self.assertEqual(self.page.evaluate('document.activeElement.className'), 'cell-btn cell-note')
        self.assertEqual(cell.locator('.cell-note').get_attribute('data-has-note'), 'true')
        self.assertIn('есть запись', cell.locator('.cell-note').get_attribute('aria-label'))
        # everything is in the one stored packet, and the chosen view survives a reload
        self.page.reload()
        self.assertTrue(self.page.locator('#table-view').is_visible())
        self.assertEqual(self.page.locator('#view-table').get_attribute('aria-pressed'), 'true')
        self.assertEqual(cell.get_attribute('data-state'), 'not-yet')
        self.assertEqual(cell.locator('.cell-note').get_attribute('data-has-note'), 'true')
        exported = json.loads(self.download('#export-json'))
        self.assertEqual(exported['answers']['main-0-0'], {'state': 'not-yet', 'note': 'Табличная заметка'})
        self.assertNotIn('view', exported)
        # keyboard: the cell buttons are ordinary buttons
        cell.locator('.cell-plus').focus(); self.page.keyboard.press('Enter')
        self.assertEqual(cell.get_attribute('data-state'), 'remember')
        self.page.locator('#view-cards').click()
        self.assertTrue(self.page.locator('#cards-view').is_visible())
        self.page.reload()
        self.assertTrue(self.page.locator('#cards-view').is_visible())

    def test_18_table_view_per_screen(self):
        """Narrow screens: the whole feelings block fits one screen above the fixed bar and a tap only selects;
        wide screens: three buttons per cell and no horizontal scroll."""
        MAIN_BLOCK = """()=>{const cells=[...document.querySelectorAll('#table-grid .cell, #table-grid .cell-empty')].filter(c=>parseInt(c.style.gridRow)<=23);
            const top=document.querySelector('#table-view .section-heading').getBoundingClientRect().top;
            return Math.round(Math.max(...cells.map(c=>c.getBoundingClientRect().bottom))-top);}"""
        for width, height in [(360, 700), (390, 664), (844, 390), (1024, 768), (1440, 1000)]:
            self.page.set_viewport_size({'width': width, 'height': height})
            self.page.reload()
            self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth > innerWidth'), (width, height))
            self.assertFalse(self.page.evaluate("()=>{const s=document.getElementById('table-scroll');return s.scrollWidth>s.clientWidth+1;}"), (width, height))
            self.assertEqual(self.page.locator('#table-grid .hcell').count(), 10)
            compact = width < 900
            self.assertEqual(self.page.locator('#table-bar').is_visible(), compact, (width, height))
            self.assertEqual(self.page.locator('.cell[data-id="main-1-0"] .cell-minus').is_visible(), not compact, (width, height))
            if compact:
                if width < 400:  # phone portrait: the zoom controls and the header row land on the first screen
                    self.assertLess(self.page.locator('#table-grid .hcell').first.bounding_box()['y'], 60)
                self.page.locator('.cell[data-id="main-1-6"] .cell-pick').click()
                self.assertEqual(self.page.locator('.cell[data-id="main-1-6"]').get_attribute('data-state'), 'unanswered')
                self.assertEqual(self.page.locator('#bar-word').inner_text(), 'Ошарашенность')
                self.page.locator('#bar-plus').click()
                self.assertEqual(self.page.locator('.cell[data-id="main-1-6"]').get_attribute('data-state'), 'remember')
                self.assertEqual(self.page.locator('#answer-main-1-6').input_value(), 'remember')
                self.page.locator('#bar-note').click()
                expect(self.page.locator('#note-sheet')).to_be_visible()
                self.page.keyboard.type('из панели'); self.page.keyboard.press('Escape')
                self.assertEqual(self.page.locator('#bar-note').get_attribute('data-has-note'), 'true')
                self.assertEqual(self.page.evaluate('document.activeElement.id'), 'bar-note')
                for selector in ['#bar-minus', '#bar-plus', '#bar-note']:
                    box = self.page.locator(selector).bounding_box()
                    self.assertGreaterEqual(min(box['width'], box['height']), 44, (width, selector))
                self.assertEqual(self.page.locator('#table-grid .hcell').nth(1).locator('.tally').all_text_contents(),
                                 ['1 вспоминаю', '0 пока нет', '20 без ответа'])
                # note dot on the cell itself, and a clearly different fill for + and -
                self.assertEqual(self.page.locator('.cell[data-id="main-1-6"]').get_attribute('data-has-note'), 'true')
                plus_bg = self.page.locator('.cell[data-id="main-1-6"]').evaluate('el=>getComputedStyle(el).backgroundColor')
                self.page.locator('.cell[data-id="main-1-7"] .cell-pick').click(); self.page.locator('#bar-minus').click()
                minus_bg = self.page.locator('.cell[data-id="main-1-7"]').evaluate('el=>getComputedStyle(el).backgroundColor')
                self.assertNotEqual(plus_bg, minus_bg)
                # zoom: the smallest step puts the entire table on one screen above the bar; the choice is remembered
                WHOLE = """()=>{const top=document.querySelector('#table-view .section-heading').getBoundingClientRect().top;
                    const bottom=Math.max(...[...document.querySelectorAll('#table-grid > *')].map(c=>c.getBoundingClientRect().bottom));
                    return Math.round(bottom-top);}"""
                budget = self.page.evaluate("innerHeight - document.getElementById('table-bar').getBoundingClientRect().height")
                if width < 400:
                    self.assertLessEqual(self.page.evaluate(MAIN_BLOCK), budget, (width, height, 'default zoom: feelings block'))
                while not self.page.locator('#zoom-out').is_disabled():
                    self.page.locator('#zoom-out').click()
                if width < 400:
                    self.assertLessEqual(self.page.evaluate(WHOLE), budget, (width, height, 'smallest zoom: whole table'))
                self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth > innerWidth'))
                small = self.page.evaluate("getComputedStyle(document.querySelector('.cell-pick')).fontSize")
                self.page.reload()
                self.assertEqual(self.page.evaluate("getComputedStyle(document.querySelector('.cell-pick')).fontSize"), small)
                self.page.locator('#zoom-in').click(); self.page.locator('#zoom-in').click()
                self.assertGreater(float(self.page.evaluate("parseFloat(getComputedStyle(document.querySelector('.cell-pick')).fontSize)")), float(small[:-2]))
            else:
                box = self.page.locator('.cell[data-id="main-1-0"] .cell-minus').bounding_box()
                self.assertGreaterEqual(min(box['width'], box['height']), 40, (width, height))
            self.page.evaluate('localStorage.clear()')

    def test_19_table_and_smallest_zoom_are_default_intro_collapses(self):
        """Fresh load, no stored preferences: the table is what's immediately
        visible, already at its smallest zoom step, with the headline,
        instructions and export tucked behind a collapsed summary. Storage
        warnings are never hidden behind it, and an explicit choice (view,
        zoom or the intro itself) survives a reload."""
        self.page.set_viewport_size({'width': 390, 'height': 664})
        self.page.evaluate('localStorage.clear()')
        self.page.reload()
        self.assertFalse(self.page.evaluate("document.getElementById('intro-collapse').open"))
        self.assertTrue(self.page.locator('#table-view').is_visible())
        self.assertTrue(self.page.locator('#cards-view').is_hidden())
        self.assertEqual(self.page.locator('#view-table').get_attribute('aria-pressed'), 'true')
        self.assertTrue(self.page.locator('#zoom-out').is_disabled(), 'already at the smallest step')
        self.assertLess(self.page.locator('#table-grid .hcell').first.bounding_box()['y'], 60)
        # +/- read as plain words, on the mobile bar and (checked separately below) on desktop
        self.assertEqual(self.page.locator('#bar-minus').inner_text(), 'Не помню')
        self.assertEqual(self.page.locator('#bar-plus').inner_text(), 'Помню')

        # a corrupted copy still warns immediately, intro collapsed or not
        self.page.evaluate("(raw)=>localStorage.setItem('emotions-form:v1', raw)", '{broken')
        self.page.reload()
        self.assertFalse(self.page.evaluate("document.getElementById('intro-collapse').open"))
        self.assertTrue(self.page.locator('#storage-warning').is_visible())
        self.page.evaluate('localStorage.clear()')
        self.page.reload()

        # expanding the intro reaches cards; a quick link in cards leads straight back
        open_intro(self.page)
        self.assertTrue(self.page.locator('#export-json').is_visible())
        self.page.locator('#view-cards').click()
        self.assertTrue(self.page.locator('#cards-view').is_visible())
        self.page.locator('#cards-to-table').click()
        self.assertTrue(self.page.locator('#table-view').is_visible())

        # explicit choices (intro expanded, zoom raised) persist across a reload
        self.page.locator('#intro-collapse > summary').click()  # collapse it again
        self.assertFalse(self.page.evaluate("document.getElementById('intro-collapse').open"))
        self.page.locator('#intro-collapse > summary').click()  # and re-expand: this is the stored choice
        self.page.locator('#zoom-in').click()
        self.page.reload()
        self.assertTrue(self.page.evaluate("document.getElementById('intro-collapse').open"))
        self.assertFalse(self.page.locator('#zoom-out').is_disabled())

    def test_20_wide_cells_use_plain_words_not_symbols(self):
        cell = self.page.locator('.cell[data-id="main-0-0"]')
        self.assertEqual(cell.locator('.cell-minus').inner_text(), 'Не помню')
        self.assertEqual(cell.locator('.cell-plus').inner_text(), 'Помню')
        self.assertEqual(cell.locator('.cell-plus').get_attribute('aria-label'), 'Помню: Бешенство')
        self.assertEqual(cell.locator('.cell-minus').get_attribute('aria-label'), 'Не помню: Бешенство')
        self.assertNotIn('+', cell.locator('.cell-plus').inner_text())
        self.assertNotIn('−', cell.locator('.cell-minus').inner_text())

    def test_21_zoom_reflows_columns_past_five_across(self):
        """Beyond the point where 5 columns of bigger text would overflow, extra
        zoom steps shrink the number of categories shown side by side instead --
        3, then 2, then 1 -- wrapping the remaining categories into bands below.
        The interaction and the underlying answers stay identical throughout."""
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.page.reload()
        cols = lambda: len(self.page.evaluate(
            "getComputedStyle(document.getElementById('table-grid')).gridTemplateColumns.split(' ')"))
        expected = [5, 5, 5, 5, 5, 3, 2, 1]
        for level, want in enumerate(expected):
            self.assertEqual(cols(), want, level)
            self.assertEqual(self.page.locator('#table-grid .cell').count(), 148, level)
            self.assertEqual(self.page.locator('#table-grid .hcell').count(), 10, level)
            self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth > innerWidth'), level)
            if level < len(expected) - 1:
                self.page.locator('#zoom-in').click()
        self.assertTrue(self.page.locator('#zoom-in').is_disabled())

        # a category's tally is correct wherever its header currently sits, one column per row
        cell = self.page.locator('.cell[data-id="main-4-3"]')
        cell.locator('.cell-pick').click()
        self.page.locator('#bar-minus').click()
        self.assertEqual(self.page.locator('#table-grid .hcell[data-column="4"]').first.locator('.tally').all_text_contents(),
                         ['0 вспоминаю', '1 пока нет', '21 без ответа'])
        self.assertEqual(self.page.locator('#answer-main-4-3').input_value(), 'not-yet')

        # reflowing never leaves a stale selection highlighted on the rebuilt grid
        self.page.locator('#zoom-out').click()
        self.assertEqual(self.page.locator('.cell.selected').count(), 0)

        # a fresh reload keeps the chosen (reflowed) step
        self.page.reload()
        self.assertEqual(cols(), 2)
        self.assertEqual(self.page.locator('.cell[data-id="main-4-3"]').get_attribute('data-state'), 'not-yet')

        # going wide always shows all 5 columns with per-cell buttons regardless of the stored zoom step;
        # coming back to a narrow screen restores it
        COLS_JS = "getComputedStyle(document.getElementById('table-grid')).gridTemplateColumns.split(' ').length"
        self.page.set_viewport_size({'width': 1440, 'height': 1000})
        self.page.wait_for_function(f'({COLS_JS}) === 5')
        self.assertTrue(self.page.locator('.zoom').first.is_hidden())
        self.assertTrue(self.page.locator('.cell[data-id="main-0-0"] .cell-minus').is_visible())
        self.page.set_viewport_size({'width': 390, 'height': 844})
        self.page.wait_for_function(f'({COLS_JS}) === 2')

if __name__ == '__main__':
    unittest.main(verbosity=2)
