"""Bounded, auditable language rules for actions versus reported UI state.

These rules describe ordinary operations, never benchmark objects or answers.
A public statement remains a proposal; it cannot certify focus or completion.
"""
import re
import unicodedata

VERSION = 'public_operation_semantics_v6'
FILE = re.compile(r'\b(?:files?|folders?|director(?:y|ies)|documents?)\b|文件|文件夹|目录|文档', re.I)
PATTERNS = {
    'copy': r'\bcopy\b|复制', 'cut': r'\bcut\b|剪切', 'paste': r'\bpaste\b|粘贴',
    'move': r'\bmove\b|移动|搬移', 'transfer': r'\btransfer\b|转移|传送',
    'rename': r'\brenam\w*\b|重命名', 'capture': r'\bscreenshot\b|\bsnapshot\b|\bcapture\b|截图|截屏|快照',
    'export': r'\bexport\w*\b|导出', 'save': r'\bsav(?:e|ing)\b|保存',
    'save_as': r'\bsave\s+as\b|另存为',
    'open': r'\bopen\b|打开', 'find': r'\bfind\b|\bsearch\b|搜索|查找',
    'edit': r'\breplace\b|\btype\b|\benter text\b|输入|替换',
    'confirm': r'\bconfirm\b|确认|确定', 'dismiss': r'\bdismiss\b|\bcancel\b|取消|关闭弹窗',
    'undo': r'\bundo\b|撤销', 'down': r'\bscroll down\b|向下滚', 'up': r'\bscroll up\b|向上滚',
    'horizontal_scroll': r'\bscroll (?:left|right)\b|向左滚|向右滚|横向滚动',
    'zoom_out': r'\bzoom out\b|缩小', 'zoom_in': r'\bzoom in\b|\benlarge\b|放大',
    'zoom_value': r'\b(?:set|change|adjust|type|enter)\b[^.;\n]{0,24}\b(?:zoom|scale)\b[^.;\n]{0,16}(?:\d+(?:\.\d+)?\s*%|exact|precise|numeric)|\b(?:set|type|enter)\s+(?:the\s+)?(?:exact|precise|numeric)\s+zoom\b|\bzoom\s+(?:in\s+|out\s+)?to\s+\d+(?:\.\d+)?\s*%|(?:设置|输入|调整)(?:精确|准确)?(?:缩放|比例)[^。；\n]{0,12}\d+(?:\.\d+)?\s*%',
    'readability': r'\b(?:make|keep)\b[^.;\n]{0,32}\breadable\b|\b(?:adjust|change)\s+(?:the\s+)?zoom\b|提高可读性|调整缩放',
    'reading': r'\b(?:read|review|compare|cross[- ]?check|reconcile|inspect)\b|阅读|核对|对比|比较|查看(?:内容|文档|文本|数据)',
    'image_edit': r'\b(?:edit|modify|crop|retouch|resize)\b[^.;\n]{0,32}\b(?:image|picture|photo|canvas)\b|\b(?:remove|erase|delete)\b[^.;\n]{0,32}\bbackground\b|\b(?:make|set)\b[^.;\n]{0,32}\btransparent\b|(?:编辑|裁剪|修改|缩放)(?:图像|图片|照片)|(?:删除|移除|去除)背景|(?:设为|变为|改为)透明',
    'drag': r'\bdrag(?:ging)?\b|拖拽|拖动',
    'maximize': r'\bmaximi[sz]e\b|最大化',
    'actual_pixels': r'\bactual pixels\b|实际像素',
    'play': r'\b(?:play|pause)\b|播放|暂停', 'stop': r'\bstop playback\b|停止播放',
    'fullscreen': r'\bfull ?screen\b|全屏', 'seek_forward': r'\bseek forward\b|快进',
    'seek_backward': r'\bseek backward\b|快退',
    'window_switch': r'\bswitch\b[^.;。]*\b(?:window|application|app)\b|切换窗口|切换应用',
    'focus_next': r'\bnext (?:field|control)\b|下一个控件|下一个输入框',
    'context_menu': r'\bcontext menu\b|上下文菜单|右键菜单',
    'menu_open': r'\bopen\s+(?:(?!(?:then|and|but|to)\b)[\w-]+\s+){0,4}menu\b|打开(?:(?!然后|随后|并且)[^。；]){0,8}菜单',
    'window_locate': r'\b(?:open|find|locate|reopen)\s+(?:(?!(?:then|and|but|to)\b)[\w-]+\s+){0,5}(?:window|application|app|overview)\b|(?:打开|查找|定位)(?:(?!然后|随后|并且)[^。；]){0,12}(?:窗口|应用|概览)',
    'folder_open': r'\b(?:open|enter|navigate to)\s+(?:(?!(?:then|and|but|to)\b)[\w-]+\s+){0,5}(?:folder|directory)\b|(?:打开|进入)(?:(?!然后|随后|并且)[^。；]){0,12}(?:目录|文件夹)',
    'url_open': r'\b(?:open|visit|navigate to)\s+(?:(?!(?:then|and|but|to)\b)[\w-]+\s+){0,5}(?:website|webpage|url|web page)\b|(?:打开|访问)(?:(?!然后|随后|并且)[^。；]){0,12}(?:网页|网站|网址)',
    'file_find': r'\b(?:find|search for|locate)\s+(?:(?!(?:then|and|but|to)\b)[\w-]+\s+){0,5}(?:file|folder|directory)\b|(?:查找|搜索)(?:(?!然后|随后|并且)[^。；]){0,12}(?:文件|目录)',
}
NEGATIVE = re.compile(r"(?:\b(?:not|never|avoid|don't|do not)\s+(?:\w+\s+){0,2}|(?:不要|勿|避免|不需要|无需).{0,4})$", re.I)
STATE_PREFIX = re.compile(r'\b(?:is|are|was|were|remains?|already|looks?)\s+(?:(?:now|still|already)\s+)*$', re.I)
DEPENDENCIES = {
    'copy': {'paste'}, 'cut': {'paste'}, 'move': {'cut', 'paste'},
    'transfer': {'copy', 'cut', 'paste'},
    'reading': {'readability', 'up', 'down', 'horizontal_scroll', 'zoom_in', 'zoom_out', 'zoom_value', 'maximize', 'window_switch'},
    'readability': {'reading', 'zoom_in', 'zoom_out', 'zoom_value', 'maximize', 'horizontal_scroll'},
    'image_edit': {'undo', 'zoom_in', 'zoom_out', 'save', 'export'},
    'open': {'reading', 'readability'},
    'file_operations': {'folder_open', 'file_find', 'edit', 'confirm', 'window_locate', 'window_switch'},
    'capture': {'file_find', 'folder_open', 'window_locate', 'window_switch'},
    'export': {'edit', 'confirm', 'file_find', 'folder_open'},
    'save_as': {'edit', 'confirm', 'folder_open'},
    'zoom_value': {'edit', 'confirm', 'readability'},
}

# These are conditional navigation prerequisites, never permission to mutate
# content. Capability scope is frozen separately from the current operation.
SUPPORT = {'focus_next', 'context_menu', 'menu_open', 'dismiss', 'window_switch', 'window_locate'}
SEQUENCE = re.compile(r'\b(?:then|after that|subsequently)\b|然后|随后|接着', re.I)
LITERALS = re.compile(r'`[^`]*`|"[^"\n]*"|“[^”\n]*”|\b[a-z_][\w-]*(?:\.[a-z_][\w-]*)+\b', re.I)


def immediate_actions(parsed):
    """Only explicit ordering; do not invent a plan from an unordered goal."""
    hits = parsed['hits']
    text = parsed.get('text', '')
    limits = [m.start() for m in SEQUENCE.finditer(text)]
    # Distinguish the immediate command from its purpose, e.g. opening a menu
    # to zoom is not yet choosing a zoom command. "Need to zoom" stays an action.
    for match in re.finditer(r'\b(?:to|in order to|so I can)\s+(?:read|zoom|copy|paste|save|export|find)\b|以便|为了', text, re.I):
        if any(h['span'][1] <= match.start() for h in hits):
            limits.append(match.start())
    return {h['operation'] for h in hits if not limits or h['span'][0] < min(limits)}


def analyze(text):
    if not isinstance(text, str):
        text = ''
    text = unicodedata.normalize('NFKC', re.sub(r'<(artifact_review|key_lookup)>.*?</\1>', '', text, flags=re.S))
    # Malformed/unterminated protocol labels must not turn their topic names
    # or review fields into ordinary action keywords.
    text = re.sub(r'<(?:artifact_review|key_lookup)\b.*$', '', text, flags=re.S)
    hits, states, rejected = [], [], []
    for operation, pattern in PATTERNS.items():
        for match in re.finditer(pattern, text, re.I):
            before, after = text[max(0, match.start() - 48):match.start()], text[match.end():match.end() + 48]
            reason = None
            if NEGATIVE.search(before):
                reason = 'negated'
            elif re.search(r'\b(?:if|whether)\b[^.;\n]{0,40}$|(?:如果|是否)[^。；]{0,12}$', before, re.I):
                reason = 'conditional_not_current_action'
            elif operation == 'cut' and re.match(r'\s+(?:off|out|short)\b', after, re.I):
                reason = 'non_clipboard_expression'
            elif operation == 'move' and re.match(r'\s+(?:(?:the|my)\s+)?(?:mouse|pointer|cursor|window|dialog)\b', after, re.I):
                reason = 'pointer_motion'
            elif operation == 'capture' and re.match(r'\s+(?:(?:the|your)\s+)?(?:attention|idea|meaning)\b', after, re.I):
                reason = 'non_gui_expression'
            elif operation == 'save' and re.match(r'\s+(?:time|effort|money)\b', after, re.I):
                reason = 'non_gui_expression'
            elif operation == 'find' and re.match(r'\s+out\b', after, re.I):
                reason = 'non_gui_expression'
            elif operation == 'open' and re.match(r'\s+(?:question|issue|mind)\b', after, re.I):
                reason = 'non_gui_expression'
            elif operation == 'copy' and (re.match(r'\s+of\b', after, re.I) or re.search(r'\b(?:a|the)\s+$', before, re.I)):
                reason = 'noun_not_action'
            elif operation == 'edit' and match.group().lower() == 'type' and re.search(r'\b(?:file|data|document|content)\s+$', before, re.I):
                reason = 'noun_not_action'
            elif STATE_PREFIX.search(before) or re.search(r'(?:已经|已|仍然|处于)$', before):
                reason = 'reported_state'
            elif re.match(r'\s+(?:(?:command|button|menu)\s+)?(?:is|was|remains)\s+(?:disabled|enabled|visible|selected)\b', after, re.I):
                reason = 'reported_state'
            elif operation == 'reading' and re.match(r'[- ]only\b', after, re.I):
                reason = 'reported_state'
            elif operation == 'reading' and re.search(r'\b(?:can|could)\s+(?:now\s+)?(?:clearly\s+)?$', before, re.I):
                reason = 'reported_state'
            elif operation == 'reading' and match.group().lower() == 'inspect' and not re.search(
                    r'\b(?:document|text|content|page|value|data|number|table)\b|文档|内容|数值', after, re.I):
                reason = 'non_reading_inspection'
            elif operation == 'confirm' and (re.match(r'\s+(?:that|whether)\b', after, re.I) or re.search(
                    r'\b(?:details|amount|result|readability|focus|correct|exists?|matches?)\b|是否|存在|结果|焦点|金额|细节', after, re.I)):
                reason = 'inspection_not_confirmation_key'
            elif operation == 'context_menu' and re.search(r'\b(?:see|shows?|showing|displays?)\s+(?:(?:the|a|an)\s+)?$', before, re.I):
                reason = 'reported_state'
            elif operation == 'open' and re.match(r'\s+(?:(?:the|a|an|file|view|application|context)\s+)*menu\b', after, re.I):
                reason = 'menu_not_document'
            elif operation == 'open' and re.match(r'[^。；]{0,8}菜单', after):
                reason = 'menu_not_document'
            hit = {'operation': operation, 'span': list(match.span()), 'text': match.group()}
            if reason:
                rejected.append({**hit, 'reason': reason})
                if reason == 'reported_state' or (reason == 'non_clipboard_expression' and re.search(
                        r'\b(?:text|content|edge|column|page|window|document)\b|文字|内容|边缘|列|页面|窗口|文档', before + after, re.I)):
                    states.append({**hit, 'kind': reason})
            else:
                hits.append(hit)
    # A verb in a filename, quoted literal or key-lookup label is not an intent.
    literals = [m.span() for m in LITERALS.finditer(text)]
    for hit in list(hits):
        if any(a <= hit['span'][0] and hit['span'][1] <= b for a, b in literals):
            hits.remove(hit)
            rejected.append({**hit, 'reason': 'literal_not_intent'})
    # Most specific object wins *within the same action clause*. Opening a
    # window/folder/menu is not the application's Ctrl+O document dialog.
    specific = {'window_locate': {'open', 'find'}, 'folder_open': {'open'},
                'url_open': {'open'}, 'file_find': {'find'}, 'menu_open': {'open', 'context_menu'},
                'save_as': {'save'}}
    for target in list(hits):
        for hit in list(hits):
            if (hit['operation'] in specific.get(target['operation'], set())
                    and target['span'][0] <= hit['span'][0] < target['span'][1]):
                hits.remove(hit)
                rejected.append({**hit, 'reason': 'different_target_type'})
    for hit in list(hits):
        if hit['operation'] == 'window_locate' and any(
                h['operation'] == 'menu_open' and h['span'][0] == hit['span'][0] for h in hits):
            hits.remove(hit)
            rejected.append({**hit, 'reason': 'menu_not_window'})
    # A separate request to open a context menu retains its own identity.
    # A read goal or an arbitrary larger value is not a request for precise
    # numeric zoom. A known field request is explicit; a percentage alone is not.
    for hit in hits:
        local = re.split(r'[;。；\n]|\.\s', text[hit['span'][0]:hit['span'][1] + 60])[0]
        if hit['operation'] == 'edit' and re.search(r'\bzoom\b|缩放', local, re.I):
            hit['operation'] = ('zoom_value' if re.search(r'\d+(?:\.\d+)?\s*%|\b(?:exact|precise|numeric)\b|精确|准确', local, re.I)
                                else 'readability')
    # Public readability statements are separate from actions. They remain
    # model reports; the caller must bind them to an observation before reuse.
    for match in re.finditer(r'\b(?:text|content|document|page|values?|numbers?)\s+(?:is|are|looks?|seems?)\s+(?:(?:now|already|clearly|still)\s+)*(?:not\s+)?(?:readable|legible|unreadable|illegible|too small)|(?:文字|内容|文档|页面|数值)(?:已经|现在|仍然|仍)?(?:清晰可读|可读|不可读|看不清)', text, re.I):
        if re.search(r'\b(?:if|whether|ensure|check|make)\b|是否|如果|确保', text[max(0, match.start()-24):match.start()], re.I):
            continue
        if re.search(r'\bnot\s+(?:unreadable|illegible|too small)\b', match.group(), re.I):
            continue
        negative = bool(re.search(r'\b(?:not|unreadable|illegible|too small)\b|不可读|看不清', match.group(), re.I))
        states.append({'kind': 'unreadable' if negative else 'readable', 'span': list(match.span()), 'text': match.group()})
    for match in re.finditer(r'\bI can (?:now )?(?:clearly read|read\b[^.;\n]{0,60}\bclearly)|(?:我)?(?:现在|已经)能(?:清楚|清晰)(?:地)?(?:读出|读取|看清)', text, re.I):
        if not re.search(r'\b(?:if|whether|check|ensure)\b|是否|如果|确保', text[max(0, match.start()-24):match.start()], re.I):
            states.append({'kind': 'readable', 'span': list(match.span()), 'text': match.group()})
    if any(h['operation'] == 'zoom_value' for h in hits):
        hits = [h for h in hits if h['operation'] not in ('zoom_in', 'zoom_out', 'readability')]
    # Object + destination relations, not a filename or a task-specific verb.
    transfer = re.search(r'\b(?:put|place|organize|collect|gather)\b[^.;\n]{0,160}\b(?:in|into|to|under)\b[^.;\n]{0,80}\b(?:folder|directory)\b|(?:放入|放到|归入|整理到|移至)[^。；]{0,50}(?:目录|文件夹)', text, re.I)
    if transfer and FILE.search(text) and not NEGATIVE.search(text[max(0, transfer.start()-48):transfer.start()]):
        hits.append({'operation': 'transfer', 'span': list(transfer.span()), 'text': transfer.group()})
    actions = sorted({h['operation'] for h in hits})
    file_context = bool(FILE.search(text) and set(actions) & {'copy', 'cut', 'move', 'transfer', 'paste', 'rename'})
    return {'version': VERSION, 'text': text, 'actions': actions, 'file_context': file_context,
            'hits': hits, 'states': states, 'rejected': rejected}


def operations(text):
    return set(analyze(text)['actions'])


def capabilities(text):
    parsed = analyze(text)
    result = set(parsed['actions']) | ({'file_operations'} if parsed['file_context'] else set())
    if isinstance(text, str) and text.strip():
        result.update(SUPPORT)
    # Transitive prerequisites are fixed at preparation, not silently enabled
    # in response to a runtime proposal.
    previous = None
    while previous != result:
        previous = set(result)
        for op in previous:
            result.update(DEPENDENCIES.get(op, set()))
    return sorted(result)
