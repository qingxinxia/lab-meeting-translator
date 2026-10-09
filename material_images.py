"""Decode user-selected HEIC in memory; send only a metadata-free JPEG onward."""
import base64
import io

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()
MAX_BYTES = 6 * 1024 * 1024
MAX_PIXELS = 50_000_000


def heic_to_jpeg(data_url):
    prefix, separator, encoded = data_url.partition(',')
    if not separator or not prefix.startswith('data:') or not prefix.endswith(';base64'):
        raise ValueError('仅接受上传的 HEIC / HEIF 文件，不接受网址')
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError as error:
        raise ValueError('无效 HEIC 图片编码') from error
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError('HEIC 图片需为 6 MB 以内')
    try:
        with Image.open(io.BytesIO(raw), formats=['HEIF']) as source:
            if source.width * source.height > MAX_PIXELS:
                raise ValueError('HEIC 图片超过 5000 万像素，请缩小后上传')
            multiple = getattr(source, 'n_frames', 1) > 1
            # The HEIF plugin selects the primary image and normalizes orientation.
            image = ImageOps.exif_transpose(source).convert('RGB')
            image.thumbnail((4096, 4096), Image.Resampling.LANCZOS)
            image.info.clear()  # Do not forward EXIF/GPS or other original metadata.
            for edge, quality in [(4096, 92), (2560, 85)]:
                image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
                output = io.BytesIO()
                image.save(output, format='JPEG', quality=quality)
                if output.tell() <= MAX_BYTES:
                    return 'data:image/jpeg;base64,' + base64.b64encode(output.getvalue()).decode(), multiple
            raise ValueError('HEIC 转换后仍超过 6 MB，请缩小后上传')
    except ValueError:
        raise
    except Exception as error:
        raise ValueError('无法读取 HEIC / HEIF 图片，文件可能损坏或编码不受支持；请导出为 JPEG 后重试') from error
