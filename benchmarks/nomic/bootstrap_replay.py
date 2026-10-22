"""Pinned-file offline replay bootstrap, private qualification scratch only."""
from pathlib import Path
import hashlib,json,sqlite3,subprocess,sys,urllib.request
ROOT=Path(__file__).resolve().parent
REVISION='9ab1f174388161f459005dde6dfeb3a7567ad796'
MANIFEST={'gregory_core/__init__.py': '250c81178f993c01f003d0d6a1b7da6d540c7959eb77b511717fee567632767c', 'gregory_core/memory.py': '63f8b3f4f5f73c7ea24a751b945ca77459bb5e8a6a7ab20e72a923b2bba82ad7', 'gregory_core/embeddings.py': 'fad300858c750a6197994b542757676bccb02db7ad074d2026c2278b117f6b95', 'benchmarks/nomic/run_benchmark.py': '09437ab458a93bfcd1bae5ec96b67dc94da310cfa3883c00d9e3c4b92ab41a11', 'benchmarks/nomic/test_benchmark.py': '1c4138838ecc64fefaff8a26fac79a1850f7bc37e398cd787689b025fb229c7a', 'benchmarks/nomic/fixtures.json': 'c9a72a8c9befc331d71c50f7104731e259d7bed8473fb05cbe5d0e36885f3dbf', 'benchmarks/nomic/FREEZE.json': '444ef8bbd5167d3cf5faf6f6893f2b579b8c8a4d250229b006fcd6486d2a3656'}
assert sys.version_info[:3]==(3,15,1), 'qualified Python gate'
assert sqlite3.sqlite_version=='3.53.4', 'qualified SQLite gate'
source=ROOT/'src';source.mkdir(exist_ok=True)
for name,h in MANIFEST.items():
 p=source/name;p.parent.mkdir(parents=True,exist_ok=True)
 url='https://raw.githubusercontent.com/connortheh09-art/Gregory-Garry-s-mod-bot/'+REVISION+'/'+name
 data=urllib.request.urlopen(url,timeout=30).read()
 assert hashlib.sha256(data).hexdigest()==h,'source hash mismatch'
 p.write_bytes(data)
(ROOT/'SOURCE_MANIFEST.json').write_text(json.dumps({'revision':REVISION,'files':MANIFEST},indent=2)+'\n')
command=[sys.executable,'-I','-S','-B',str(source/'benchmarks/nomic/run_benchmark.py'),'--captures',str(ROOT),'--out',str(ROOT/'results-initial')]
r=subprocess.run(command,capture_output=True,text=True)
(ROOT/'REPLAY_STDOUT.txt').write_text(r.stdout+'\nSTDERR\n'+r.stderr,encoding='utf-8')
print(r.stdout);print(r.stderr)
if r.returncode:raise SystemExit(r.returncode)
