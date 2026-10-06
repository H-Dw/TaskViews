"""Atomic snapshot publication. Projections never mutate source knowledge."""
from __future__ import annotations

from threading import RLock
from .model import Edge, Node, Snapshot


class GraphStore:
    def __init__(self):
        self._lock = RLock()
        self._snapshot = Snapshot.create([], [])

    def read(self) -> Snapshot:
        with self._lock:
            return self._snapshot

    def replace(self, snapshot: Snapshot) -> None:
        with self._lock:
            self._snapshot = snapshot

    def update(self, *, nodes: tuple[Node, ...] = (), edges: tuple[Edge, ...] = (),
               remove_nodes: tuple[str, ...] = (), remove_edges: tuple[str, ...] = ()) -> Snapshot:
        """Upsert complete entities; deletion cascades incident edges atomically."""
        with self._lock:
            ns, es = dict(self._snapshot.nodes), dict(self._snapshot.edges)
            for node_id in remove_nodes:
                ns.pop(node_id, None)
            # Removing a page also removes entities owned by that page.
            ns = {nid: n for nid, n in ns.items() if n.page_id not in remove_nodes}
            for edge_id in remove_edges:
                es.pop(edge_id, None)
            ns.update((n.id, n) for n in nodes)
            es = {k: e for k, e in es.items() if e.source in ns and e.target in ns}
            es.update((e.id, e) for e in edges)
            next_snapshot = Snapshot.create(list(ns.values()), list(es.values()))
            self._snapshot = next_snapshot
            return next_snapshot
