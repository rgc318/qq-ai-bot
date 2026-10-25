"""Apply a narrow, repeatable OmniDraw frontend compatibility fix.

Run inside the AstrBot container with --root pointing to the installed plugin.
Only static assets change; runtime configuration and model calls are untouched.
"""
import argparse
import hashlib
import json
from pathlib import Path


def patched_script(source):
    for statement in (
        'byId("opt_astrbot").checked = Boolean(state.optimizer_config.use_astrbot_provider);',
        'state.optimizer_config.use_astrbot_provider = byId("opt_astrbot").checked;',
    ):
        replacement='if (byId("opt_astrbot")) '+statement
        if replacement in source:
            continue
        if source.count(statement)!=1:
            raise ValueError('Unexpected OmniDraw frontend; missing or ambiguous compatibility target')
        source=source.replace(statement,replacement,1)
    return source


def apply(root,backup,dry_run=False):
    page=root/'pages/插件配置'
    script=page/'app.js';html=page/'index.html'
    originals={script:script.read_text(encoding='utf-8'),html:html.read_text(encoding='utf-8')}
    next_script=patched_script(originals[script])
    old='./app.js?v=3.4.0'
    new=old+'-qq-page-fix1'
    next_html=originals[html]
    if new not in next_html:
        if next_html.count(old)!=1:raise ValueError('Unexpected script URL; refusing partial patch')
        next_html=next_html.replace(old,new,1)
    updates={script:next_script,html:next_html}
    changed=[]
    for path,source in updates.items():
        if originals[path]==source:continue
        changed.append(path.name)
        if not dry_run:
            backup.mkdir(parents=True,exist_ok=True)
            before=originals[path].encode('utf-8')
            target=backup/(path.name+'.'+hashlib.sha256(before).hexdigest()[:12]+'.before')
            if not target.exists():target.write_bytes(before)
            path.write_text(source,encoding='utf-8')
    return {'changed_assets':changed,'dry_run':dry_run,'runtime_config_writes':0,'model_calls':0}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--backup',type=Path,required=True)
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    print(json.dumps(apply(args.root,args.backup,args.dry_run),ensure_ascii=False))
