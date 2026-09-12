"""Unprivileged Playwright dependency extraction, confined to this project."""
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
output = subprocess.run([str(root / '.venv/bin/python'), '-m', 'playwright', 'install-deps', '--dry-run', 'webkit'], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout
packages = [line.strip() for line in output.splitlines() if line.startswith('  ')]
if not packages:
    raise SystemExit('No package list returned; inspect install-deps --dry-run manually.')
cache = root / '.webkit-deps/debs'
cache.mkdir(parents=True, exist_ok=True)
subprocess.run(['apt-get', 'download', *packages], cwd=cache, check=True)
for package in sorted(cache.glob('*.deb')):
    subprocess.run(['dpkg-deb', '-x', str(package), str(cache.parent)], check=True)
print(f'Extracted {len(list(cache.glob("*.deb")))} packages under {cache.parent}')
# The bundled wrapper replaces LD_LIBRARY_PATH; retain the project-local path.
for wrapper in (root / '.browsers').glob('webkit-*/minibrowser-wpe/MiniBrowser'):
    text = wrapper.read_text()
    old = 'export LD_LIBRARY_PATH="${MYDIR}/lib:${MYDIR}/sys/lib"'
    new = 'export LD_LIBRARY_PATH="${MYDIR}/lib:${MYDIR}/sys/lib:${LD_LIBRARY_PATH:-}"'
    if old in text:
        wrapper.write_text(text.replace(old, new))
        print(f'Preserved inherited library path in {wrapper}')
