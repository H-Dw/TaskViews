"""Evidence-gated stage recovery with durable, reverse-order compensation.

This module never invents an inverse from a click, guesses an effect from a
controller return code, or executes GUI actions. A trusted adapter registers
compensation contracts and verifies fresh observations. Each returned inverse
is ONE ordinary action; the caller accounts for it in its normal step budget.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import RLock


class RecoveryConflict(ValueError):
    """The persisted journal changed in another writer."""


def _text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise ValueError(f"{name} must be a bounded nonempty string")
    return value


def _json(value):
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _proof(value):
    if not isinstance(value, dict):
        raise ValueError("Evidence needs source, ref and version")
    return {k: _text(value.get(k), k) for k in ("source", "ref", "version")}


def _state(value):
    if not isinstance(value, dict) or not isinstance(value.get("facts", {}), dict):
        raise ValueError("Observed state needs a facts object")
    return {**_proof(value), "resource": _text(value.get("resource"), "resource"),
            "facts": _json(value.get("facts", {}))}


def _guard(value, *, resource_required=True):
    if not isinstance(value, dict) or set(value) - {"resource", "facts"}:
        raise ValueError("A guard contains only resource and facts")
    if not isinstance(value.get("facts", {}), dict):
        raise ValueError("Guard facts must be an object")
    result = {"facts": _json(value.get("facts", {}))}
    if "resource" in value or resource_required:
        result["resource"] = _text(value.get("resource"), "guard resource")
    return result


def _action(value):
    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
        raise ValueError("A compensation is one structured action with a type")
    # A transaction/macro cannot hide several GUI steps in one inverse.
    if value["type"] in {"done", "fail", "macro", "sequence", "batch"}:
        raise ValueError("Terminal actions and action sequences cannot compensate")
    if "actions" in value:
        raise ValueError("A compensation cannot contain an action list")
    return _json(value)


def _contract(value):
    if not isinstance(value, dict) or set(value) != {"action", "guard", "postcondition", "evidence", "verified"}:
        raise ValueError("A compensation needs action, guard, postcondition, evidence and verified")
    if type(value["verified"]) is not bool:
        raise ValueError("Compensation verification must be explicit")
    result = {"action": _action(value["action"]), "guard": _guard(value["guard"]),
              "postcondition": _guard(value["postcondition"]), "evidence": _proof(value["evidence"]),
              "verified": value["verified"]}
    if result["verified"] and (not result["guard"]["facts"] or not result["postcondition"]["facts"]):
        raise ValueError("Verified compensation needs nonempty semantic guard and postcondition facts")
    return result


def _matches(state, guard):
    if "resource" in guard and state["resource"] != guard["resource"]:
        return False
    return all(k in state["facts"] and state["facts"][k] == v for k, v in guard["facts"].items())


def _fresh(after, before):
    # A second verifier naming the SAME observation is not a new after-state.
    return (after["ref"], after["version"]) != (before["ref"], before["version"])


class RecoveryJournal:
    """Append-only action/effect/checkpoint journal, optionally persisted in SQLite.

    ``verified`` is an adapter attestation, NEVER a model-generated field. State
    facts use exact JSON values; no substring, URL normalization or coordinate
    correction is performed. Compensation coordinates, when present, are bound
    to the guard observation version and must be registered afresh for a new
    frame. SQLite commits intent before ``next_compensation`` returns an action.
    """

    def __init__(self, task_id, path: str | Path | None = None, *, max_actions=1024, max_events=16384,
                 max_record_bytes=65536):
        self.task_id = _text(task_id, "task_id")
        if any(type(n) is not int or n < 1 for n in (max_actions, max_events, max_record_bytes)):
            raise ValueError("Journal limits must be positive integers")
        self.max_actions, self.max_events, self.max_record_bytes = max_actions, max_events, max_record_bytes
        self._lock, self._db, self._closed, self._seq = RLock(), None, False, 0
        self._actions, self._order, self._checkpoints, self._compensations = {}, [], [], {}
        self._plan = None
        if path is not None:
            self._db = sqlite3.connect(str(path), check_same_thread=False)
            try:
                self._db.execute("CREATE TABLE IF NOT EXISTS recovery_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                self._db.execute("CREATE TABLE IF NOT EXISTS recovery_events "
                                 "(seq INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
                recorded = dict(self._db.execute("SELECT key, value FROM recovery_meta"))
                if recorded and recorded != {"task_id": self.task_id, "schema": "1"}:
                    raise ValueError("Recovery journal belongs to another task or schema")
                if not recorded:
                    self._db.executemany("INSERT INTO recovery_meta VALUES (?, ?)",
                                         [("task_id", self.task_id), ("schema", "1")])
                self._db.commit()
                for seq, payload in self._db.execute("SELECT seq, payload FROM recovery_events ORDER BY seq"):
                    if seq != self._seq + 1 or seq > self.max_events or len(payload.encode("utf-8")) > max_record_bytes:
                        raise ValueError("Invalid or oversized recovery journal")
                    event = json.loads(payload)
                    self._validate(event)
                    self._apply(event)
                    self._seq = seq
            except Exception:
                self._db.close()
                raise

    def close(self):
        with self._lock:
            if self._db is not None:
                self._db.close()
            self._closed = True

    def _validate(self, event):
        kind, data = event["kind"], event["data"]
        if kind == "action":
            if data["id"] in self._actions:
                raise ValueError("Action id was already recorded")
            if len(self._order) >= self.max_actions:
                raise ValueError("Action journal budget exhausted")
            if self._plan is not None and self._plan["status"] in {"ready", "awaiting_checkpoint_verification"}:
                raise ValueError("Cannot append forward actions during active recovery")
        elif kind in {"receipt", "effect", "contract"}:
            if data["id"] not in self._actions:
                raise ValueError("Unknown action id")
        elif kind == "reversible_attestation":
            row = self._actions.get(data["id"])
            if row is None:
                raise ValueError("Unknown action id")
            if row["barrier"] != "unclassified_or_external_effect":
                raise ValueError("Only an unclassified barrier can be cleared; irreversible barriers remain")
            contract = row["compensation"]
            if not row["transport_confirmed"] or not row["effect_verified"] or contract is None or \
                    not contract["verified"]:
                raise ValueError("Reversibility requires confirmed transport, verified effect and verified compensation")
            if data["evidence"] != _proof(row["after_state"]) or data["evidence"] != contract["evidence"]:
                raise ValueError("Reversibility evidence must match verified effect and compensation proof")
        elif kind == "checkpoint":
            if self._plan is not None and self._plan["status"] in {"ready", "awaiting_checkpoint_verification"}:
                raise ValueError("Cannot create a checkpoint during active recovery")
            if any(c["id"] == data["id"] for c in self._checkpoints):
                raise ValueError("Checkpoint id was already recorded")
            if data["verified"] and any(not self._actions[i]["effect_verified"] for i in self._order):
                raise ValueError("A checkpoint cannot skip unverified action effects")
        elif kind == "plan":
            pass
        elif kind == "checkpoint_restored":
            if self._plan is None or self._plan["status"] != "awaiting_checkpoint_verification":
                raise ValueError("No checkpoint awaiting recovery verification")
        elif kind == "compensation_intent":
            if data["id"] in self._compensations:
                raise ValueError("Compensation intent was already recorded")
            if self._plan is None or self._plan["status"] != "ready":
                raise ValueError("No ready recovery plan")
            if self._plan["pending"] is not None:
                raise ValueError("Pending compensation must be observed before another inverse")
        elif kind in {"compensation_receipt", "compensation_effect"}:
            if data["id"] not in self._compensations:
                raise ValueError("Unknown compensation id")
        else:
            raise ValueError("Unknown recovery event")

    def _commit(self, kind, data):
        if self._closed:
            raise ValueError("Recovery journal is closed")
        if self._seq >= self.max_events:
            raise ValueError("Recovery event budget exhausted")
        event = {"kind": kind, "data": _json(data), "at": datetime.now(timezone.utc).isoformat()}
        payload = json.dumps(event, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if len(payload.encode("utf-8")) > self.max_record_bytes:
            raise ValueError("Recovery record exceeds byte budget")
        self._validate(event)
        if self._db is not None:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                sequence = self._db.execute("SELECT COALESCE(MAX(seq), 0) FROM recovery_events").fetchone()[0]
                if sequence != self._seq:
                    raise RecoveryConflict("Recovery journal changed in another writer")
                self._db.execute("INSERT INTO recovery_events VALUES (?, ?)", (self._seq + 1, payload))
                self._db.commit()
            except Exception:
                self._db.rollback()
                raise
        self._apply(event)
        self._seq += 1

    def _apply(self, event):
        kind, data = event["kind"], event["data"]
        if kind == "action":
            self._actions[data["id"]] = {**data, "sequence": len(self._order) + 1,
                                         "status": "dispatch_intent", "receipt": None,
                                         "transport_confirmed": False, "after_state": None,
                                         "effect_verified": False, "compensated": False,
                                         "initial_barrier": data["barrier"], "classification_evidence": None}
            self._order.append(data["id"])
        elif kind == "receipt":
            row = self._actions[data["id"]]
            row.update(receipt=data["result"], transport_confirmed=data["confirmed"])
            if not row["effect_verified"]:
                row["status"] = "transport_confirmed" if data["confirmed"] else "effect_unknown"
        elif kind == "effect":
            row = self._actions[data["id"]]
            row.update(after_state=data["state"], effect_verified=data["verified"],
                       status="effect_verified" if data["verified"] else "effect_unknown")
        elif kind == "contract":
            self._actions[data["id"]]["compensation"] = data["contract"]
        elif kind == "reversible_attestation":
            self._actions[data["id"]].update(barrier=None, classification_evidence=data["evidence"])
        elif kind == "checkpoint":
            self._checkpoints.append(data)
        elif kind == "plan":
            self._plan = data
        elif kind == "compensation_intent":
            self._compensations[data["id"]] = {**data, "status": "dispatch_intent", "receipt": None,
                                               "transport_confirmed": False, "after_state": None,
                                               "effect_verified": False}
            self._plan["pending"] = data["id"]
        elif kind == "compensation_receipt":
            row = self._compensations[data["id"]]
            row.update(receipt=data["result"], transport_confirmed=data["confirmed"])
            if not row["effect_verified"]:
                row["status"] = "transport_confirmed" if data["confirmed"] else "effect_unknown"
        elif kind == "compensation_effect":
            row = self._compensations[data["id"]]
            row.update(after_state=data["state"], effect_verified=data["verified"],
                       status="effect_verified" if data["verified"] else "effect_unknown")
            if data["verified"]:
                self._actions[row["original_action_id"]]["compensated"] = True
                self._plan["completed"].append(row["original_action_id"])
                self._plan["pending"] = None
                if len(self._plan["completed"]) == len(self._plan["action_ids"]):
                    checkpoint = next(c for c in self._checkpoints if c["id"] == self._plan["checkpoint_id"])
                    expected = {"resource": checkpoint["state"]["resource"], "facts": checkpoint["state"]["facts"]}
                    if _matches(data["state"], expected):
                        self._plan.update(status="complete", restored_state=data["state"])
                    else:
                        self._plan.update(status="awaiting_checkpoint_verification",
                                          reasons=["checkpoint_postcondition_unverified"])
        elif kind == "checkpoint_restored":
            self._plan.update(status="complete", restored_state=data["state"], reasons=[])

    def record_action(self, action_id, action, before_state, *, compensation=None, barrier=None):
        """Persist intent BEFORE handing the forward action to a controller."""
        with self._lock:
            if not isinstance(action, dict) or not isinstance(action.get("type"), str):
                raise ValueError("Action needs a structured type")
            data = {"id": _text(action_id, "action_id"), "action": _json(action),
                    "before_state": _state(before_state),
                    "compensation": _contract(compensation) if compensation is not None else None,
                    "barrier": _text(barrier, "barrier") if barrier is not None else None}
            self._commit("action", data)
            return self.action(action_id)

    def receipt(self, action_id, result, *, confirmed):
        with self._lock:
            if type(confirmed) is not bool:
                raise ValueError("Receipt confirmation must be explicit")
            self._commit("receipt", {"id": action_id, "result": _json(result), "confirmed": confirmed})

    def observe_effect(self, action_id, after_state, *, verified):
        with self._lock:
            row = self._actions.get(action_id)
            if row is None:
                raise ValueError("Unknown action id")
            state = _state(after_state)
            if type(verified) is not bool or verified and not _fresh(state, row["before_state"]):
                raise ValueError("Effect verification requires explicit attestation and fresh observation")
            self._commit("effect", {"id": action_id, "state": state, "verified": verified})

    def register_compensation(self, action_id, action, *, guard, postcondition, evidence, verified):
        with self._lock:
            contract = _contract({"action": action, "guard": guard, "postcondition": postcondition,
                                  "evidence": evidence, "verified": verified})
            self._commit("contract", {"id": action_id, "contract": contract})

    def attest_reversible(self, action_id, evidence):
        """Classify a previously unknown effect using trusted, matching proofs.

        Only the generic unclassified barrier can be cleared. A recorded send,
        submission or external approval stays a barrier even if a model proposes
        an apparent inverse. The original classification remains in the journal.
        """
        with self._lock:
            evidence = _proof(evidence)
            row = self._actions.get(action_id)
            if row is None:
                raise ValueError("Unknown action id")
            if row["barrier"] is None and row["initial_barrier"] == "unclassified_or_external_effect" and \
                    row["classification_evidence"] == evidence:
                return self.action(action_id)
            self._commit("reversible_attestation", {"id": action_id, "evidence": evidence})
            return self.action(action_id)

    def checkpoint(self, checkpoint_id, state, *, prerequisites=None, verified):
        with self._lock:
            state = _state(state)
            if type(verified) is not bool:
                raise ValueError("Checkpoint verification must be explicit")
            self._commit("checkpoint", {"id": _text(checkpoint_id, "checkpoint_id"), "state": state,
                         "prerequisites": _guard(prerequisites if prerequisites is not None else
                                                 {"resource": state["resource"], "facts": state["facts"]},
                                                 resource_required=False),
                         "verified": verified, "action_sequence": len(self._order)})

    def _candidate(self, current_state):
        eligible = [c for c in self._checkpoints if c["verified"] and _matches(current_state, c["prerequisites"])]
        if not eligible:
            reason = "checkpoint_prerequisites_changed" if any(c["verified"] for c in self._checkpoints) \
                else "no_verified_checkpoint"
            return {"status": "unavailable", "checkpoint_id": None, "action_ids": [], "reasons": [reason]}
        checkpoint = eligible[-1]
        ids = [aid for aid in reversed(self._order[checkpoint["action_sequence"]:])
               if not self._actions[aid]["compensated"]]
        reasons = []
        for aid in ids:
            row = self._actions[aid]
            if row["barrier"]:
                reasons.append(f"recovery_barrier:{aid}:{row['barrier']}")
            if not row["effect_verified"]:
                reasons.append(f"effect_unverified:{aid}")
            contract = row["compensation"]
            if contract is None or not contract["verified"]:
                reasons.append(f"no_verified_compensation:{aid}")
        return {"status": "blocked" if reasons else "ready" if ids else "complete",
                "checkpoint_id": checkpoint["id"], "action_ids": ids, "reasons": reasons}

    def plan_recovery(self, current_state):
        """Select newest valid checkpoint; never cross an unknown/irreversible effect."""
        with self._lock:
            current_state = _state(current_state)
            if self._plan is not None and self._plan["status"] in {"ready", "awaiting_checkpoint_verification"}:
                return self._public_plan()
            plan = {**self._candidate(current_state), "completed": [], "pending": None,
                    "id": f"recovery-{self._seq + 1}", "selected_state": current_state}
            self._commit("plan", plan)
            return self._public_plan()

    def _public_plan(self):
        result = deepcopy(self._plan)
        if result is not None and result["pending"] is not None:
            result["status"] = "blocked"
            result["reasons"] = [f"compensation_effect_unverified:{result['pending']}"]
        return result

    def _next_blockers(self, current_state):
        checkpoint = next(c for c in self._checkpoints if c["id"] == self._plan["checkpoint_id"])
        if not _matches(current_state, checkpoint["prerequisites"]):
            return ["checkpoint_prerequisites_changed"]
        aid = self._plan["action_ids"][len(self._plan["completed"])]
        row = self._actions[aid]
        contract = row["compensation"]
        if row["barrier"] or not row["effect_verified"] or contract is None or not contract["verified"]:
            return [f"compensation_authority_changed:{aid}"]
        if not _matches(current_state, contract["guard"]):
            return [f"compensation_guard_changed:{aid}"]
        if any(k in contract["action"] for k in ("x", "y", "to_x", "to_y")) and \
                _proof(current_state) != contract["evidence"]:
            return [f"compensation_geometry_stale:{aid}"]
        return []

    def next_compensation(self, current_state):
        """Return one registered action after persisting its intent, or blockers."""
        with self._lock:
            current_state = _state(current_state)
            if self._plan is None:
                self.plan_recovery(current_state)
            if self._plan["status"] != "ready" or self._plan["pending"] is not None:
                return {"status": "blocked", "recovery": self._public_plan(), "action": None}
            reasons = self._next_blockers(current_state)
            if reasons:
                return {"status": "blocked", "reasons": reasons, "action": None}
            aid = self._plan["action_ids"][len(self._plan["completed"])]
            contract = self._actions[aid]["compensation"]
            cid = f"{self._plan['id']}:inverse:{len(self._plan['completed']) + 1}"
            data = {"id": cid, "original_action_id": aid, "action": contract["action"],
                    "before_state": current_state, "postcondition": contract["postcondition"],
                    "contract_evidence": contract["evidence"]}
            self._commit("compensation_intent", data)
            return {"status": "ready", **deepcopy(data)}

    def compensation_receipt(self, compensation_id, result, *, confirmed):
        with self._lock:
            if type(confirmed) is not bool:
                raise ValueError("Receipt confirmation must be explicit")
            self._commit("compensation_receipt", {"id": compensation_id, "result": _json(result),
                                                   "confirmed": confirmed})

    def observe_compensation(self, compensation_id, after_state, *, verified):
        """Fresh verified postcondition can resolve a lost receipt after a crash.

        An absent receipt stays absent in evidence. Re-observation, rather than
        blindly executing the inverse a second time, is the only way forward.
        """
        with self._lock:
            row = self._compensations.get(compensation_id)
            if row is None or self._plan is None or self._plan["pending"] != compensation_id:
                raise ValueError("Compensation is not the current pending inverse")
            state = _state(after_state)
            if type(verified) is not bool or verified and (not _fresh(state, row["before_state"]) or
                                                          not _matches(state, row["postcondition"])):
                raise ValueError("Compensation requires a fresh verified matching postcondition")
            self._commit("compensation_effect", {"id": compensation_id, "state": state, "verified": verified})

    def verify_recovery_checkpoint(self, current_state, *, verified):
        """Finish recovery only after separately proving the target stage itself."""
        with self._lock:
            if self._plan is None or self._plan["status"] != "awaiting_checkpoint_verification":
                raise ValueError("No checkpoint awaiting recovery verification")
            state = _state(current_state)
            checkpoint = next(c for c in self._checkpoints if c["id"] == self._plan["checkpoint_id"])
            expected = {"resource": checkpoint["state"]["resource"], "facts": checkpoint["state"]["facts"]}
            if type(verified) is not bool or not verified or not _matches(state, expected) or \
                    not _fresh(state, self._plan["selected_state"]):
                raise ValueError("Restored checkpoint requires fresh verified matching stage state")
            self._commit("checkpoint_restored", {"state": state})

    def fail_gate(self, current_state, *, gaps=(), resource_verified=False):
        """Treat a model FAIL as a proposal; check facts, resource and safe path first."""
        with self._lock:
            current_state = _state(current_state)
            if not isinstance(gaps, (list, tuple)) or any(not isinstance(g, str) or not g for g in gaps):
                raise ValueError("Evidence gaps must be explicit nonempty strings")
            if type(resource_verified) is not bool:
                raise ValueError("Resource identity verification must be explicit")
            base = {"gaps": list(gaps), "recovery": None, "reasons": []}
            if gaps:
                return {**base, "action": "replan", "status": "evidence_gap", "reasons": list(gaps)}
            if not resource_verified:
                return {**base, "action": "replan", "status": "resource_unverified",
                        "reasons": ["current_resource_identity_unverified"]}
            plan = self.plan_recovery(current_state)
            base["recovery"], base["reasons"] = plan, plan["reasons"]
            if plan["status"] == "ready":
                reasons = self._next_blockers(current_state)
                if reasons:
                    return {**base, "action": "replan", "status": "recovery_blocked", "reasons": reasons}
                return {**base, "action": "recover", "status": "recovery_ready"}
            if plan["status"] in {"blocked", "awaiting_checkpoint_verification"} and \
                    any("unverified" in r for r in plan["reasons"]):
                return {**base, "action": "replan", "status": "recovery_blocked"}
            return {**base, "action": "fail", "status": "no_safe_recovery"}

    def action(self, action_id):
        with self._lock:
            if action_id not in self._actions:
                raise ValueError("Unknown action id")
            return deepcopy(self._actions[action_id])

    def state(self):
        """Small runtime status; does not load/copy the complete receipt history."""
        with self._lock:
            return {"task_id": self.task_id, "sequence": self._seq, "action_count": len(self._order),
                    "checkpoint_count": len(self._checkpoints), "compensation_count": len(self._compensations),
                    "last_action_id": self._order[-1] if self._order else None, "recovery": self._public_plan()}

    def snapshot(self):
        with self._lock:
            return {**self.state(), "actions": deepcopy([self._actions[i] for i in self._order]),
                    "checkpoints": deepcopy(self._checkpoints), "compensations": deepcopy(self._compensations)}
