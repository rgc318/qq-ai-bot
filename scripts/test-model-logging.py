"""Run model tracing lifecycle tests without importing AstrBot or network."""
import asyncio
import json
from pathlib import Path
import sys
from types import ModuleType

package=ModuleType('astrbot_plugin_qq_persona_models')
package.__path__=[str(Path(__file__).resolve().parents[1]/'extensions/astrbot_plugin_qq_persona_models')]
sys.modules[package.__name__]=package
from astrbot_plugin_qq_persona_models.model_logging_checks import verify_model_logging
result=asyncio.run(verify_model_logging())
print(json.dumps(result,ensure_ascii=False,indent=2))
assert result['passed']
