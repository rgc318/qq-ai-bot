"""Read installed Python source only for offline, pinned SDK tests; no config/data."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
code='''from pathlib import Path
import json,base64
root=Path('/AstrBot/data/plugins/astrbot_plugin_omnidraw')
files={}
for path in root.rglob('*.py'):
 rel=path.relative_to(root)
 if any(x.startswith('.') or x in ('__pycache__','data','secrets','logs') for x in rel.parts):continue
 files[rel.as_posix()]=base64.b64encode(path.read_bytes()).decode()
print(json.dumps(files))
'''
result=subprocess.run(['wsl','-d','Ubuntu','--exec','docker','exec','qq-ai-bot-astrbot-1','python','-c',code],capture_output=True,text=True,encoding='utf-8',check=True)
files=json.loads(result.stdout);target=ROOT/'downloads/omnidraw-native-source'
target.mkdir(exist_ok=True);hashes={}
for name,encoded in files.items():
 path=target/name;assert path.resolve().is_relative_to(target.resolve())
 data=base64.b64decode(encoded);path.parent.mkdir(exist_ok=True,parents=True);path.write_bytes(data)
 hashes[name]=hashlib.sha256(data).hexdigest()
(target/'test-source-hashes.json').write_text(json.dumps(hashes,indent=2),encoding='utf-8')
print('Installed Python source snapshotted for offline tests:',len(hashes),'files; no runtime configuration copied')
