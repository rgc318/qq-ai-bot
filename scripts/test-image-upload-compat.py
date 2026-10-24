"""Exercise GIF upload conversion without a model or network."""
import importlib.util
from io import BytesIO
from pathlib import Path
import unittest
from PIL import Image
path=Path(__file__).resolve().parents[1]/'extensions/astrbot_plugin_qq_persona_models/image_upload_compat.py'
spec=importlib.util.spec_from_file_location('image_upload_compat',path)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
def animated():
    output=BytesIO()
    Image.new('RGB',(20,20),'red').save(output,format='GIF',save_all=True,append_images=[Image.new('RGB',(20,20),'blue')],duration=50,loop=0)
    return output.getvalue()
class UploadTests(unittest.TestCase):
    def test_first_frame_and_size(self):
        source=animated()
        result,count=module.normalize_gif_references([(source,'image/gif')])
        self.assertEqual(count,1)
        data,mime=result[0]
        self.assertEqual(mime,'image/png')
        with Image.open(BytesIO(data)) as frame:
            self.assertEqual(frame.size,(20,20))
            self.assertEqual(frame.convert('RGB').getpixel((10,10)),(255,0,0))
        self.assertTrue(source.startswith(b'GIF'))
    def test_png_bytes_are_not_changed(self):
        output=BytesIO();Image.new('RGBA',(10,10),(1,2,3,50)).save(output,format='PNG')
        data=output.getvalue()
        self.assertEqual(module.normalize_gif_references([(data,'image/png')]),([(data,'image/png')],0))
    def test_both_reference_images_preserved(self):
        data=animated()
        result,count=module.normalize_gif_references([(data,'image/gif'),(data,'image/gif')])
        self.assertEqual((len(result),count),(2,2))
    def test_converted_size_limits_still_apply(self):
        with self.assertRaises(ValueError):module.normalize_gif_references([(animated(),'image/gif')],max_image_bytes=10)
        with self.assertRaises(ValueError):module.normalize_gif_references([(animated(),'image/gif')],max_total_bytes=10)
    def test_corrupt_gif_fails_before_upload(self):
        with self.assertRaises(Exception):module.normalize_gif_references([(b'GIF89a broken','image/gif')])
if __name__=='__main__':unittest.main(verbosity=2)
