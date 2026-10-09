import base64
import io
import unittest
from unittest.mock import patch
from PIL import Image
from material_images import heic_to_jpeg
from summaries import MaterialInput, analyze_material


def fixture():
    image = Image.new('RGB', (40, 24), (30, 80, 170))
    exif = Image.Exif()
    exif[315] = 'Synthetic test metadata'
    exif[274] = 6
    output = io.BytesIO()
    image.save(output, format='HEIF', exif=exif)
    return 'data:application/octet-stream;base64,' + base64.b64encode(output.getvalue()).decode()


class MaterialImageTests(unittest.TestCase):
    def test_real_heic_decodes_in_memory_to_jpeg_without_exif(self):
        data, multiple = heic_to_jpeg(fixture())
        self.assertTrue(data.startswith('data:image/jpeg;base64,'))
        self.assertFalse(multiple)
        with Image.open(io.BytesIO(base64.b64decode(data.split(',')[1]))) as image:
            self.assertEqual(image.format, 'JPEG')
            self.assertEqual(sorted(image.size), [24, 40])
            self.assertFalse(image.getexif())

    def test_uppercase_heic_and_heif_use_converted_image_not_original(self):
        data = fixture()
        for filename in ('slides.HEIC', 'slides.HEIF'):
            with patch('summaries.analyze_slide', return_value={'visible_text':'synthetic', 'uncertainty':''}) as call:
                result = analyze_material(MaterialInput(filename=filename, data=data, consent=True))
            self.assertEqual(result['visible_text'], 'synthetic')
            self.assertTrue(call.call_args.args[0].startswith('data:image/jpeg;base64,'))
            self.assertNotEqual(call.call_args.args[0], data)

    def test_bad_or_oversized_heic_rejected_before_api(self):
        for data in ('https://example.test/a.heic', 'data:image/heic;base64,!?',
                     'data:image/heic;base64,'+base64.b64encode(b'not heic').decode()):
            with patch('summaries.analyze_slide') as call:
                with self.assertRaises(ValueError):
                    analyze_material(MaterialInput(filename='x.heic', data=data, consent=True))
                call.assert_not_called()
        data=fixture()
        with patch('material_images.MAX_BYTES', 2):
            with self.assertRaisesRegex(ValueError, '6 MB'):heic_to_jpeg(data)
        with patch('material_images.MAX_PIXELS', 10):
            with self.assertRaisesRegex(ValueError, '像素'):heic_to_jpeg(data)

    def test_consent_checked_before_conversion_and_multiple_images_disclosed(self):
        with patch('material_images.heic_to_jpeg') as conversion:
            with self.assertRaises(ValueError):
                analyze_material(MaterialInput(filename='x.heic', data='data:image/heic;base64,YQ=='))
            conversion.assert_not_called()
        with patch('material_images.heic_to_jpeg', return_value=('data:image/jpeg;base64,YQ==', True)), \
             patch('summaries.analyze_slide', return_value={'uncertainty':'模糊'}):
            result=analyze_material(MaterialInput(filename='x.heic', data='data:image/heic;base64,YQ==', consent=True))
        self.assertIn('仅分析主图', result['uncertainty'])


if __name__ == '__main__':unittest.main()
