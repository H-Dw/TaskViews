"""Bounded lossless PNG wire encoding; never alter the official frame or pixels."""
from __future__ import annotations

import base64
import hashlib
from io import BytesIO
import struct
import time
import zlib

from PIL import Image

VERSION = 'png-lossless-refilter-v2'
MAX_PNG_BYTES = 8 * 1024**2
MAX_PIXELS = 1920 * 1080
PREFIX = 'data:image/png;base64,'
SIGNATURE = b'\x89PNG\r\n\x1a\n'
SEARCH_SECONDS = 12.0
REFILTER_MODES = ('sub', 'up', 'deflate_probe', 'paeth', 'signed_sum', 'none', 'average')


def policy():
    return {'version': VERSION, 'codec': 'PNG RGB8 noninterlaced', 'compression': 'zlib default strategy, level9, memLevel9',
            'placement': 'current frame before native context admission', 'select': 'strictly smaller valid PNG only',
            'identity': 'same dimensions, IHDR, non-IDAT chunks and every decoded RGB pixel',
            'refilter': list(REFILTER_MODES), 'max_compression_candidates': 1 + len(REFILTER_MODES),
            'search_seconds': SEARCH_SECONDS,
            'soft_trigger': 'image URL exceeds payload cap minus text cap minus reserve; never changes admission',
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


def _rebuild(chunks, packed):
    rebuilt, inserted = [SIGNATURE], False
    for kind, data in chunks:
        if kind == b'IDAT':
            if not inserted:
                rebuilt.append(_chunk(kind, packed))
                inserted = True
        else:
            rebuilt.append(_chunk(kind, data))
    return b''.join(rebuilt)


def _row_options(row, above, np):
    left, corner = np.zeros_like(row), np.zeros_like(row)
    left[3:], corner[3:] = row[:-3], above[:-3]
    a, b, c = left.astype(np.int16), above.astype(np.int16), corner.astype(np.int16)
    p = a + b - c
    pa, pb, pc = np.abs(p - a), np.abs(p - b), np.abs(p - c)
    prediction = np.where((pa <= pb) & (pa <= pc), a, np.where(pb <= pc, b, c)).astype(np.uint8)
    return (row, row - left, row - above, row - ((a + b) // 2).astype(np.uint8), row - prediction)


def _refilter_candidates(blob, size, chunks, deadline):
    # NumPy is already part of the pinned OSWorld runtime. Keep operations row-sized;
    # do not allocate five full-frame filter arrays or add an image-processing service.
    import numpy as np

    with Image.open(BytesIO(blob)) as image:
        raw = image.tobytes()
    stride = size[0] * 3
    pixels = np.frombuffer(raw, dtype=np.uint8).reshape(size[1], stride)
    fixed = {'none': 0, 'sub': 1, 'up': 2, 'average': 3, 'paeth': 4}
    for mode in REFILTER_MODES:
        compressor = zlib.compressobj(9, zlib.DEFLATED, 15, 9, zlib.Z_DEFAULT_STRATEGY)
        packed, filtered_sha, histogram = bytearray(), hashlib.sha256(), [0] * 5
        for index, row in enumerate(pixels):
            if time.monotonic() >= deadline:
                return  # Discard this incomplete candidate and retain a verified earlier PNG.
            above = pixels[index - 1] if index else np.zeros_like(row)
            choices = _row_options(row, above, np)
            if mode in fixed:
                selected = fixed[mode]
            elif mode == 'signed_sum':
                costs = [int(np.minimum(v.astype(np.int16), 256 - v.astype(np.int16)).sum()) for v in choices]
                selected = min(range(5), key=lambda k: costs[k])
            else:
                costs = []
                for kind, values in enumerate(choices):
                    trial = compressor.copy()
                    costs.append(len(trial.compress(bytes([kind]) + values.tobytes()) + trial.flush(zlib.Z_SYNC_FLUSH)))
                selected = min(range(5), key=lambda k: costs[k])
            filtered = bytes([selected]) + choices[selected].tobytes()
            histogram[selected] += 1
            filtered_sha.update(filtered)
            packed.extend(compressor.compress(filtered))
        packed.extend(compressor.flush())
        yield mode, _rebuild(chunks, packed), filtered_sha.hexdigest(), histogram


def recompress(data_url, expected_size, *, target_data_url_chars=None):
    """Return a wire URL and audit metadata; do not mutate the input frame/history."""
    started = time.monotonic()
    if target_data_url_chars is not None and (type(target_data_url_chars) is not int or target_data_url_chars < 0):
        raise ValueError('Qwen PNG soft target must be a nonnegative integer')
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
    candidate = _rebuild(chunks, packed)
    changed = len(candidate) < len(blob)
    selected = candidate if changed else blob
    if changed and _pixels(selected, size) != pixel_sha:
        raise ValueError('Lossless Qwen PNG pixel verification failed')
    filtered_sha = hashlib.sha256(scanlines).hexdigest()
    wire_filtered_sha = filtered_sha
    choice = 'idat_default' if changed else 'original'
    candidates = [{'encoding': 'idat_default', 'png_bytes': len(candidate)}]
    fast_url_chars = len(PREFIX) + 4 * ((len(selected) + 2) // 3)
    search = target_data_url_chars is None or fast_url_chars > target_data_url_chars
    if search:
        deadline = time.monotonic() + SEARCH_SECONDS
        for mode, candidate, candidate_filtered_sha, histogram in _refilter_candidates(blob, size, chunks, deadline):
            candidates.append({'encoding': mode, 'png_bytes': len(candidate), 'filter_histogram': histogram})
            if len(candidate) < len(selected):
                if _pixels(candidate, size) != pixel_sha:
                    raise ValueError('Lossless Qwen PNG pixel verification failed')
                selected, choice, wire_filtered_sha = candidate, mode, candidate_filtered_sha
    changed = len(selected) < len(blob)
    url = PREFIX + base64.b64encode(selected).decode('ascii') if changed else data_url
    return url, {'version': VERSION, 'changed': changed, 'dimensions': list(size),
        'original_png_bytes': len(blob), 'wire_png_bytes': len(selected),
        'original_data_url_chars': len(data_url), 'wire_data_url_chars': len(url),
        'original_png_sha256': hashlib.sha256(blob).hexdigest(), 'wire_png_sha256': hashlib.sha256(selected).hexdigest(),
        'decoded_rgb_sha256': pixel_sha, 'all_rgb_pixels_equal': True,
        'filtered_scanlines_sha256': filtered_sha, 'wire_filtered_scanlines_sha256': wire_filtered_sha,
        'encoding_choice': choice, 'candidate_count': len(candidates), 'candidates': candidates,
        'refilter_search_used': search, 'refilter_search_complete': search and len(candidates) == 1 + len(REFILTER_MODES),
        'target_data_url_chars': target_data_url_chars, 'encoding_seconds': round(time.monotonic() - started, 6)}
