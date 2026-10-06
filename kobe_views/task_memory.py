"""Durable, provenance-bound task facts, separate from current screenshot geometry.

The task contract is supplied by the caller; visual/model extraction remains a
candidate.  Missing information and whole-fact budget omissions are explicit.
No environment, credential store, evaluator answer, or browser state is read.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from threading import RLock
from urllib.parse import urlsplit

from .model import digest, dumps, plain
from .task_graph import TaskGraph


_CATEGORIES = ("goal", "url", "port", "delivery_file", "key_semantics", "constraint")
_PREDICATES = {
    "task.goal": "goal", "resource.url_original": "url", "resource.port": "port",
    "task.delivery_file": "delivery_file", "task.key_semantics": "key_semantics",
    "task.constraint": "constraint", "action.semantic": "key_semantics",
}
_URL = re.compile(
    r"https?://[^\s<>\"`]+|"
    r"(?<![\w@])(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+"
    r"(?:[A-Za-z][A-Za-z0-9-]*|[0-9]+)"
    r"(?::[0-9]{1,5})(?:/[^\s<>\"`]*)?"
    r"|(?<![\w@])(?:[A-Za-z0-9-]+\.)+(?:io|com|org|net|dev|local)"
    r"(?:/[^\s<>\"`]*)?",
    re.IGNORECASE,
)
_FILE = re.compile(
    r"(?<!\w)(?:[A-Za-z]:[\\/]|/|\./)?[^\s<>\"`]+"
    r"\.(?:xlsx?|ods|csv|pdf|docx?|odt|pptx?|odp|txt|md|json)(?!\w)", re.IGNORECASE,
)
_SECRET = re.compile(
    r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}|"
    r"\bsk-[A-Za-z0-9_-]{16,}|"
    r"(?:api[_-]?key|access[_-]?token|authorization|password|secret)"
    r"[\"']?\s*[:=]\s*[\"']?(?!\$\{|os\.environ|QWEN_API_KEY\b|API_KEY\b)"
    r"[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE,
)
_SENSITIVE_URL = re.compile(r"https?://[^/\s]+:[^/@\s]+@|[?&](?:api[_-]?key|token|access_token|password|secret)=", re.I)
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}\Z")
_GEOMETRY_KEYS = {"bbox", "bounds", "coordinates", "coordinate", "rect", "rectangle", "screen_position",
                  "click_x", "click_y", "to_x", "to_y", "left", "top", "right", "bottom", "x", "y"}
_CAPS = {"entities": 64, "claims": 96, "total_entities": 4000, "total_claims": 8000}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _text(value, maximum=100000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError("Expected bounded nonempty text")
    if _SECRET.search(value) or _SENSITIVE_URL.search(value):
        raise ValueError("Credential-like text is not admitted to persistent task memory")
    return value


def _list_of_text(values):
    if not isinstance(values, (tuple, list)) or len(values) > 128:
        raise ValueError("Task contract fields must be bounded lists")
    return [_text(value, 8000) for value in values]


def _contains_geometry(value, depth=0):
    if depth > 16:
        raise ValueError("Semantic JSON nesting exceeds its bound")
    if isinstance(value, dict):
        return any(str(key).casefold() in _GEOMETRY_KEYS or _contains_geometry(item, depth + 1)
                   for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_geometry(item, depth + 1) for item in value)
    return False


def _credential_safe(value, depth=0):
    if depth > 16:
        raise ValueError("Semantic JSON nesting exceeds its bound")
    encoded = dumps(value)
    if _SECRET.search(encoded) or _SENSITIVE_URL.search(encoded):
        raise ValueError("Credential-like text is not admitted to persistent task memory")
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in {"api_key", "authorization", "password", "access_token", "secret"}:
                raise ValueError("Credential fields are not admitted to persistent task memory")
            _credential_safe(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _credential_safe(item, depth + 1)


def literal_urls(text):
    """Yield original observed URL strings, never reconstruct a missing domain/port."""
    result = []
    for match in _URL.finditer(text):
        original = match.group(0).rstrip(".,;:!?)]}'")
        parsed = urlsplit(original if re.match(r"https?://", original, re.I) else "//" + original)
        try:
            port = parsed.port
        except ValueError:
            continue
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            continue
        # Credentials in a URL query must not enter either the graph or journal.
        if re.search(r"(?:[?&])(?:api[_-]?key|token|access_token|password|secret)=", original, re.I):
            continue
        if original not in [entry["original"] for entry in result]:
            result.append({"original": original, "host": parsed.hostname, "port": port,
                           "start": match.start(), "end": match.start() + len(original)})
    return result


class TaskMemory:
    """One task directory with SQLite facts, an evidence journal, and hashed screenshots.

    ``current_observation`` is an in-memory current-frame packet.  Its coordinates
    are deliberately absent from durable semantic graph claims.  Raw screenshot
    files remain available to audit those claims without promoting them to truth.
    """

    def __init__(self, task_id: str, directory: str | Path):
        self.task_id = _text(task_id, 512)
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.screenshots = self.directory / "screenshots"
        self.screenshots.mkdir(exist_ok=True)
        self.observations = self.directory / "observations"
        self.observations.mkdir(exist_ok=True)
        self.journal = self.directory / "events.jsonl"
        self._lock = RLock()
        self.current_observation = None
        self._frames = {}
        self._proposal_frames = {}
        self._action_attempts = {}
        self._latest_sources = {}
        self._contract = None
        self._journal_sequence = 0
        manifest = self.directory / "task-memory.json"
        if manifest.exists():
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if data.get("task_id") != self.task_id or data.get("schema_version") != 1:
                raise ValueError("Task memory directory identity/schema mismatch")
        else:
            self._atomic_json(manifest, {"task_id": self.task_id, "schema_version": 1})
        instruction_file = self.directory / "instruction.json"
        if instruction_file.exists():
            self._contract = json.loads(instruction_file.read_text(encoding="utf-8"))
        self.graph = TaskGraph(self.task_id, journal=self.directory / "task.sqlite")
        for cid, claim in self.snapshot.claims.items():
            if claim["predicate"] == "execution.attempt" and claim["evidence"]["source"] == "agent-decision":
                self._action_attempts[claim["value"]["action_id"]] = {
                    "entity_id": claim["subject"], "attempt_claim_id": cid}
        if self.journal.exists():
            with self.journal.open(encoding="utf-8") as stream:
                for line in stream:
                    if len(line) > 262144:
                        self.graph.close()
                        raise ValueError("Task memory journal record exceeds its bound")
                    row = json.loads(line)
                    self._journal_sequence = max(self._journal_sequence, row["sequence"])
                    if row["kind"] == "observation":
                        frame = row["data"]
                        self._frames[frame["frame_id"]] = frame
                    if row["kind"] == "semantic_proposals" and row["data"].get("source_frame_id"):
                        self._proposal_frames[row["data"]["event_id"]] = row["data"]["source_frame_id"]
                    for cid in row["data"].get("recurring_claim_ids", []):
                        self._latest_sources[cid] = row["data"]["provenance"]

    @property
    def snapshot(self):
        return self.graph.read()

    def read(self):
        return self.graph.read()

    @staticmethod
    def _atomic_json(path, value):
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(dumps(value) + "\n", encoding="utf-8")
        temporary.replace(path)

    def _append(self, kind, data):
        self._journal_sequence += 1
        row = {"sequence": self._journal_sequence, "kind": kind, "task_id": self.task_id,
               "recorded_at": _now(), "revision": self.snapshot.revision, "data": data}
        with self.journal.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(dumps(row) + "\n")
            stream.flush()

    def _event(self, event_id, source, ref, text, extraction, timestamp=None):
        timestamp = timestamp or _now()
        return {"id": event_id, "task_id": self.task_id, "source": source, "ref": str(ref),
                "observed_at": timestamp, "occurred_at": timestamp, "text": text,
                "extraction": extraction}

    def _literal_patch(self, texts, *, namespace):
        snapshot = self.snapshot
        entities, claims, repeated = [], [], []
        # Repeated literal observations point to their original fact and new source
        # in the journal, instead of adding 500 identical candidate claims.
        lookup = {(c["subject"], c["predicate"], dumps(c["value"])): cid
                  for cid, c in snapshot.claims.items() if snapshot.statuses[cid] == "active"}
        for locator, text in texts:
            for url in literal_urls(text):
                rid = "resource:" + digest(url["original"])
                if rid not in snapshot.entities and rid not in {e["id"] for e in entities}:
                    entities.append({"id": rid, "type": "resource", "label": url["original"]})
                facts = [(rid, "resource.url_original", url["original"], []),
                         (rid, "resource.host", url["host"], []),
                         (rid, "resource.task", self.task_id, ["task"])]
                if url["port"] is not None:
                    facts.append((rid, "resource.port", url["port"], []))
                for subject, predicate, value, objects in facts:
                    slot = (subject, predicate, dumps(value))
                    if slot in lookup:
                        repeated.append(lookup[slot])
                        continue
                    cid = namespace + ":literal:" + digest([subject, predicate, value])
                    claim = {"id": cid, "subject": subject, "predicate": predicate, "value": value,
                             "objects": objects, "locator": f"{locator}:chars:{url['start']}:{url['end']}"}
                    claims.append(claim)
                    lookup[slot] = cid
        return {"entities": entities, "claims": claims}, sorted(set(repeated))

    def initialize(self, instruction, *, constraints=(), delivery_files=(), key_semantics=()):
        with self._lock:
            contract = {"instruction": _text(instruction), "constraints": _list_of_text(constraints),
                        "delivery_files": _list_of_text(delivery_files), "key_semantics": _list_of_text(key_semantics)}
            if self._contract is not None and contract != {k: self._contract[k] for k in contract}:
                raise ValueError("Task contract changed; use a new task identity/directory")
            if "task" in self.snapshot.entities:
                self._contract = self._contract or contract
                return {"revision": self.snapshot.revision, "duplicate": True}
            timestamp = self._contract.get("created_at") if self._contract else _now()
            contract["created_at"] = timestamp
            self._atomic_json(self.directory / "instruction.json", contract)
            event_id = "contract:" + digest(contract)
            patch = {"entities": [{"id": "task", "type": "task", "label": self.task_id}], "claims": []}
            patch["claims"].append({"id": event_id + ":goal", "subject": "task", "predicate": "task.goal",
                                    "value": instruction, "locator": "instruction"})
            for predicate, values in (("task.constraint", contract["constraints"]),
                                      ("task.key_semantics", contract["key_semantics"])):
                if values:
                    patch["claims"].append({"id": event_id + ":" + digest(predicate), "subject": "task",
                                            "predicate": predicate, "value": values, "locator": predicate})
            literals, _ = self._literal_patch([("instruction", instruction)], namespace=event_id)
            patch["entities"].extend(literals["entities"])
            patch["claims"].extend(literals["claims"])
            # Delivery filenames are only recognized from literal text; no proposed
            # path is manufactured from a paraphrased target description.
            explicit_files = set(contract["delivery_files"])
            for match in _FILE.finditer(instruction):
                value = match.group(0).rstrip(".,;)]}'")
                if value in explicit_files or literal_urls(value):
                    continue
                explicit_files.add(value)
            if explicit_files:
                patch["claims"].append({"id": event_id + ":files", "subject": "task",
                                       "predicate": "task.delivery_file", "value": sorted(explicit_files),
                                       "locator": "delivery_files_and_instruction_literals"})
            publication = self.graph.ingest(self._event(event_id, "task-contract", self.directory / "instruction.json",
                                                       instruction, patch, timestamp))
            self._contract = contract
            self._append("initialized", {"event_id": event_id, "original_instruction_ref": str(self.directory / "instruction.json")})
            return publication

    def observe(self, frame_id, screenshot, evidence, *, proposals=None):
        with self._lock:
            _text(frame_id, 128)
            if "task" not in self.snapshot.entities:
                raise ValueError("Initialize task memory before observing")
            if not isinstance(screenshot, bytes) or not 1 <= len(screenshot) <= 20 * 1024 * 1024:
                raise ValueError("Screenshot must be bounded bytes")
            if not isinstance(evidence, dict) or set(evidence) != {"summary", "elements"}:
                raise ValueError("Visual evidence must contain summary and elements")
            summary = _text(evidence["summary"], 6000)
            elements = evidence["elements"]
            if not isinstance(elements, list) or len(elements) > 256:
                raise ValueError("Visible control list exceeds its bound")
            texts = [("summary", summary)]
            semantic_elements = []
            for index, element in enumerate(elements):
                if not isinstance(element, dict):
                    raise ValueError("Invalid visible element")
                text = element.get("text", "")
                role = element.get("role", "")
                if not isinstance(text, str) or not isinstance(role, str) or max(len(text), len(role)) > 1000:
                    raise ValueError("Visible control fields exceed their bound")
                _credential_safe({"text": text, "role": role})
                texts.append((f"elements:{index}:text", text))
                semantic_elements.append({"text": text, "role": role})
            sha256 = hashlib.sha256(screenshot).hexdigest()
            path = self.screenshots / (sha256 + ".png")
            if not path.exists():
                path.write_bytes(screenshot)
            previous = self._frames.get(frame_id)
            if previous is not None:
                if previous["sha256"] != sha256 or previous["evidence_hash"] != digest(evidence):
                    raise ValueError("Frame identity cannot be reused for different evidence")
                self.current_observation = {**previous, "evidence": plain(evidence)}
                if proposals is not None:
                    result = self.accept_proposals(proposals, frame_id=frame_id)
                    return {**previous, "duplicate": True, "semantic_proposals": result,
                            "revision": self.snapshot.revision}
                return {**previous, "duplicate": True}
            event_id = "observation:" + digest([frame_id, sha256, evidence])
            patch, repeated = self._literal_patch(texts, namespace=event_id)
            observation_id = "observation:" + digest(frame_id)
            patch["entities"].append({"id": observation_id, "type": "observation", "label": frame_id})
            patch["claims"].append({"id": event_id + ":summary", "subject": observation_id, "predicate": "observation.summary",
                                   "value": summary, "locator": "summary"})
            patch["claims"].append({"id": event_id + ":root", "subject": observation_id,
                                   "predicate": "observation.task", "value": self.task_id,
                                   "objects": ["task"], "locator": "current_screenshot"})
            timestamp = _now()
            # Coordinates never enter graph/journal text.  The immutable source
            # screenshot is kept for auditing/re-grounding a later current frame.
            raw_semantics = dumps({"summary": summary, "elements": semantic_elements})
            semantic_ref = self.observations / (digest([frame_id, sha256, raw_semantics]) + ".json")
            self._atomic_json(semantic_ref, {"summary": summary, "elements": semantic_elements})
            publication = self.graph.ingest(self._event(event_id, "screenshot:" + frame_id, path,
                                                       summary, patch, timestamp))
            provenance = {"source": "screenshot:" + frame_id, "ref": str(path), "frame_id": frame_id,
                          "sha256": sha256, "source_version": sha256, "event_id": event_id,
                          "observed_at": timestamp, "graph_revision": publication["revision"]}
            metadata = {"frame_id": frame_id, "screenshot_ref": str(path), "sha256": sha256,
                        "source_version": sha256, "evidence_hash": digest(evidence), "event_id": event_id,
                        "semantic_evidence_ref": str(semantic_ref),
                        "revision": publication["revision"], "provenance": provenance,
                        "recurring_claim_ids": repeated}
            self._frames[frame_id] = metadata
            for cid in repeated:
                self._latest_sources[cid] = provenance
            self.current_observation = {**metadata, "evidence": plain(evidence)}
            self._append("observation", metadata)
            if proposals is not None:
                metadata = {**metadata, "semantic_proposals": self.accept_proposals(proposals, frame_id=frame_id)}
                metadata["revision"] = self.snapshot.revision
            return metadata

    @staticmethod
    def validate_proposal_structure(proposals):
        """Pure business-schema validation, usable before bounded model repair.

        Evidence admission, geometry/credential rejection and graph transactions
        still belong to accept_proposals; this never writes memory or grants truth.
        """
        if not isinstance(proposals, dict) or set(proposals) != {"entities", "claims"}:
            raise ValueError("Proposal must contain only entities and claims")
        for key in ("entities", "claims"):
            if not isinstance(proposals[key], list) or len(proposals[key]) > _CAPS[key]:
                raise ValueError("Semantic proposal list budget exceeded")
        if len(dumps(proposals).encode("utf-8")) > 131072:
            raise ValueError("Semantic proposal byte budget exceeded")
        for entity in proposals["entities"]:
            if not isinstance(entity, dict) or set(entity) != {"id", "type", "label"}:
                raise ValueError("Invalid semantic entity fields")
            _text(entity["id"], 128)
            _text(entity["label"], 1000)
            if not isinstance(entity["type"], str) or not _NAME.fullmatch(entity["type"]):
                raise ValueError("Invalid semantic entity type")
        for claim in proposals["claims"]:
            mandatory = {"id", "subject", "predicate", "value", "locator"}
            if (not isinstance(claim, dict) or not mandatory <= set(claim) or
                    set(claim) - mandatory - {"objects", "basis", "supersedes", "mode"}):
                raise ValueError("Invalid semantic claim fields")
            for key in ("id", "subject", "locator"):
                _text(claim[key], 500 if key == "locator" else 128)
            if not isinstance(claim["predicate"], str) or not _NAME.fullmatch(claim["predicate"]):
                raise ValueError("Invalid semantic predicate")
            for key in ("objects", "basis", "supersedes"):
                refs = claim.get(key, [])
                if not isinstance(refs, list) or len(refs) > 32 or any(not isinstance(r, str) or not r for r in refs):
                    raise ValueError("Invalid semantic references")

    def accept_proposals(self, proposals, *, frame_id=None, source_ref=None):
        """Accept bounded open-schema semantic proposals bound to a trusted frame.

        Geometry and credential claims are rejected with their original indices.
        Structural errors reject the remaining patch atomically; model errors do
        not terminate the Agent.  The rejected values themselves are not logged.
        """
        with self._lock:
            current = self.current_observation
            if current is None or (frame_id is not None and frame_id != current["frame_id"]):
                return {"accepted": False, "rejected": [{"reason": "no_matching_current_frame"}],
                        "revision": self.snapshot.revision}
            if source_ref is not None and str(source_ref) != current["screenshot_ref"]:
                return {"accepted": False, "rejected": [{"reason": "source_identity_mismatch"}],
                        "revision": self.snapshot.revision}
            rejected = []
            try:
                self.validate_proposal_structure(proposals)
                if not isinstance(proposals, dict) or set(proposals) != {"entities", "claims"}:
                    raise ValueError("Proposal must contain only entities and claims")
                for key in ("entities", "claims"):
                    if not isinstance(proposals[key], list) or len(proposals[key]) > _CAPS[key]:
                        raise ValueError("Semantic proposal list budget exceeded")
                if len(dumps(proposals).encode("utf-8")) > 131072:
                    raise ValueError("Semantic proposal byte budget exceeded")
                snapshot = self.snapshot
                entities = []
                for entity in proposals["entities"]:
                    if not isinstance(entity, dict) or set(entity) != {"id", "type", "label"}:
                        raise ValueError("Invalid semantic entity fields")
                    _text(entity["id"], 128)
                    _text(entity["label"], 1000)
                    if not isinstance(entity["type"], str) or not _NAME.fullmatch(entity["type"]):
                        raise ValueError("Invalid semantic entity type")
                    entities.append(plain(entity))
                claims, repeated, aliases = [], [], {}
                dropped_ids = set()
                lookup = {(c["subject"], c["predicate"], dumps(c["value"]), dumps(c["objects"]), dumps(c["basis"])): cid
                          for cid, c in snapshot.claims.items() if snapshot.statuses[cid] == "active"}
                for index, claim in enumerate(proposals["claims"]):
                    mandatory = {"id", "subject", "predicate", "value", "locator"}
                    if not isinstance(claim, dict) or set(claim) - mandatory - {"objects", "basis", "supersedes", "mode"} or not mandatory <= set(claim):
                        raise ValueError("Invalid semantic claim fields")
                    for key in ("id", "subject", "locator"):
                        _text(claim[key], 500 if key == "locator" else 128)
                    predicate = claim["predicate"]
                    if not isinstance(predicate, str) or not _NAME.fullmatch(predicate):
                        raise ValueError("Invalid semantic predicate")
                    if predicate.casefold().split(".")[-1] in _GEOMETRY_KEYS or _contains_geometry(claim["value"]):
                        rejected.append({"index": index, "id": claim["id"], "reason": "current_frame_geometry_only"})
                        dropped_ids.add(claim["id"])
                        continue
                    try:
                        _credential_safe(claim["value"])
                    except ValueError:
                        rejected.append({"index": index, "reason": "credential_field_or_value"})
                        dropped_ids.add(claim["id"])
                        continue
                    if len(dumps(claim["value"]).encode("utf-8")) > 8192:
                        rejected.append({"index": index, "id": claim["id"], "reason": "semantic_value_budget_exceeded"})
                        dropped_ids.add(claim["id"])
                        continue
                    for key in ("objects", "basis", "supersedes"):
                        refs = claim.get(key, [])
                        if not isinstance(refs, list) or len(refs) > 32 or any(not isinstance(ref, str) or not ref for ref in refs):
                            raise ValueError("Invalid semantic references")
                    slot = (claim["subject"], predicate, dumps(claim["value"]), dumps(claim.get("objects", [])),
                            dumps(claim.get("basis", [])))
                    if slot in lookup and not claim.get("supersedes"):
                        aliases[claim["id"]] = lookup[slot]
                        repeated.append(lookup[slot])
                        continue
                    claims.append((index, plain(claim)))
                while True:
                    invalid = [(index, claim) for index, claim in claims
                               if set(claim.get("basis", []) + claim.get("supersedes", [])) & dropped_ids]
                    if not invalid:
                        break
                    for index, claim in invalid:
                        rejected.append({"index": index, "id": claim["id"], "reason": "rejected_evidence_dependency"})
                        dropped_ids.add(claim["id"])
                    claims = [(index, claim) for index, claim in claims if claim["id"] not in dropped_ids]
                cleaned = []
                for _, claim in claims:
                    for key in ("basis", "supersedes"):
                        if key in claim:
                            claim[key] = [aliases.get(cid, cid) for cid in claim[key]]
                    cleaned.append(claim)
                # Keep a bounded in-memory semantic index while raw frames/logs
                # stay on disk.  Admission failure is a visible memory gap.
                if len(snapshot.entities) + len({e["id"] for e in entities if e["id"] not in snapshot.entities}) > _CAPS["total_entities"] or len(snapshot.claims) + len(cleaned) > _CAPS["total_claims"]:
                    raise ValueError("Durable semantic index capacity exceeded")
                event_id = "semantics:" + digest([current["event_id"], proposals])
                patch = {"entities": entities, "claims": cleaned}
                if not cleaned and all(e["id"] in snapshot.entities for e in entities):
                    publication = {"revision": snapshot.revision, "duplicate": True}
                else:
                    publication = self.graph.ingest(self._event(event_id, "visual-extractor",
                                                               current["screenshot_ref"], "Structured candidate extraction",
                                                               patch))
                provenance = {**current["provenance"], "source": "visual-extractor", "event_id": event_id,
                              "graph_revision": publication["revision"]}
                result = {"accepted": True, "accepted_claim_ids": [c["id"] for c in cleaned],
                          "accepted_entity_ids": [e["id"] for e in entities], "aliases": aliases, "rejected": rejected,
                          "revision": publication["revision"], "recurring_claim_ids": sorted(set(repeated)),
                          "event_id": event_id, "source_frame_id": current["frame_id"], "provenance": provenance}
                self._proposal_frames[event_id] = current["frame_id"]
                for cid in repeated:
                    self._latest_sources[cid] = provenance
                self._append("semantic_proposals", result)
                return result
            except (ValueError, TypeError, KeyError, RecursionError) as error:
                # Fixed descriptions only: invalid model fields/values may contain
                # sensitive strings and TaskGraph validation can quote them.
                result = {"accepted": False, "accepted_claim_ids": [], "rejected": rejected + [
                    {"reason": "invalid_semantic_proposal", "error_type": type(error).__name__}],
                    "revision": self.snapshot.revision}
                self._append("semantic_proposals_rejected", result)
                return result

    def append_action_semantics(self, action, *, frame_id, receipt=None):
        """Keep key/text action meaning without preserving stale pointer coordinates."""
        with self._lock:
            if not isinstance(action, dict) or not isinstance(action.get("type", action.get("name")), str):
                return {"accepted": False, "reason": "invalid_action"}
            kind = action.get("type", action.get("name"))
            semantic = {"type": kind}
            for key in ("text", "key", "keys", "semantic", "target", "description"):
                if key in action:
                    semantic[key] = action[key]
            if set(semantic) == {"type"}:
                return {"accepted": True, "retained": False, "reason": "no_persistent_key_or_text_semantics"}
            try:
                _credential_safe(semantic)
                if _contains_geometry(semantic) or len(dumps(semantic).encode("utf-8")) > 16384:
                    raise ValueError("Action semantic budget/geometry constraint")
            except (TypeError, ValueError):
                return {"accepted": False, "reason": "unsafe_or_oversize_action_semantics"}
            frame = self._frames.get(frame_id)
            if frame is None:
                return {"accepted": False, "reason": "unknown_action_frame"}
            # Copy a small fixed receipt shape only; raw command output belongs in
            # the execution journal and is not assumed to verify a task effect.
            bounded_receipt = {}
            if isinstance(receipt, dict):
                for key in ("status", "returncode", "effect_verified", "action_id"):
                    value = receipt.get(key)
                    if value is None or isinstance(value, (int, bool)) or isinstance(value, str) and len(value) <= 128:
                        bounded_receipt[key] = value
            _credential_safe(bounded_receipt)
            semantic["execution_receipt"] = bounded_receipt
            semantic["effect_status"] = "effect_verified" if bounded_receipt.get("effect_verified") is True else "effect_unverified"
            event_id = "action:" + digest([frame_id, semantic])
            if event_id + ":semantic" in self.snapshot.claims:
                return {"accepted": True, "duplicate": True, "revision": self.snapshot.revision}
            action_id = "action:" + digest([frame_id, semantic])
            patch = {"entities": [{"id": action_id, "type": "action", "label": kind}], "claims": [
                     {"id": event_id + ":semantic", "subject": action_id, "predicate": "action.semantic",
                      "value": semantic, "locator": "action:semantic"},
                     {"id": event_id + ":root", "subject": action_id, "predicate": "action.task",
                      "value": self.task_id, "objects": ["task"], "locator": "action:semantic"}]}
            publication = self.graph.ingest(self._event(event_id, "action-log", frame["screenshot_ref"],
                                                       dumps(semantic), patch))
            self._append("action_semantics", {"event_id": event_id, "frame_id": frame_id,
                                              "claim_id": event_id + ":semantic"})
            return {"accepted": True, "retained": True, "revision": publication["revision"]}

    def record_action_attempt(self, action_id, action, reason, *, frame_id, journal_ref):
        """Publish every action's intent/rationale for graph-scoped retrieval.

        This records a model proposal, not an execution result.  Pointer positions
        remain in the raw execution journal/current frame, never in the semantic
        graph.  The full rationale can be inspected through ``journal_ref`` while
        its graph history uses the same 2,000-character bound as Agent history.
        These general execution claims are deliberately outside mandatory core.
        """
        with self._lock:
            try:
                _text(action_id, 512)
                _text(frame_id, 128)
                journal_ref = _text(str(journal_ref), 2000)
                if not isinstance(action, dict) or not isinstance(action.get("type"), str):
                    raise ValueError("Invalid action intent")
                if not isinstance(reason, str) or len(reason) > 100000:
                    raise ValueError("Invalid rationale")
                _credential_safe(action)
                _credential_safe(reason)
                frame = self._frames.get(frame_id)
                if frame is None:
                    return {"accepted": False, "reason": "unknown_action_frame", "revision": self.snapshot.revision}
                # Validate the entire action first, then deliberately discard
                # only known pointer geometry.  There is no inverse-click guess.
                semantic = {key: plain(value) for key, value in action.items()
                            if key.casefold() not in _GEOMETRY_KEYS}
                if _contains_geometry(semantic) or len(dumps(semantic).encode("utf-8")) > 16384:
                    raise ValueError("Invalid non-coordinate action semantics")
                reason_budget = {"received_chars": len(reason), "retained_chars": min(len(reason), 2000),
                                 "omitted_chars": max(len(reason) - 2000, 0)}
                value = {"action_id": action_id, "action_semantics": semantic,
                         "model_rationale": reason[:2000], "rationale_budget": reason_budget,
                         "raw_action_hash": digest(action), "raw_rationale_hash": digest(reason),
                         "raw_journal_ref": journal_ref,
                         "before_evidence": {"frame_id": frame_id, "ref": frame["screenshot_ref"],
                                             "sha256": frame["sha256"], "source_version": frame["source_version"]},
                         "interpretation": "model_action_intent_not_execution_or_task_success"}
                previous = self._action_attempts.get(action_id)
                if previous is not None:
                    old = self.snapshot.claims[previous["attempt_claim_id"]]["value"]
                    if dumps(old) != dumps(value):
                        return {"accepted": False, "reason": "action_identity_reused", "revision": self.snapshot.revision}
                    return {"accepted": True, "duplicate": True, **previous, "reason_budget": reason_budget,
                            "revision": self.snapshot.revision}
                if len(self.snapshot.claims) + 2 > _CAPS["total_claims"] or len(self.snapshot.entities) + 1 > _CAPS["total_entities"]:
                    return {"accepted": False, "reason": "semantic_index_capacity_exceeded", "revision": self.snapshot.revision}
                entity_id = "attempt:" + digest(action_id)
                event_id = "action-attempt:" + digest([action_id, frame_id, value])
                attempt_claim_id = event_id + ":intent"
                patch = {"entities": [{"id": entity_id, "type": "action_attempt", "label": action_id}], "claims": [
                    {"id": attempt_claim_id, "subject": entity_id, "predicate": "execution.attempt",
                     "value": value, "locator": "action:" + action_id},
                    {"id": event_id + ":task", "subject": entity_id, "predicate": "execution.task",
                     "value": self.task_id, "objects": ["task"], "locator": "action:" + action_id}]}
                publication = self.graph.ingest(self._event(event_id, "agent-decision", journal_ref,
                                                           "Model action intent; full source is the execution journal", patch))
                self._action_attempts[action_id] = {"entity_id": entity_id, "attempt_claim_id": attempt_claim_id}
                result = {"accepted": True, "action_id": action_id, **self._action_attempts[action_id],
                          "frame_id": frame_id, "journal_ref": journal_ref, "reason_budget": reason_budget,
                          "revision": publication["revision"]}
                self._append("action_attempt", result)
                return result
            except (ValueError, TypeError, KeyError, RecursionError):
                # Return a fixed gap rather than leaking a rejected model value.
                return {"accepted": False, "reason": "invalid_action_intent", "revision": self.snapshot.revision}

    def record_action_feedback(self, action_id, *, status, transport_confirmed, effect_verified,
                               evidence_ref, version):
        """Append adapter receipts/effect evidence linked to the original intent.

        A controller return code and an observed effect are separate facts.  A
        verified effect of one action is never converted into task success.
        Explicit subsequent receipts supersede prior receipt versions while
        leaving the original intent and failed branches available for audit.
        """
        with self._lock:
            try:
                _text(action_id, 512)
                _text(status, 64)
                evidence_ref = _text(str(evidence_ref), 2000)
                _text(version, 128)
                if type(transport_confirmed) is not bool or type(effect_verified) is not bool:
                    raise ValueError("Receipt confirmations must be booleans")
                attempt = self._action_attempts.get(action_id)
                if attempt is None:
                    return {"accepted": False, "reason": "unknown_action_attempt", "revision": self.snapshot.revision}
                value = {"action_id": action_id, "status": status, "transport_confirmed": transport_confirmed,
                         "effect_verified": effect_verified,
                         "effect_status": "effect_verified" if effect_verified else "effect_unverified",
                         "evidence_ref": evidence_ref, "source_version": version,
                         "interpretation": "adapter_action_receipt_not_task_success"}
                previous = [(cid, claim) for cid, claim in self.snapshot.claims.items()
                            if claim["subject"] == attempt["entity_id"] and claim["predicate"] == "execution.feedback"
                            and claim["evidence"]["source"] == "execution-feedback"
                            and self.snapshot.statuses[cid] == "active"]
                for cid, claim in previous:
                    if dumps(claim["value"]) == dumps(value):
                        return {"accepted": True, "duplicate": True, "entity_id": attempt["entity_id"],
                                "feedback_claim_id": cid, "revision": self.snapshot.revision}
                    if claim["value"]["source_version"] == version:
                        return {"accepted": False, "reason": "feedback_version_reused", "revision": self.snapshot.revision}
                if len(self.snapshot.claims) + 1 > _CAPS["total_claims"]:
                    return {"accepted": False, "reason": "semantic_index_capacity_exceeded", "revision": self.snapshot.revision}
                event_id = "action-feedback:" + digest([action_id, value])
                claim_id = event_id + ":receipt"
                patch = {"entities": [], "claims": [{"id": claim_id, "subject": attempt["entity_id"],
                         "predicate": "execution.feedback", "value": value, "basis": [attempt["attempt_claim_id"]],
                         "supersedes": [cid for cid, _ in previous], "locator": "action:" + action_id + ":receipt"}]}
                publication = self.graph.ingest(self._event(event_id, "execution-feedback", evidence_ref,
                                                           "Adapter receipt/effect evidence for one action", patch))
                result = {"accepted": True, "action_id": action_id, "entity_id": attempt["entity_id"],
                          "feedback_claim_id": claim_id, "evidence_ref": evidence_ref, "source_version": version,
                          "revision": publication["revision"]}
                self._append("action_feedback", result)
                return result
            except (ValueError, TypeError, KeyError, RecursionError):
                return {"accepted": False, "reason": "invalid_action_feedback", "revision": self.snapshot.revision}

    def core_packet(self, budget_bytes):
        """Reserve whole core facts before any other view receives context budget."""
        with self._lock:
            if isinstance(budget_bytes, bool) or not isinstance(budget_bytes, int) or budget_bytes < 256:
                raise ValueError("Core packet budget must be at least 256 UTF-8 bytes")
            snapshot = self.snapshot
            all_facts = []
            conflicted = {cid for item in snapshot.conflicts for cid in item["claim_ids"]}
            seen = set()
            for cid, claim in snapshot.claims.items():
                category = _PREDICATES.get(claim["predicate"])
                if category is None or snapshot.statuses[cid] != "active":
                    continue
                slot = (category, dumps(claim["value"]))
                if slot in seen:
                    continue
                seen.add(slot)
                provenance = plain(claim["evidence"])
                frame = self._frames.get(provenance["source"].removeprefix("screenshot:")) if provenance["source"].startswith("screenshot:") else None
                if frame is None and provenance["source"] == "visual-extractor":
                    frame = self._frames.get(self._proposal_frames.get(provenance["event_id"]))
                if frame is None and provenance["source"] == "action-log":
                    frame = next((frame for frame in reversed(list(self._frames.values())) if frame["screenshot_ref"] == provenance["ref"]), None)
                if frame:
                    provenance.update(frame_id=frame["frame_id"], sha256=frame["sha256"], source_version=frame["source_version"])
                elif provenance["source"] == "task-contract":
                    provenance["source_version"] = digest(self._contract)
                fact = {"id": cid, "category": category, "subject": claim["subject"], "predicate": claim["predicate"],
                        "value": plain(claim["value"]), "grade": "task_contract" if provenance["source"] == "task-contract" else "candidate",
                        "status": "conflicted" if cid in conflicted else "active", "provenance": provenance,
                        "graph_revision": snapshot.revision}
                if cid in self._latest_sources:
                    fact["latest_provenance"] = self._latest_sources[cid]
                all_facts.append(fact)
            all_facts.sort(key=lambda fact: (_CATEGORIES.index(fact["category"]), fact["grade"] != "task_contract", fact["id"]))
            present = {fact["category"] for fact in all_facts}
            # A missing port is only a gap if a URL was supplied with no explicit
            # port.  No default 80/443 or benchmark-specific value is fabricated.
            gaps = [{"category": category, "code": "not_explicitly_provided"} for category in _CATEGORIES
                    if category not in present and (category != "port" or "url" in present)]
            gaps.extend({"category": fact["category"], "code": "conflicting_core_fact", "claim_id": fact["id"]}
                        for fact in all_facts if fact["status"] == "conflicted")
            packet = {"task_id": self.task_id, "revision": snapshot.revision, "sequence": snapshot.sequence,
                      "facts": [], "gaps": gaps, "budget_bytes": budget_bytes, "used_bytes": 0,
                      "complete": not gaps}
            # Admission reserves a compact overflow ledger up front.  Every
            # omitted fact is identified, rather than truncating its value.
            for fact in all_facts:
                trial = {**packet, "facts": packet["facts"] + [fact]}
                unresolved = len(all_facts) - len(trial["facts"])
                reserve = 192 + unresolved * 90
                if len(dumps(trial).encode("utf-8")) + reserve <= budget_bytes:
                    packet["facts"].append(fact)
                else:
                    packet["gaps"].append({"category": fact["category"], "code": "core_budget_exceeded", "claim_id": fact["id"]})
                    packet["complete"] = False
            # Gaps themselves can exceed a very small budget.  Their summary is
            # still explicit and includes a durable index reference for details.
            if len(dumps(packet).encode("utf-8")) + 32 > budget_bytes:
                gap_counts = {}
                for gap in packet["gaps"]:
                    key = gap["code"] + ":" + gap["category"]
                    gap_counts[key] = gap_counts.get(key, 0) + 1
                packet["facts"] = []
                packet["gaps"] = [{"code": "core_packet_metadata_exceeds_budget", "counts": gap_counts,
                                   "evidence_ref": str(self.directory / "task.sqlite")}]
                packet["complete"] = False
            # At least 256 bytes need not fit verbose provenance metadata.  Return
            # a compact hard gap when that occurs, still within requested bytes.
            if len(dumps(packet).encode("utf-8")) + 32 > budget_bytes:
                packet = {"task_id_digest": digest(self.task_id), "revision": snapshot.revision,
                          "sequence": snapshot.sequence, "facts": [],
                          "gaps": [{"code": "core_packet_metadata_exceeds_budget"}],
                          "complete": False, "budget_bytes": budget_bytes, "used_bytes": 0}
            for _ in range(4):
                measured = len(dumps(packet).encode("utf-8"))
                if measured == packet["used_bytes"]:
                    break
                packet["used_bytes"] = measured
            return packet

    def close(self):
        self.graph.close()
