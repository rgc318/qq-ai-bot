"""Convert GIF reference uploads to static PNG without changing source files."""
from io import BytesIO
import asyncio
import functools
import importlib


def normalize_gif_references(loaded,max_image_bytes=20*1024*1024,max_total_bytes=64*1024*1024):
    from PIL import Image
    result=[]
    converted=0
    for payload,mime in loaded:
        if payload.startswith((b'GIF87a',b'GIF89a')):
            with Image.open(BytesIO(payload)) as image:
                if image.width*image.height>25_000_000:
                    raise ValueError('GIF 参考图像素过大，无法转换上传副本')
                image.seek(0)
                frame=image.convert('RGBA')
                output=BytesIO()
                frame.save(output,format='PNG')
                payload=output.getvalue()
                mime='image/png'
                converted+=1
        if len(payload)>max_image_bytes:
            raise ValueError('转换后的参考图超过原有单图大小限制')
        result.append((payload,mime))
    if sum(len(payload) for payload,_ in result)>max_total_bytes:
        raise ValueError('转换后的参考图超过原有总大小限制')
    return result,converted


class ImageUploadAdapter:
    """Reversible compatibility at OmniDraw's OpenAI provider upload boundary."""
    def __init__(self,settings):
        self.settings=settings
        self.target=None
        self.wrapper=None

    def install(self,context):
        if not self.settings.get('enabled',True):
            self.restore()
            return False
        metadata=context.get_registered_star('astrbot_plugin_omnidraw')
        plugin=getattr(metadata,'star_cls',None)
        if plugin is None:return False
        root=plugin.__class__.__module__.rsplit('.',1)[0]
        cls=importlib.import_module(root+'.providers.openai_impl').OpenAIProvider
        if self.target is cls and cls.load_reference_images is self.wrapper:return True
        self.restore()
        original=cls.load_reference_images
        self.had_own='load_reference_images' in cls.__dict__
        self.original=original
        base=importlib.import_module(original.__module__)
        allowed=set(self.settings.get('provider_ids',['litellm-image25']))
        @functools.wraps(original)
        async def load(instance,refs,max_images=14):
            # Retain original file/URL validation, input count and byte limits.
            loaded=await original(instance,refs,max_images=max_images)
            if instance.config.id not in allowed:return loaded
            normalized,count=await asyncio.to_thread(normalize_gif_references,loaded,base.MAX_REFERENCE_IMAGE_BYTES,base.MAX_REFERENCE_TOTAL_BYTES)
            if count:
                from astrbot.api import logger
                logger.info('[QQ改图格式] provider=%s GIF首帧转PNG=%s（仅上传副本）',instance.config.id,count)
            return normalized
        self.target,self.wrapper=cls,load
        cls.load_reference_images=load
        return True

    def restore(self):
        if self.target is not None and self.target.load_reference_images is self.wrapper:
            if self.had_own:self.target.load_reference_images=self.original
            else:delattr(self.target,'load_reference_images')
        self.target=self.wrapper=None
