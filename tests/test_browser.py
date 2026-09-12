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
        self.page.locator('#answer-main-0-0').select_option('remember')
        self.page.locator('[data-id="main-0-0"] .note > summary').click()
        self.page.locator('#note-main-0-0').fill('Тестовая заметка\nНовая строка')
        self.page.reload()
        self.assertEqual(self.page.locator('#answer-main-0-0').input_value(), 'remember')
        self.assertEqual(self.page.locator('#note-main-0-0').input_value(), 'Тестовая заметка\nНовая строка')
        self.assertEqual(self.page.locator('#progress-text').inner_text(), 'Отмечено 1 из 148')
        self.assertEqual(self.page.locator('.main-groups .group-count').first.inner_text(), '1 / 16')
        self.assertIsNotNone(self.page.evaluate("localStorage.getItem('emotions-form:v1')"))

    def download(self, selector):
        with self.page.expect_download(timeout=30000) as pending:
            self.page.locator(selector).click()
        return Path(pending.value.path()).read_text(encoding='utf-8-sig')

    def upload(self, data):
        raw = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
        self.page.locator('#import-file').set_input_files({'name': 'backup.json', 'mimeType': 'application/json', 'buffer': raw.encode()})

    def test_03_export_import_roundtrip(self):
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
        damaged = '{broken secret data'
        self.page.evaluate('(raw)=>localStorage.setItem("emotions-form:v1",raw)', damaged)
        self.page.reload()
        self.assertTrue(self.page.locator('#storage-warning').is_visible())
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
            self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth > innerWidth'), width)
            if width < 900:
                self.assertTrue(self.page.locator('.main-groups > .group').first.get_attribute('open') is not None)
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
        self.page.locator('#answer-main-0-0').select_option('remember')
        self.assertEqual(requests, [(self.page.url, 'document', 'GET')])
        self.assertEqual(errors, [])
        self.assertNotIn('?', self.page.url)
        policy = self.page.locator('meta[http-equiv="Content-Security-Policy"]').get_attribute('content')
        for directive in ["connect-src 'none'", "base-uri 'none'", "form-action 'none'"]:
            self.assertIn(directive, policy)

    def test_11_conflicting_storage_is_not_overwritten(self):
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
        self.assertGreaterEqual(page.locator('#answer-main-0-0').evaluate('(el)=>parseFloat(getComputedStyle(el).fontSize)'), 16)
        page.locator('#answer-main-0-0').select_option('not-yet')
        page.locator('[data-id="main-0-0"] .note > summary').tap()
        page.locator('#note-main-0-0').fill('Проверка мобильного ввода')
        page.reload()
        self.assertEqual(page.locator('#note-main-0-0').input_value(), 'Проверка мобильного ввода')
        self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'))
        context.close()
        self.page.set_viewport_size({'width': 390, 'height': 844})
        summary = self.page.locator('.main-groups > .group > summary').nth(1)
        summary.focus(); self.page.keyboard.press('Enter')
        self.assertTrue(self.page.locator('#answer-main-1-0').is_visible())
        self.page.locator('#answer-main-1-0').focus(); self.page.keyboard.press('ArrowDown')
        self.assertEqual(self.page.locator('#answer-main-1-0').input_value(), 'remember')

    def test_13_compact_intro_and_visible_storage_reminder(self):
        for width in [320, 390]:
            self.page.set_viewport_size({'width': width, 'height': 844})
            self.page.reload()
            first_answer = self.page.locator('#answer-main-0-0').bounding_box()
            self.assertLess(first_answer['y'], 844, 'First answer should be within the initial mobile screen')
            reminder = self.page.locator('#storage-reminder')
            expect(reminder).to_be_visible()
            self.assertLess(reminder.bounding_box()['y'], 400)
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
        self.assertEqual(self.page.locator('#progress-text').inner_text(), 'Отмечено 0 из 148')

if __name__ == '__main__':
    unittest.main(verbosity=2)
