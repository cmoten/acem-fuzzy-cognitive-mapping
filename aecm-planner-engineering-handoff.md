# AECM scenario planner engineering handoff

Build a guided application that lets a planner select an AECM concept, define an intervention, compare modeled outcomes, and test ways to mitigate adverse effects. Use the foreign economic assistance exercise as an acceptance fixture. The workflow should support any AECM concept and multiple targets.

## Planner workflow

| Screen | Planner action | Application behavior |
|---|---|---|
| Explore model | Search for concepts and inspect relationships | Show concept definitions, incoming and outgoing edges, signs, and weight provenance. Offer the full model, incident links, or links among selected concepts. Preview concept and edge counts. |
| Set assumptions | Review strengths and enter baselines | Show workbook polarity and signed simulation weight as separate fields. Validate IDs, bounds, and duplicate edges. Allow supported edge additions, removals, and weight edits. Identify illustrative assumptions. |
| Define intervention | Enter targets, increments, and schedule | Show targets in each concept’s declared units. Create a no-intervention control with the same model and baselines. Explain that feedback can move final values away from targets. |
| Review outcomes | Run scenarios and inspect effects | Show run status and per-increment diagnostics. Compare final values, plot ranked signed differences, and allow trajectory drill-down. Use percentage points for normalized values and declared units otherwise. |
| Explore risk | Choose an adverse outcome and vary selected weights | Offer a one-edge sweep and Monte Carlo ranges. Show direction, signed bounds, distribution, draw count, seed, convergence count, and 5th/50th/95th percentiles. |
| Test a safeguard | Describe a measure and specify its hypothesized effect | Show the affected link, proposed change, rationale, and evidence. Compare aid plus safeguard with aid alone using paired draws. Also show aid plus safeguard against the no-intervention control. |
| Save and share | Record findings and export | Include assumptions, provenance, run IDs, model version, solver settings, qualified results, and failed draw counts. |

Treat positive changes as score increases. Let the planner label outcomes as favorable, adverse, or context-dependent. Keep the modeled link change, proposed real-world measure, and evidence for its effect visible together.

## Implementation

Use the existing Python solver as the numerical engine. Bind a run to an immutable snapshot of the model and scenario. For long-running simulations, return a run ID promptly and expose queued, running, completed, partially converged, or failed status. Render previous results with their original assumptions when a planner edits a draft.

- **Workshop option.** Use linked model and scenario records, input forms, and result tables or charts. Route execution through a backend run request and expose completed results through the project’s approved data access path.
- **React option.** Use the same run contract with a custom concept explorer, signed-weight editor, and linked results views. Use authenticated project APIs and server-side authorization. Keep execution and durable run storage in the backend.

Confirm deployment and execution mechanisms with the Foundry project team. Route the application through one backend contract so both interfaces can use the same validation and solver. In the repository, `build_aecm_model` builds a full or reduced model, `build_fsdm_scenario` binds baselines and targets, `run_fsdm_scenario` returns trajectory and diagnostics, and `run_fsdm_monte_carlo` samples independent uniform signed weights and compares each draw with a matched control.

### Data contract

| Record | Grain and required fields |
|---|---|
| Model version | Model/version ID, source and import timestamp, topology and weight provenance |
| Concept | Model version + node ID, name, definition, group if present, min/max and units |
| Edge | Model version + source/target IDs, workbook polarity, signed simulation weight, rationale |
| Scenario revision | Revision ID, model version, subset selection, edge overrides, per-node baseline and optional target, solver mode, increments, tolerance, iteration limit |
| Experiment request | Scenario revision, comparison type, outcome selection, sweep values or signed sampling ranges, explicit edge sampling order, seed and draw count, optional safeguard transform and rationale |
| Run | Run ID, experiment ID, status, input snapshot, solver version, timestamps, convergence counts and errors |
| Results | Trajectory keyed by run, arm, draw if applicable, increment and concept. Diagnostics keyed by run, arm, draw and increment. Store final changes, sampled weights and draw status for the audit trail. |

Store wide or long analytical tables as datasets. Expose model, scenario, and run records as Ontology objects where browsing and linking help planners. Enforce existing project permissions on model access, edit actions, run submission, and results access. Apply a project-defined draw limit and make submissions idempotent for retries.

### Comparison and failure semantics

- Deterministic effect equals intervention final minus control final, joined by concept ID.
- Sweep a single edge across a user-provided grid. Hold all other inputs fixed and report each point’s convergence.
- For Monte Carlo, save a draw ID and sampled weight per edge. Use the same draw in the intervention and its control. Report percentiles only over converged pairs and show the contributing count and total requested.
- For paired safeguard comparisons, generate the sample table once. Apply the safeguard transform to the selected weights while preserving the original draw IDs and every other sampled weight. Use the intersection of successful draws for paired deltas. The existing Python walkthrough reproduces pairing by reusing the seed and edge order. Explicitly consuming a shared sample table requires a backend extension or orchestration around the solver.
- Mark out-of-domain and nonconverged attempts with their diagnostics. Display failed or missing outcomes as unavailable, and distinguish partial success from a completed all-converged run.

## Acceptance fixture

Use the workbook’s `EconAssistForeign` anchor with incident selection. Expect 11 concepts and 13 directed links. Use the workbook signs with magnitude 0.05, baseline 0.50, target 0.60, and 10 exponential increments with the solver defaults.

1. Both deterministic arms converge 10/10. Assistance ends at 0.599878 in the intervention. Crisis changes by −0.005490 and corruption by +0.005490 relative to control.
2. Changing the aid-to-corruption weight to +0.02 yields a corruption final score of 0.502203. The six-point sweep from 0 to 0.05 produces a monotonic increase in the corruption effect.
3. The three-link Monte Carlo with 200 draws and seed 42 converges 200/200. In this order, use aid-to-corruption [0, 0.05], aid-to-crisis [−0.075, −0.025], and aid-to-growth [0.025, 0.075]. Median changes are 0.002637, −0.005461, and 0.005516 respectively.
4. Multiplying each sampled aid-to-corruption weight by 0.4 yields 200 matched safeguard pairs. The median safeguard effect on corruption is about −0.158 percentage points. Check displayed values against the walkthrough to its reported precision.
5. Submit an unknown target and an invalid range and verify field-level errors. Exercise a nonconverged draw and confirm that it appears in run status and contributes no percentile observations. Reopen a saved run and verify that its assumptions and results can be traced to the original inputs.

See [the analysis walkthrough](foreign-aid-analysis.md) for executable reproduction steps and planning interpretation.
