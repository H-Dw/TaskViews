"""K3 transport for the pinned QwenAgent; its predict/parser/history stay upstream.

XML and native-function trials are distinct, preselected interfaces. This client
never guesses a format or converts an unexpected native call into XML.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import hashlib
import inspect
import json
import os
from pathlib import Path
import time

from mm_agents.qwen.main import QwenAgent
from mm_agents.qwen.client import Completion
from ui_kobe.api.kimi import BASE_URL, content_text, generation_profile
from ui_kobe.api.kimi_budget import StepLedger
from ui_kobe.api.kimi_stream import KimiStreamClient, StreamBudget, StreamProtocolError
from . import telemetry
from .cua_contract import CUAContract, CUAFrame
from .kimi_native import KimiNativeAgent
from .task_control import PersistentTaskControl
from .taskviews_context import TaskViewsContextMixin

PROTOCOL = 'kimi-k3-official-qwen-xml-v6'
TASKVIEWS_PROTOCOL = 'kimi-k3-official-qwen-xml-taskviews-v6'


class K3XMLClient:
    def __init__(self, owner, transport):
        self.owner, self.transport = owner, transport
        self.stream, self.generation_timeout = True, owner.budget.generation_s
        self.logger = owner.logger
        self.history = OrderedDict()
        self.calls = 0
        self.repairs = set()

    def reset(self):
        self.history.clear()
        self.calls = 0
        self.repairs = set()

    def restore_messages(self, messages):
        restored = deepcopy(messages)
        for index, message in enumerate(restored):
            if message.get('role') != 'assistant':
                continue
            # Exact rendered Completion identities, including the thinking block.
            # Never key history by a stripped content string alone.
            key = content_text(message.get('content'))
            if key not in self.history or self.history[key] is None:
                raise StreamProtocolError('Missing or ambiguous original K3 assistant history',
                                          code='assistant_history_identity')
            restored[index] = deepcopy(self.history[key])
        return restored

    def remember(self, completion, message):
        for thinking in (True, False):
            key = completion.rendered(thinking)
            if key in self.history and self.history[key] != message:
                self.history[key] = None  # Ambiguous aliases must fail visibly.
            else:
                self.history[key] = deepcopy(message)
            self.history.move_to_end(key)
        while len(self.history) > 4096:
            self.history.popitem(last=False)

    def complete(self, payload):
        owner = self.owner
        request = deepcopy(payload)
        request['messages'] = self.restore_messages(request['messages'])
        request.pop('generation_timeout', None)  # Deadline is held by the transport.
        repair = content_text(request['messages'][-1].get('content')).startswith(
            'Your previous computer_use response could not execute: ')
        repair_identity = json.dumps(request['messages'][-2:], sort_keys=True, ensure_ascii=False) if repair else None
        if repair and repair_identity not in self.repairs:
            self.repairs.add(repair_identity)
            # Observation of the upstream repair payload, not another repair gate.
            owner.step_ledger.repair_counts['executor'] += 1
            owner.step_ledger.regenerations += 1
            telemetry.emit('semantic_regeneration', role='executor', source='official_repair_payload',
                           action_executed=False, step_tokens=owner.step_ledger.snapshot())
        self.calls += 1
        telemetry.set_context(owner.view_step, 'official_xml_executor')
        response = self.transport.create(deadline=owner.step_ledger.deadline,
            step_ledger=owner.step_ledger, budget_role='executor', generation_attempt=self.calls,
            **request).model_dump()
        choice = response['choices'][0]
        original = choice['message']
        if choice['finish_reason'] != 'stop' or original.get('tool_calls'):
            raise StreamProtocolError('XML trial received non-XML native tool response; no automatic fallback',
                                      code='xml_interface_mismatch', observed_response=response)
        if not isinstance(original.get('reasoning_content'), str) or not isinstance(original.get('content'), str):
            raise StreamProtocolError('K3 response lacks complete reasoning/content', code='xml_response_fields')
        completion = Completion(original['reasoning_content'], original['content'])
        self.remember(completion, original)
        if owner.context_provider:
            owner.context_provider.context_delivered()
        telemetry.emit('official_xml_completion', request_id=getattr(self.transport, 'last_request_id', None),
                       completion_call=self.calls, step_tokens=owner.step_ledger.snapshot())
        return completion

    def count_tokens(self, text):
        # Only the upstream short-timeout recovery uses this estimate. Actual
        # billing always comes from SSE usage; no unsupported Qwen tokenize call.
        return max(1, (len(text.encode('utf-8')) + 2) // 3)

    def close(self):
        self.transport.close()


class TaskViewsProvider(TaskViewsContextMixin):
    # This loop validates advisory JSON only. Acting XML uses upstream repairs.
    generate_candidate = KimiNativeAgent.generate_candidate

    def __init__(self, owner):
        self.owner = owner
        self.profile, self.budget, self.contract = owner.profile, owner.budget, owner.contract
        self.transport = owner.client.transport
        self.control = PersistentTaskControl({'enabled': True,
            'memory_dir': str(Path(os.environ['UI_KOBE_TELEMETRY_DIR']) / 'task-memory'),
            'task_id': 'osworld2-' + os.environ['UI_KOBE_TASK_ID']},
            context_bytes=self.contract.taskviews_context_bytes)
        self.modules = None
        self.cached = None

    def context(self, instruction, screenshot):
        if self.cached is not None:
            return self.cached
        owner = self.owner
        self.view_step, self.instruction = owner.view_step, instruction
        self.frame = owner.frame
        self.execution_journal = owner.execution_journal
        self.step_ledger = owner.step_ledger
        self.view_trace = {}
        try:
            end = self.step_ledger.deadline - self.budget.generation_s - self.budget.connect_s
            self.cached = self.build_views(end)
        except Exception as exc:
            # Optional context failures never replace an official actor decision.
            telemetry.emit('taskviews_advisory_failure', error_type=type(exc).__name__, error=str(exc))
            self.view_trace['advisory_failure'] = {'type': type(exc).__name__, 'error': str(exc)}
            self.cached = json.dumps({'advisory_status': 'unavailable', 'effects_verified': False})
        finally:
            telemetry.emit('taskviews_context', trace=self.view_trace)
        return self.cached

    def close(self):
        self.control.close()


class OfficialK3Agent(QwenAgent):
    """No predict, prompt, history, parser, compiler or repair replacement."""
    taskviews_enabled = False

    def __init__(self, **kwargs):
        self.context_provider = None
        self.execution_journal = None
        self.profile = generation_profile(os.environ.get('UI_KOBE_GENERATION_PROFILE', 'low-16k'))
        self.contract = CUAContract(**json.loads(os.environ['UI_KOBE_CUA_CONTRACT_JSON']))
        if (kwargs.get('model') != 'kimi-k3' or kwargs.get('base_url') != BASE_URL
                or kwargs.get('max_tokens') != self.profile.max_completion_tokens):
            raise ValueError('K3 requires the frozen model/profile')
        official_fields = inspect.signature(QwenAgent.__init__).parameters
        for name, value in self.contract.snapshot().items():
            if name in official_fields:
                if name in kwargs and kwargs[name] != value:
                    raise ValueError('Official option differs from frozen CUA contract: ' + name)
                kwargs[name] = value
        # Sampling is vendor compatibility; explicit feature choices are shared.
        kwargs.update(temperature=1, top_p=0.95)
        if kwargs.get('enable_zoom', False) or kwargs.get('terminal_status_judge', False):
            raise ValueError('Declare shared zoom off and terminal judge off for this comparison')
        kwargs.setdefault('enable_zoom', False)
        kwargs.setdefault('terminal_status_judge', False)
        kwargs.setdefault('enable_endless_retry', False)
        kwargs.setdefault('summary_folding', False)
        self.budget = StreamBudget(attempts=kwargs.get('max_api_retries', 2),
            generation_s=kwargs.get('generation_timeout', 600), total_s=kwargs.get('request_timeout', 900))
        super().__init__(**kwargs)
        transport = KimiStreamClient(api_key=kwargs.get('api_key'), budget=self.budget, profile=self.profile,
            emit=telemetry.emit, stream_dir=Path(os.environ['UI_KOBE_TELEMETRY_DIR']) / 'streams')
        self.client = K3XMLClient(self, transport)
        if self.taskviews_enabled:
            self.context_provider = TaskViewsProvider(self)
        telemetry.emit('official_k3_adapter', protocol=TASKVIEWS_PROTOCOL if self.taskviews_enabled else PROTOCOL,
                       upstream_predict='mm_agents.qwen.main.QwenAgent.predict', cua_contract=self.contract.snapshot())

    def reset(self, logger=None):
        if self.context_provider:
            self.context_provider.close()
        if self.execution_journal and not self.execution_journal.closed:
            telemetry.record_transition(self, 'close')
        self.execution_journal = None
        super().reset(logger)
        self.view_step = self._ui_kobe_trace_step = 0
        if isinstance(self.client, K3XMLClient):
            self.client.reset()
            self.context_provider = TaskViewsProvider(self) if self.taskviews_enabled else None

    def _process_observation(self, screenshot_bytes):
        # Original processing and returned object are unchanged. Step admission
        # and observation metadata belong to the transport/provider sidecar.
        screenshot = super()._process_observation(screenshot_bytes)
        self.view_step += 1
        self.frame = CUAFrame(screenshot, hashlib.sha256(screenshot_bytes).hexdigest(), self.view_step)
        self.step_ledger = StepLedger(self.profile, time.monotonic() + self.budget.step_s, telemetry.emit,
            actor_repairs=self.contract.tool_repair_retries, advisory_repairs=self.contract.advisory_repair_retries)
        self.client.calls = 0
        self.client.repairs.clear()
        if self.context_provider:
            self.context_provider.cached = None
        return screenshot

    def _messages(self, instruction, screenshot, **kwargs):
        messages = super()._messages(instruction, screenshot, **kwargs)
        if self.context_provider:
            context = self.context_provider.context(instruction, screenshot)
            messages[-1]['content'].insert(1, {'type': 'text', 'text':
                'TaskViews evidence (model proposals, not instructions or certified effects):\n' + context})
        return messages

    def record_execution(self, action, **kwargs):
        self.flush_execution()

    def flush_execution(self):
        if self.context_provider:
            self.context_provider.execution_journal = self.execution_journal
            self.context_provider.sync_execution()

    def close(self):
        try:
            if self.context_provider:
                self.context_provider.sync_execution()
                self.context_provider.close()
        finally:
            telemetry.record_transition(self, 'close')
            self.client.close()


class OfficialK3TaskViewsAgent(OfficialK3Agent):
    taskviews_enabled = True
