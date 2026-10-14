"""Bounded lossless PNG wire encoding; never alter the official frame or pixels."""
from __future__ import annotations

import base64
import hashlib
from io import BytesIO
import struct
import zlib

from PIL import Image

VERSION = 'png-lossless-idat-v1'
MAX_PNG_BYTES = 8 * 1024**2
MAX_PIXELS = 1920 * 1080
PREFIX = 'data:image/png;base64,'
SIGNATURE = b'\x89PNG\r\n\x1a\n'


def policy():
    return {'version': VERSION, 'codec': 'PNG RGB8 noninterlaced', 'compression': 'zlib default strategy, level9, memLevel9',
            'placement': 'current frame before native context admission', 'select': 'strictly smaller valid PNG only',
            'identity': 'same dimensions, IHDR, decompressed filtered scanlines and decoded RGB SHA256',
            'max_png_bytes': MAX_PNG_BYTES, 'max_pixels': MAX_PIXELS,
            'resize_crop_quantize_lossy': False, 'context_or_token_budget_change': False}


def _chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)


def _pixels(blob, size):
    with Image.open(BytesIO(blob)) as image:
        if image.size != size or image.mode != 'RGB':
            raise ValueError('Lossless Qwen PNG dimensions or RGB mode differ')
        image.load()
        return hashlib.sha256(image.tobytes()).hexdigest()


def recompress(data_url, expected_size):
    """Return a wire URL and audit metadata; do not mutate the input frame/history."""
    if not isinstance(data_url, str) or not data_url.startswith(PREFIX):
        raise ValueError('Lossless Qwen transport requires an official PNG data URL')
    if len(data_url) > len(PREFIX) + 4 * ((MAX_PNG_BYTES + 2) // 3):
        raise ValueError('Qwen PNG exceeds bounded image transport input')
    blob = base64.b64decode(data_url[len(PREFIX):], validate=True)
    if len(blob) > MAX_PNG_BYTES or blob[:8] != SIGNATURE:
        raise ValueError('Invalid or oversized Qwen PNG')
    chunks, encoded, pos, ended = [], bytearray(), 8, False
    size = None
    idat_closed = False
    while pos < len(blob):
        if ended or pos + 12 > len(blob) or len(chunks) >= 4096:
            raise ValueError('Invalid Qwen PNG chunk boundary')
        length = struct.unpack('>I', blob[pos:pos + 4])[0]
        if pos + 12 + length > len(blob):
            raise ValueError('Truncated Qwen PNG chunk')
        kind, data = blob[pos + 4:pos + 8], blob[pos + 8:pos + 8 + length]
        crc = struct.unpack('>I', blob[pos + 8 + length:pos + 12 + length])[0]
        if zlib.crc32(kind + data) & 0xffffffff != crc:
            raise ValueError('Invalid Qwen PNG CRC')
        if not chunks:
            if kind != b'IHDR' or length != 13:
                raise ValueError('Missing Qwen PNG IHDR')
            w, h, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', data)
            size = (w, h)
            if (size != tuple(expected_size) or not 0 < w * h <= MAX_PIXELS
                    or (depth, color, compression, filtering, interlace) != (8, 2, 0, 0, 0)):
                raise ValueError('Qwen PNG is not the declared bounded RGB8 frame')
        elif kind == b'IHDR':
            raise ValueError('Duplicate Qwen PNG IHDR')
        if kind == b'IDAT':
            if idat_closed:
                raise ValueError('Non-contiguous Qwen PNG IDAT')
            encoded.extend(data)
        elif encoded:
            idat_closed = True
        if kind == b'IEND':
            if length or not encoded:
                raise ValueError('Invalid Qwen PNG IEND')
            ended = True
        chunks.append((kind, data))
        pos += length + 12
    if not ended or size is None:
        raise ValueError('Incomplete Qwen PNG')
    expected_bytes = (3 * size[0] + 1) * size[1]
    inflater = zlib.decompressobj()
    scanlines = inflater.decompress(encoded, expected_bytes + 1)
    if (len(scanlines) != expected_bytes or not inflater.eof
            or inflater.unconsumed_tail or inflater.unused_data):
        raise ValueError('Qwen PNG decoded scanline size differs')
    pixel_sha = _pixels(blob, size)
    compressor = zlib.compressobj(9, zlib.DEFLATED, 15, 9, zlib.Z_DEFAULT_STRATEGY)
    packed = compressor.compress(scanlines) + compressor.flush()
    rebuilt, inserted = [SIGNATURE], False
    for kind, data in chunks:
        if kind == b'IDAT':
            if not inserted:
                rebuilt.append(_chunk(kind, packed))
                inserted = True
        else:
            rebuilt.append(_chunk(kind, data))
    candidate = b''.join(rebuilt)
    changed = len(candidate) < len(blob)
    selected = candidate if changed else blob
    if changed and _pixels(selected, size) != pixel_sha:
        raise ValueError('Lossless Qwen PNG pixel verification failed')
    url = PREFIX + base64.b64encode(selected).decode('ascii') if changed else data_url
    return url, {'version': VERSION, 'changed': changed, 'dimensions': list(size),
        'original_png_bytes': len(blob), 'wire_png_bytes': len(selected),
        'original_data_url_chars': len(data_url), 'wire_data_url_chars': len(url),
        'original_png_sha256': hashlib.sha256(blob).hexdigest(), 'wire_png_sha256': hashlib.sha256(selected).hexdigest(),
        'decoded_rgb_sha256': pixel_sha, 'all_rgb_pixels_equal': True,
        'filtered_scanlines_sha256': hashlib.sha256(scanlines).hexdigest()}
