"""Pure contract, response timing and local validation cost checks."""
import asyncio
import importlib
import json
from pathlib import Path
import sys
import time
from types import ModuleType

root=Path(__file__).resolve().parents[1]
package=ModuleType('image_task_fixture');package.__path__=[str(root/'extensions/astrbot_plugin_qq_persona_models')];sys.modules[package.__name__]=package
checks=importlib.import_module('image_task_fixture.image_task_checks')
contract=importlib.import_module('image_task_fixture.image_task_contract')
result=asyncio.run(checks.verify_image_tasks());assert result['passed'],result
samples=[]
for i in range(10000):
    args={'image_task':{'operation':'edit','reason':'same source','independent_quote':''},'reference_ids':['A'],'reference_notes':[{'image_id':'A','purpose':'original identity'}]}
    start=time.perf_counter();contract.validate_task(args,'修改',{});samples.append((time.perf_counter()-start)*1000)
result['validation_p95_ms']=round(sorted(samples)[9499],4)
assert result['validation_p95_ms']<1
print(json.dumps(result,ensure_ascii=False,indent=2))
