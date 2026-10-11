# UI-KOBE and TaskViews execution boundary

The completed 2026-10-07 Task059 UI-KOBE-like run used 42 native decisions and 77 commands, returned original official score 0.2, and performed no adviser requests. Its saved construction contained the image, manual points, a fitted function and a derived volume. Task046 also completed with score 1.0, but took 441 decisions. Completion is not evidence that the method is always fast or accurate.

Sources: the read-only `docs/experiments/osworld21-kimi-k3-task059-20261007-native-v7-max16/ui_kobe_like/{report.md,scored-terminal-inspection.json,telemetry/events-13480.jsonl}` and the corresponding Task046 report. The new V12 comparison diagnosis records their hashes and the original evaluation event. Earlier baseline and TaskViews experiments use different providers/configurations; no controlled Qwen performance claim follows from those scores.

| Boundary | UI-KOBE / completed native UI-KOBE-like | V12 before this repair | Repair |
| --- | --- | --- | --- |
| Low-level execution | Original task, current image, native history/compiler; bounded recorded transitions | Same shared native predict/generation/history/compiler | Shared execution unchanged |
| Graph/role reasoning | Original mobile UI-KOBE selects a local instruction; native UI-KOBE-like retrieves actual edges without adviser calls | Classification, module details, graph views and adviser reports compete for actor input | Keep classification and full reports in TaskViews memory/trace; actor gets stable subgoal, local brief and operation evidence |
| Pointer source | Execution model grounds the current screenshot | Observer bounding boxes were also supplied to actor | Remove observer boxes from actor projection; no parameter conversion or coordinate correction |
| Failed operation | Next current screenshot/recorded attempt | One `not_observed` could trigger global classification and planning again | Always retain action-bound feedback; refresh planning for repetition, page/subgoal changes or initial needs |
| Evidence priority | Recent actual edges | Step56 omitted visible evidence while retaining assigned graph views | Protect bounded whole current labels, latest operation and unresolved failure references before optional module detail |

Current original V12 steps54–58 repeat ineffective window preparation. Several observer boxes do not match the original 1920×1080 screenshot. This supports an input contamination risk, not a proven provider coordinate convention or a justification to rescale coordinates. The raw observations, rejected responses, native tool arguments, receipts and screenshots remain unchanged.

The repair applies only inside opt-in feedback TaskViews. It preserves the raw image, original task, native IDs/history, strict action/identity/content guards, output/deadline budgets, serial GUI and official evaluator. Classified views still drive role/subgoal selection; they are not discarded from memory. Current-view literal text remains a fallible model proposal, with whole-value omission counts under its budget. A single unobserved attempt does not certify success or suppress escalation after repeated failures.

Validation covers exact geometry separation, UTF-8 boundaries, trigger/escalation behavior, persistence of action/image/receipt/unresolved references, and an offline full input→object→save→native termination→fixture scoring loop. The fixture uses mock provider/controller/QMP; its score is not an OSWorld result. Real improvement must be established by new original Task059 actions and eventual official evaluation, with the existing goal of at least0.2.

## Original intent and intended result

The follow-up original steps59–67 exposed a separate defect: actor prose repeatedly said the window was not maximized, while perception called a menu/focus change observed. The stored native `local_instruction` was null in this run; the actual intended operation is in the original decision `response`. Supplying only the action-type-derived focus/state expectation lost that distinction. The comparison did not prove improved mouse grounding or task artifacts.

The next opt-in feedback repair reads the immutable original actor prose into a bounded adviser-only `actor_intent` projection. It preserves whole prose up to1200 UTF-8 bytes or omits the whole value with its exact source/hash/length. Serialized native tool messages without prose do not create an intention. Batch prose remains decision-scoped, with the original command index/count; later screenshot commands remain separate evidence.

Perception checks intended result separately from generic focus/text/submission. An observed intent must name existing before/current state keys whose known values changed for that result; unknown/not_observed intent prevents generic focus success from becoming overall observed. A missing/omitted intention or ambiguous batch effect must stay unknown. The schema guard verifies provenance, binding, evidence and state differences; semantic relevance still depends on the visual model and cannot be proved by these structural checks alone. No old assessment, native parameter, coordinate, command or receipt is rewritten. Optional window preparation must not consume the task indefinitely when the current UI offers another ordinary route to the requested deliverable.

Regression cases distinguish menu dismissal from actual maximization, verify genuine relevant state changes, reject clock/new-key evidence, preserve oversized original prose and batch/capture boundaries, and run the complete mock object/save/end workflow with intent checks. These tests are not official scores or evidence that Qwen can ground the real screenshot correctly.
