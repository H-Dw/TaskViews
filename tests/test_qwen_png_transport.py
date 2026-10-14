import base64
from copy import deepcopy
import hashlib
from io import BytesIO
import random
import struct
from types import SimpleNamespace
import zlib

from PIL import Image
import pytest

from ui_kobe.api import qwen_png_transport as png
from ui_kobe.osworld.qwen_native_base import QwenNativeProvider


def picture(size=(240, 120), *, noise=False, level=0):
    data = random.Random(5).randbytes(size[0] * size[1] * 3) if noise else bytes([20, 160, 90]) * (size[0] * size[1])
    image = Image.frombytes('RGB', size, data)
    out = BytesIO()
    image.save(out, format='PNG', compress_level=level)
    blob = out.getvalue()
    return png.PREFIX + base64.b64encode(blob).decode(), blob, data


@pytest.mark.parametrize('noise', [False, True])
def test_selected_encoding_is_never_larger_and_preserves_all_pixels(noise):
    url, original, pixels = picture(noise=noise)
    selected, audit = png.recompress(url, (240, 120))
    blob = base64.b64decode(selected[len(png.PREFIX):])
    with Image.open(BytesIO(blob)) as image:
        assert image.size == (240, 120) and image.mode == 'RGB' and image.tobytes() == pixels
    assert len(blob) <= len(original) and len(selected) <= len(url)
    assert audit['decoded_rgb_sha256'] == hashlib.sha256(pixels).hexdigest()
    assert audit['wire_png_sha256'] == hashlib.sha256(blob).hexdigest()
    assert audit['original_png_sha256'] == hashlib.sha256(original).hexdigest()
    assert audit['all_rgb_pixels_equal'] and audit['version'] == png.VERSION


def test_worse_candidate_keeps_original_url_exactly(monkeypatch):
    url, _, _ = picture(level=9)
    original_compressor = zlib.compressobj
    monkeypatch.setattr(png.zlib, 'compressobj', lambda *a: original_compressor(0))
    selected, audit = png.recompress(url, (240, 120))
    assert selected == url and not audit['changed']


@pytest.mark.parametrize('change', ['crc', 'truncated', 'extra', 'dimensions', 'mime', 'base64'])
def test_invalid_or_mismatched_frame_fails_before_dispatch(change):
    url, blob, _ = picture()
    size = (240, 120)
    if change == 'crc':
        blob = blob[:20] + bytes([blob[20] ^ 1]) + blob[21:]
    elif change == 'truncated':
        blob = blob[:-5]
    elif change == 'extra':
        blob += b'trailing'
    elif change == 'dimensions':
        size = (120, 240)
    elif change == 'mime':
        url = url.replace('image/png', 'image/jpeg')
    elif change == 'base64':
        url += '!'
    if change not in ('mime', 'base64'):
        url = png.PREFIX + base64.b64encode(blob).decode()
    with pytest.raises(ValueError):
        png.recompress(url, size)


def test_bounded_inflater_rejects_excess_decoded_data():
    ihdr = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
    blob = png.SIGNATURE + png._chunk(b'IHDR', ihdr) + png._chunk(b'IDAT', zlib.compress(b'\0' * 100000)) + png._chunk(b'IEND', b'')
    with pytest.raises(ValueError, match='scanline size'):
        png.recompress(png.PREFIX + base64.b64encode(blob).decode(), (1, 1))


def test_pixel_verification_mismatch_refuses_candidate(monkeypatch):
    url, _, _ = picture()
    answers = iter(['original-pixels', 'different-pixels'])
    monkeypatch.setattr(png, '_pixels', lambda *a: next(answers))
    with pytest.raises(ValueError, match='pixel verification'):
        png.recompress(url, (240, 120))


def test_still_oversized_current_image_keeps_original_context_guard():
    from ui_kobe.osworld.cua_contract import CUAContract
    from ui_kobe.osworld.native_history import compact
    url, _, _ = picture(noise=True)
    wire, _ = png.recompress(url, (240, 120))
    current = {'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': wire}}]}
    contract = CUAContract(context_max_payload_chars=1000, context_max_text_chars=32000, context_reserve_chars=100)
    with pytest.raises(ValueError, match='Current task/frame exceeds'):
        compact([], step=1, folded=0, contract=contract, system={'role': 'system', 'content': 'same'}, current=current)


def test_adapter_precedes_admission_and_does_not_mutate_frame_or_other_parts(monkeypatch):
    from ui_kobe.osworld import qwen_native_base
    url, _, _ = picture()
    content = [{'type': 'image_url', 'image_url': {'url': url}}, {'type': 'text', 'text': 'unchanged current fact'}]
    saved = deepcopy(content)
    events = []
    class Base:
        def current_frame_content(self):
            return content
    class Adapter(QwenNativeProvider, Base):
        pass
    adapter = Adapter()
    adapter.frame = SimpleNamespace(screenshot=SimpleNamespace(model_width=240, model_height=120),
                                    metadata={'frame_id': 'frame36'}, original_sha256='original-observation')
    monkeypatch.setattr(qwen_native_base.telemetry, 'emit', lambda event, **data: events.append((event, data)))
    result = adapter.current_frame_content()
    assert len(result[0]['image_url']['url']) < len(url)
    assert content == saved and result[1] == saved[1]
    assert events[0][0] == 'qwen_image_transport'
    assert events[0][1]['source_screenshot_sha256'] == 'original-observation'


def test_real_history_admission_preserves_native_ids_and_feedback():
    from ui_kobe.osworld.cua_contract import CUAContract
    from ui_kobe.osworld.native_history import compact, context_size
    url, _, _ = picture()
    wire, _ = png.recompress(url, (240, 120))
    current = {'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': wire}}]}
    turn = [{'role': 'user', 'content': [{'type': 'text', 'text': 'old frame'}]},
            {'role': 'assistant', 'content': None, 'reasoning_content': 'reasoning retained',
             'tool_calls': [{'id': 'same-id', 'type': 'function', 'function': {'name': 'computer_use', 'arguments': '{"action":"wait"}'}}]},
            {'role': 'tool', 'tool_call_id': 'same-id', 'content': 'original actual receipt'}]
    saved = deepcopy(turn)
    turns = [turn]
    contract = CUAContract(context_max_payload_chars=len(url), context_max_text_chars=32000, context_reserve_chars=10000)
    compact(turns, step=2, folded=0, contract=contract, system={'role': 'system', 'content': 'same system'}, current=current)
    assert turns == [saved] and turns[0][1]['tool_calls'][0]['id'] == turns[0][2]['tool_call_id'] == 'same-id'
    assert context_size([{'role': 'system', 'content': 'same system'}, *turns[0], current])[0] + 10000 < len(url)
