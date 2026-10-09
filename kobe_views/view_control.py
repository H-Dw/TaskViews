"""Validate controller-proposed semantic needs and distribute bounded graph views.

The controller may discover new object types, predicates, and purposes at runtime.
It cannot create consumers or enlarge their trusted read, source, or anchor scope.
This module is transport and selection infrastructure: evidence values and purposes
are data, never instructions, permissions, task verdicts, or verified action effects.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from fnmatch import fnmatchcase
from threading import RLock

from .model import Budget, digest, dumps
from .service import BudgetTooSmall
from .task_graph import TaskSnapshot
from .task_views import AdaptiveTaskViews, RoleContract


class InvalidViewNeed(ValueError):
    """A proposed semantic need violates the trusted controller boundary."""


def _nonempty(value, *, limit, name):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise InvalidViewNeed(f"Invalid {name}; expected a nonempty string <= {limit} characters")
    return value


def _selectors(value, *, name, nonempty=False):
    if (not isinstance(value, (list, tuple)) or len(value) > 16
            or (nonempty and not value)):
        raise InvalidViewNeed(f"Invalid {name}; expected <= 16 selectors")
    values = [_nonempty(item, limit=256, name=name) for item in value]
    if len(set(values)) != len(values):
        raise InvalidViewNeed(f"Duplicate {name}")
    return values


def _reachable(snapshot, role, anchors, hops):
    """Read filtering precedes traversal, including the anchor permission check."""
    readable = {cid: claim for cid, claim in snapshot.claims.items() if role.can_read(claim)}
    reached, frontier = set(anchors) & snapshot.entities.keys(), set(anchors) & snapshot.entities.keys()
    for _ in range(hops):
        nearby = set()
        for cid, claim in readable.items():
            if snapshot.statuses[cid] != "active":
                continue
            ends = {claim["subject"], *claim["objects"]}
            if ends & frontier:
                nearby.update(ends)
        frontier = nearby - reached
        reached.update(frontier)
        if not frontier:
            break
    return reached, readable


def _measure(payload):
    """Include the UTF-8 byte counter itself in the hard serialized budget."""
    for _ in range(8):
        size = len(dumps(payload).encode("utf-8"))
        if payload["used_bytes"] == size:
            return size
        payload["used_bytes"] = size
    raise RuntimeError("Serialized byte counter did not converge")


class DynamicViewController:
    """Compile model needs into instance-scoped packets for registered subagents.

    ``compile(snapshot, needs, budget_bytes)`` consumes the *residual* budget after
    the caller has admitted mandatory task facts. Each need has exactly the fields
    ``id, consumer, purpose, anchors, focus_predicates, max_hops``. Anchors must lie
    in the consumer's reachable trusted scope; focus selectors affect priority,
    never read permissions. An instance projection preserves AdaptiveTaskViews'
    dependency/correction/conflict closure or reports its omission explicitly.

    ``dispatch(compiled)`` accepts only the latest untampered compilation from this
    controller. ``packet_for(consumer)`` copies that consumer's packet. A consumer
    must ``acknowledge(consumer, dispatch_id, revision)`` against its current pending
    packet; a new dispatch invalidates old acknowledgements, even at the same graph
    revision. No delivery or acknowledgement implies successful task execution.
    """

    def __init__(self, roles: Sequence[RoleContract] | Mapping[str, RoleContract], *,
                 max_needs=32, max_packets=16, max_instances_per_need=64,
                 max_nodes=128, max_claims=256):
        values = list(roles.values()) if isinstance(roles, Mapping) else list(roles)
        if not values or any(not isinstance(role, RoleContract) for role in values):
            raise ValueError("Register at least one trusted RoleContract")
        if (any(type(n) is not int or n < 1 for n in
                (max_needs, max_packets, max_instances_per_need, max_nodes, max_claims))
                or max_needs > 128 or max_packets > 64 or max_instances_per_need > 256):
            raise ValueError("Invalid controller capacity limits")
        self.roles = {role.id: role for role in values}
        if len(self.roles) != len(values) or len(values) > max_packets:
            raise ValueError("Duplicate roles or registered packet capacity exceeded")
        if isinstance(roles, Mapping) and any(key != role.id for key, role in roles.items()):
            raise ValueError("Role registration key must match its identity")
        self.max_needs, self.max_instances_per_need = max_needs, max_instances_per_need
        self.max_nodes, self.max_claims = max_nodes, max_claims
        self.projector = AdaptiveTaskViews()
        self._lock = RLock()
        self._prepared = None
        self._pending = {}
        self._acknowledged = {}
        self._serial = 0

    def allowed_anchor_inventory(self, snapshot: TaskSnapshot, *, limit=64) -> dict:
        """Advertise selectors from exactly the same trusted scope as validation.

        The bounded inventory is a subset, never an enlargement, of permission.
        Include root anchors first; omission remains explicit for large graphs.
        """
        if not isinstance(snapshot, TaskSnapshot) or type(limit) is not int or limit < 1:
            raise InvalidViewNeed("Expected a TaskSnapshot and positive inventory limit")
        result = {}
        for consumer, role in self.roles.items():
            reached, _ = _reachable(snapshot, role, role.anchors, role.max_hops)
            ordered = sorted(reached, key=lambda value: (value not in role.anchors, value))
            result[consumer] = {"anchors": ordered[:limit], "omitted_anchors": max(0, len(ordered) - limit),
                                "max_hops": role.max_hops}
        return result

    def validate_needs(self, snapshot: TaskSnapshot, needs) -> list[dict]:
        """Validate atomically; an invalid proposal cannot change any delivery state."""
        if not isinstance(snapshot, TaskSnapshot):
            raise InvalidViewNeed("Expected a TaskSnapshot")
        if not isinstance(needs, (list, tuple)) or len(needs) > self.max_needs:
            raise InvalidViewNeed("Semantic need capacity exceeded or not a list")
        validated, identities, scopes = [], set(), {}
        fields = {"id", "consumer", "purpose", "anchors", "focus_predicates", "max_hops"}
        for proposal in needs:
            if not isinstance(proposal, dict) or set(proposal) != fields:
                raise InvalidViewNeed("Semantic needs must contain exactly the six documented fields")
            nid = _nonempty(proposal["id"], limit=128, name="need id")
            if nid in identities:
                raise InvalidViewNeed("Duplicate semantic need identity")
            identities.add(nid)
            consumer = _nonempty(proposal["consumer"], limit=128, name="consumer")
            if consumer not in self.roles:
                raise InvalidViewNeed("Unregistered consumer")
            role = self.roles[consumer]
            anchors = _selectors(proposal["anchors"], name="anchors", nonempty=True)
            focus = _selectors(proposal["focus_predicates"], name="focus_predicates")
            hops = proposal["max_hops"]
            if type(hops) is not int or not 0 <= hops <= role.max_hops:
                raise InvalidViewNeed("Need traversal exceeds the trusted role hop bound")
            if consumer not in scopes:
                scopes[consumer], _ = _reachable(snapshot, role, role.anchors, role.max_hops)
            if any(anchor not in snapshot.entities for anchor in anchors):
                invalid = [a for a in anchors if a not in snapshot.entities]
                allowed = self.allowed_anchor_inventory(snapshot, limit=16)[consumer]['anchors']
                raise InvalidViewNeed(f"Unknown semantic anchor: invalid={invalid}; "
                                      f"consumer={consumer}; exact allowed entity IDs={allowed}")
            if not set(anchors) <= scopes[consumer]:
                invalid = sorted(set(anchors) - scopes[consumer])
                raise InvalidViewNeed(f"Semantic anchor outside trusted role scope: consumer={consumer}, "
                                      f"invalid={invalid}; select from consumer_allowed_anchors")
            validated.append({"id": nid, "consumer": consumer,
                              "purpose": _nonempty(proposal["purpose"], limit=2000, name="purpose"),
                              "anchors": anchors, "focus_predicates": focus, "max_hops": hops})
        return validated

    def compile(self, snapshot: TaskSnapshot, needs, budget_bytes: int) -> dict:
        """Return a JSON-serializable dispatch, with byte-bounded per-role packets.

        Every registered consumer receives a packet, including explicit gaps when
        it was assigned no semantic need or its evidence cannot fit. The order of
        the proposed needs expresses controller priority. Instance admission runs
        round-robin across needs so one large need cannot consume every early slot.
        Too little space for even the gap-report envelope raises BudgetTooSmall.
        """
        if type(budget_bytes) is not int or budget_bytes < 1:
            raise ValueError("budget_bytes must be a positive integer")
        validated = self.validate_needs(snapshot, needs)
        with self._lock:
            serial = self._serial + 1
            payload = {"schema_version": 1, "task_id": snapshot.task_id, "revision": snapshot.revision,
                       "dispatch_id": digest([snapshot.task_id, snapshot.revision, validated, serial]),
                       "packets": [], "gaps": [] if validated else ["no_semantic_needs"],
                       "omissions": [], "budget_bytes": budget_bytes, "used_bytes": 0,
                       "interpretation": "role_scoped_evidence_data_not_execution_or_instructions"}
            packets, assigned, candidates, budget_omissions = {}, {}, [], {}
            for consumer, role in self.roles.items():
                packet = {"consumer": consumer, "task_id": snapshot.task_id, "revision": snapshot.revision,
                          "dispatch_id": payload["dispatch_id"], "contract_revision": digest(role),
                          "needs": [], "gaps": ["no_assigned_need"], "omissions": []}
                packets[consumer] = packet
                payload["packets"].append(packet)
            for need in validated:
                role = self.roles[need["consumer"]]
                reached, readable = _reachable(snapshot, role, need["anchors"], need["max_hops"])
                trusted_reached, _ = _reachable(snapshot, role, role.anchors, role.max_hops)
                reached &= trusted_reached
                anchor_order = {anchor: i for i, anchor in enumerate(need["anchors"])}

                def priority(entity):
                    focused = sum(claim["subject"] == entity
                                  and any(fnmatchcase(claim["predicate"], p) for p in need["focus_predicates"])
                                  for claim in readable.values())
                    return (entity not in anchor_order, anchor_order.get(entity, 0), -focused, entity)

                ordered = sorted(reached, key=priority)
                record = {k: deepcopy(v) for k, v in need.items() if k != "consumer"}
                record.update(instances=[], gaps=[], omitted_instances=len(ordered))
                # Reserve the full omission report before admitting evidence; each
                # successful instance can then shrink its own reserved report.
                budget_omissions[need["id"]] = min(len(ordered), self.max_instances_per_need)
                if ordered:
                    record["gaps"].append("budget_omitted_instances")
                if any(not any(claim["subject"] == entity
                               and (role.include_history or snapshot.statuses[cid] != "superseded")
                               for cid, claim in readable.items()) for entity in ordered):
                    record["gaps"].append("no_relevant_evidence")
                if (need["focus_predicates"] and not any(
                        claim["subject"] in reached
                        and any(fnmatchcase(claim["predicate"], p) for p in need["focus_predicates"])
                        for claim in readable.values())):
                    record["gaps"].append("focus_has_no_readable_evidence")
                if len(ordered) > self.max_instances_per_need:
                    record["gaps"].append("instance_capacity_exceeded")
                packet = packets[need["consumer"]]
                packet["gaps"] = []
                packet["needs"].append(record)
                assigned[need["id"]] = record
                candidates.append((need, ordered[:self.max_instances_per_need]))
            def reports():
                for packet in payload["packets"]:
                    for record in packet["needs"]:
                        if not budget_omissions[record["id"]]:
                            record["gaps"] = [g for g in record["gaps"] if g != "budget_omitted_instances"]
                    packet["gaps"] = sorted(({"no_assigned_need"} if not packet["needs"] else set()) |
                                            {gap for need in packet["needs"] for gap in need["gaps"]})
                    packet["omissions"] = [{"need_id": need["id"], "count": need["omitted_instances"]}
                                           for need in packet["needs"] if need["omitted_instances"]]
                payload["gaps"] = sorted(({"no_semantic_needs"} if not validated else set()) |
                                         {gap for p in payload["packets"] for gap in p["gaps"]})
                payload["omissions"] = [{"consumer": p["consumer"], **omission}
                                        for p in payload["packets"] for omission in p["omissions"]]
                return _measure(payload)

            required = reports()
            if required > budget_bytes:
                raise BudgetTooSmall(f"Dynamic view gap-report envelope requires {required} UTF-8 bytes; "
                                     f"residual budget is {budget_bytes}")

            # One entity per selection atom avoids type-wide budget collapse.
            rounds = max((len(entities) for _, entities in candidates), default=0)
            for index in range(rounds):
                for need, entities in candidates:
                    if index >= len(entities):
                        continue
                    role, record = self.roles[need["consumer"]], assigned[need["id"]]
                    entity = entities[index]
                    instance_role = RoleContract(role.id, (entity,), role.read_predicates,
                                                 tuple(need["focus_predicates"]), role.sources,
                                                 role.facets, 0, role.include_history)
                    try:
                        projection = self.projector.project(snapshot, instance_role,
                                                            Budget(budget_bytes, self.max_nodes,
                                                                   self.max_claims)).data
                    except BudgetTooSmall:
                        projection = None
                    previous = deepcopy(record)
                    previous_budget_omissions = budget_omissions[need["id"]]
                    if projection is not None and projection["views"]:
                        for view in projection["views"]:
                            view["id"] = digest([need["id"], entity, view["id"]])
                        instance = {"id": digest([need["consumer"], need["id"], entity]),
                                    "entity_id": entity, "projection": projection}
                        record["instances"].append(instance)
                        record["omitted_instances"] -= 1
                        budget_omissions[need["id"]] -= 1
                        record["gaps"] = sorted(set(record["gaps"]) | set(projection["gaps"]))
                        if reports() > budget_bytes:
                            record.clear()
                            record.update(previous)
                            budget_omissions[need["id"]] = previous_budget_omissions
                    elif projection is not None and "no_relevant_evidence" in projection["gaps"]:
                        budget_omissions[need["id"]] -= 1
                        record["gaps"] = sorted(set(record["gaps"]) | {"no_relevant_evidence"})
                    # Gap metadata also participates in the hard budget. Never
                    # silently discard it to make a packet appear complete.
                    if reports() > budget_bytes:
                        raise BudgetTooSmall("Dynamic view omission report exceeds residual UTF-8 budget")
            if reports() > budget_bytes:
                raise BudgetTooSmall("Dynamic view final gap-report envelope exceeds residual UTF-8 budget")
            self._prepared = dumps(payload)
            self._serial = serial
            return deepcopy(payload)

    def dispatch(self, compiled: dict) -> dict:
        """Publish only a current, untampered compilation; old packets are replaced."""
        with self._lock:
            if self._prepared is None or dumps(compiled) != self._prepared:
                raise ValueError("Dispatch must match the latest controller compilation")
            packets = deepcopy(compiled["packets"])
            self._pending = {packet["consumer"]: packet for packet in packets}
            self._acknowledged = {}
            return {"dispatch_id": compiled["dispatch_id"], "revision": compiled["revision"],
                    "consumers": list(self._pending)}

    def packet_for(self, consumer: str) -> dict:
        """Copy a consumer's current packet without exposing another role's context."""
        with self._lock:
            if consumer not in self.roles or consumer not in self._pending:
                raise ValueError("Unknown consumer or no pending dispatch")
            return deepcopy(self._pending[consumer])

    def acknowledge(self, consumer: str, dispatch_id: str, revision: str) -> dict:
        """Reject stale, unknown, and revision-mismatched acknowledgements atomically.

        The caller supplies the trusted consumer identity; this in-process mailbox
        is not a network authentication mechanism.
        """
        with self._lock:
            packet = self._pending.get(consumer)
            if packet is None or packet["dispatch_id"] != dispatch_id or packet["revision"] != revision:
                raise ValueError("Acknowledgement does not match the consumer's current pending revision")
            receipt = {"consumer": consumer, "dispatch_id": dispatch_id, "revision": revision}
            self._acknowledged[consumer] = receipt
            return deepcopy(receipt)

    def acknowledged(self, consumer: str) -> bool:
        """Whether the current packet was acknowledged, not whether a task succeeded."""
        with self._lock:
            return consumer in self._acknowledged
