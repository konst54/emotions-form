"""Run file + temporary loopback HTTP tests and retain per-engine evidence."""
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / 'test-results'
RESULTS.mkdir(exist_ok=True)

class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        with (RESULTS / 'http-server.txt').open('a') as log:
            log.write(fmt % args + '\n')

server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Handler, directory=str(ROOT)))
thread = Thread(target=server.serve_forever, daemon=True)
thread.start()
failed = False
try:
    for protocol in os.environ.get('TEST_PROTOCOLS', 'file http').split():
        for engine in os.environ.get('TEST_ENGINES', 'chromium webkit').split():
            env = os.environ.copy()
            env['TEST_BROWSER'] = engine
            env.pop('TEST_BASE_URL', None)
            if protocol == 'http':
                env['TEST_BASE_URL'] = f'http://127.0.0.1:{server.server_port}/index.html'
            local_libs = ROOT / '.webkit-deps/usr/lib/x86_64-linux-gnu'
            if engine == 'webkit' and local_libs.exists():
                env['LD_LIBRARY_PATH'] = str(local_libs)
                env['PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS'] = '1'
                env['__EGL_VENDOR_LIBRARY_FILENAMES'] = str(ROOT / '.webkit-deps/usr/share/glvnd/egl_vendor.d/50_mesa.json')
                env['LIBGL_ALWAYS_SOFTWARE'] = '1'
                env['WEBKIT_DISABLE_COMPOSITING_MODE'] = '1'
            path = RESULTS / f'{engine}-{protocol}-final.txt'
            with path.open('w') as log:
                result = subprocess.run([sys.executable, 'tests/test_browser.py'], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=1200)
            print(f'{engine} {protocol}: exit {result.returncode}; {path}', flush=True)
            failed |= result.returncode != 0
finally:
    server.shutdown()
    server.server_close()
    thread.join()
sys.exit(int(failed))
