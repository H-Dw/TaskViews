"""Audited routing contracts, distinct from frozen key bindings and UI proof.

The gate establishes semantic eligibility, not visual applicability. Unknown
focus stays conditional. Unsupported references remain in the frozen catalog
but cannot acquire a runnable binding merely from a lookup tag.
"""
import re

from .guidance_semantics import NEGATIVE, LITERALS

VERSION = 'guidance_applicability_v1'

GUIDE_OPS = {
    'clipboard.copy_paste': ['copy'], 'clipboard.move_paste': ['cut'],
    'clipboard.transfer': ['copy', 'cut', 'transfer'], 'files.transfer': ['transfer', 'copy', 'cut', 'move'],
    'clipboard.copy': ['copy'], 'clipboard.cut': ['cut'], 'clipboard.paste': ['paste'],
    'clipboard.verify': ['paste'], 'files.copy': ['copy'], 'files.move': ['cut', 'move'],
    'files.rename': ['rename'], 'text.edit': ['edit'], 'text.replace_confirm': ['edit', 'confirm'],
    'text.confirm': ['confirm'], 'ui.dismiss': ['dismiss'], 'history.undo': ['undo'],
    'document.find': ['find'], 'document.open': ['open'], 'document.save': ['save'],
    'document.save_as': ['save_as'],
    'navigation.down': ['down'], 'navigation.up': ['up'], 'capture.image': ['capture'],
    'export.file': ['export'], 'vlc.capture': ['capture'], 'gimp.export': ['export'],
    'navigation.horizontal': ['horizontal_scroll'], 'view.zoom_value': ['zoom_value'],
    'view.zoom_confirm': ['zoom_value'], 'view.zoom_check': ['zoom_value'],
    'view.readability': ['reading', 'readability'], 'menu.open': ['menu_open'],
    'document.read': ['reading'], 'window.maximize': ['maximize'],
    'view.zoom_in': ['zoom_in'], 'view.zoom_out': ['zoom_out'], 'focus.verify': [],
    'pointer.drag': ['drag'], 'image.edit': ['image_edit'],
    'window.locate': ['window_locate'], 'folder.open': ['folder_open'],
    'url.open': ['url_open'], 'files.find': ['file_find'],
}

# Each supported catalog intent is mapped explicitly. Broad topics are never
# selected as a whole: save/open/print, up/down and copy/cut are different needs.
CATALOG_OPS = {
    'zoom in': 'zoom_in', 'zoom page in': 'zoom_in',
    'zoom out': 'zoom_out', 'zoom page out': 'zoom_out', 'actual pixels': 'actual_pixels',
    'toggle playback': 'play', 'toggle play or pause': 'play', 'play or pause': 'play',
    'stop playback': 'stop', 'toggle full screen': 'fullscreen',
    'short seek forward': 'seek_forward', 'short seek backward': 'seek_backward',
    'switch window or application': 'window_switch', 'next control': 'focus_next',
    'open focused item context menu': 'context_menu',
    'copy selection': 'copy', 'cut selection': 'cut', 'paste clipboard': 'paste',
    'cut selected files': 'cut', 'copy selected files': 'copy', 'paste into current folder': 'paste',
    'undo last edit': 'undo', 'undo image edit': 'undo', 'dismiss popup': 'dismiss',
    'dismiss current popup': 'dismiss', 'select field text': 'edit',
    'confirm current field or dialog': 'confirm', 'confirm cell entry': 'confirm',
    'scroll one viewport down': 'down', 'scroll one viewport up': 'up',
    'open or focus content search': 'find', 'find page text': 'find', 'find text': 'find', 'find': 'find',
    'open file chooser': 'open', 'open document dialog': 'open', 'open file dialog': 'open',
    'save current editable content': 'save', 'save current document': 'save', 'save file': 'save',
    'open save as dialog': 'save_as',
    'focus or open application menu': 'menu_open', 'rename selected file': 'rename', 'rename file': 'rename',
    'toggle maximize': 'maximize',
}


def mentioned_toolsets(text, data):
    """Explicit public names only; a mention is still not focus detection."""
    text = LITERALS.sub(' ', text or '')
    result = set()
    for key, aliases in data['task_aliases'].items():
        for alias in [*aliases, key]:
            for match in re.finditer(r'(?<![a-z0-9_])' + re.escape(alias) + r'(?![a-z0-9_])', text or '', re.I):
                if not NEGATIVE.search(text[max(0, match.start()-48):match.start()]):
                    result.add(key)
    return result


def catalog_operation(recipe):
    return CATALOG_OPS.get(recipe['intent'].casefold())


def owner(topic):
    return topic.rsplit('.', 1)[0] if '.' in topic else 'general'


def software_reason(toolset, text, data):
    text = LITERALS.sub(' ', text or '')
    if toolset == 'general':
        return None
    if toolset.startswith('task.'):
        return 'temporary_catalog_requires_audited_contract'
    mentioned = mentioned_toolsets(text, data)
    if toolset in mentioned:
        return None
    # Type-specific references may be justified by an explicit target type.
    targets = {'type.file_manager': r'\b(?:files?|folders?|directory|file manager)\b|文件|目录',
               'type.browser': r'\b(?:browser|webpage|website|web page)\b|浏览器|网页',
               'type.document': r'\b(?:document|text editor)\b|文档|文本编辑器',
               'type.text_editor': r'\btext editor\b|文本编辑器',
               'type.media': r'\b(?:player|video|playback)\b|播放器|视频|播放'}
    if toolset in targets and re.search(targets[toolset], text, re.I):
        return None
    return 'software_target_not_established'


def contextual_reason(ops, text):
    """Known incompatible targets are excluded, unknown focus isn't asserted."""
    text = LITERALS.sub(' ', text or '')
    if re.search(r'\bterminal\b|终端', text, re.I) and ops & {'copy', 'cut', 'paste', 'edit', 'confirm', 'find', 'open', 'save', 'save_as', 'undo'}:
        return 'terminal_requires_distinct_bindings'
    if re.search(r'\b(?:canvas|image|photo|picture|layer|background)\b|画布|图像|图片|图层|背景', text, re.I):
        if 'rename' in ops and re.search(r'\b(?:layer|object|selection)\b|图层|对象|选区', text, re.I):
            return 'canvas_object_is_not_file'
        if 'cut' in ops and re.search(r'\b(?:cut out|cut away|cut the background)\b|裁剪|剪掉', text, re.I):
            return 'image_cut_not_clipboard'
        if 'edit' in ops and not re.search(r'\b(?:text|label|field|name|path)\b|文本|文字|输入框|名称|路径', text, re.I):
            return 'canvas_is_not_text_field'
    return None


def guide_reason(name, entry, *, ops, frozen, enabled, text, origin, data, phase=None):
    required = set(entry.get('requires', [])) - set(enabled)
    if required:
        return 'directory_not_frozen', sorted(required)
    supported = set(entry['operations'])
    if name == 'focus.verify':
        return None, []
    if name in ('view.zoom_confirm', 'view.zoom_check', 'clipboard.verify'):
        expected = {'view.zoom_confirm': 'confirm_once', 'view.zoom_check': 'inspect_effect', 'clipboard.verify': 'verify'}[name]
        if phase != expected:
            return 'execution_phase_not_established', []
    if not supported & ops:
        return 'operation_mismatch', []
    # Every binding in a workflow needs frozen support, not just its title.
    needed = {b for b in entry['bindings'] if b in ('copy', 'cut', 'paste')}
    if name.startswith('files.') and name != 'files.find':
        needed.add('file_operations')
    missing = (ops & supported | needed) - frozen
    if missing:
        return 'capability_not_frozen', sorted(missing)
    reason = contextual_reason(ops & supported, text)
    if reason:
        return reason, []
    if name in ('vlc.capture', 'gimp.export'):
        reason = software_reason('app.vlc' if name == 'vlc.capture' else 'app.gimp', text, data)
        if reason:
            return reason, []
    if name == 'vlc.capture' and re.search(r'\b(?:desktop|whole screen|window screenshot)\b|桌面|整个屏幕|窗口截图', text, re.I):
        return 'desktop_capture_not_video_snapshot', []
    return None, []
