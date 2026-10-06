"""Task projections for UI-KOBE and other GUI agent runtimes."""
from .adapters import UIKobeAdapter, control_id, observation_nodes, page_id
from .model import Assertion, Budget, Edge, EvidenceRef, Grade, Node, Request, Snapshot, View, ViewKind
from .runtime import RuntimeBridge
from .service import BudgetTooSmall, ProjectionService, StaleHandle
from .store import GraphStore
from .task_graph import RevisionConflict, TaskExtractor, TaskGraph, TaskSnapshot
from .task_views import AdaptiveTaskViews, RoleContract, task_view_delta
from .task_memory import TaskMemory
from .view_control import DynamicViewController, InvalidViewNeed
from .recovery import RecoveryConflict, RecoveryJournal

__all__ = ["Assertion", "Budget", "BudgetTooSmall", "Edge", "EvidenceRef", "Grade",
           "GraphStore", "Node", "ProjectionService", "Request", "RuntimeBridge", "Snapshot",
           "StaleHandle", "UIKobeAdapter", "View", "ViewKind", "control_id", "observation_nodes", "page_id",
           "AdaptiveTaskViews", "RevisionConflict", "RoleContract", "TaskExtractor", "TaskGraph", "TaskSnapshot",
           "task_view_delta", "TaskMemory", "DynamicViewController", "InvalidViewNeed",
           "RecoveryJournal", "RecoveryConflict"]
