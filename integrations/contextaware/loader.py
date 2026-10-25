"""Load locked upstream algorithms without registering their global handlers.

Only filter.* registration decorators on Main are removed from the runtime AST.
Source files remain byte-identical to the pinned MIT upstream dependency.
All entry points are called explicitly by the existing scoped plugin facade.
"""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from uuid import uuid4


def verify_source(root, lock_path):
    root=Path(root).resolve()
    lock=json.loads(Path(lock_path).read_text(encoding='utf-8'))
    for name,entry in lock['files'].items():
        path=root/name
        if Path(name).name!=name or path.is_symlink() or not path.is_file():
            raise ValueError('ContextAware locked source is missing: '+name)
        if hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:
            raise ValueError('ContextAware source differs from locked commit: '+name)
    return lock


def load_managed(root,lock_path):
    verify_source(root,lock_path)
    name='_qq_managed_contextaware_'+uuid4().hex
    package=ModuleType(name);package.__path__=[str(root)];sys.modules[name]=package
    try:
        spec=importlib.util.spec_from_file_location(name+'.main',Path(root)/'main.py')
        module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module
        tree=ast.parse((Path(root)/'main.py').read_text(encoding='utf-8'))
        stripped=0
        for node in tree.body:
            if not isinstance(node,ast.ClassDef) or node.name!='Main':continue
            for method in node.body:
                if not isinstance(method,(ast.FunctionDef,ast.AsyncFunctionDef)):continue
                keep=[]
                for decorator in method.decorator_list:
                    target=decorator.func if isinstance(decorator,ast.Call) else decorator
                    if isinstance(target,ast.Attribute) and isinstance(target.value,ast.Name) and target.value.id=='filter':
                        stripped+=1
                    else:keep.append(decorator)
                method.decorator_list=keep
        if stripped<5:raise ValueError('Upstream registration shape changed')
        exec(compile(ast.fix_missing_locations(tree),str(Path(root)/'main.py'),'exec'),module.__dict__)
        original=module.logger
        class ManagedLogger:
            def __getattr__(self,key):return getattr(original,key)
            def info(self,message,*args,**kwargs):
                if '[ContextAware] ✓ 场景注入' in str(message):message=str(message).replace('✓ 场景注入','事实注入（后面的对象是规则观察，非模型决策）')
                return original.info(message,*args,**kwargs)
        module.logger=ManagedLogger()
        return module,name,stripped
    except BaseException:
        unload(name)
        raise


def unload(name):
    for key in list(sys.modules):
        if key==name or key.startswith(name+'.'):sys.modules.pop(key,None)
