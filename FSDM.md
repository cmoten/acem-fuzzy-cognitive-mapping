# AECM Fuzzy Systems Dynamics Model

`fsdm.py` requires NumPy and pandas. Install openpyxl in environments that
read the Excel workbook. The solver can also use tables from Foundry directly.

```python
from fsdm import load_aecm, simulate

nodes, signs = load_aecm("AECM 2.0 Model.xlsx")
baseline = dict.fromkeys(signs.index, 50.0)
trajectory, diagnostics = simulate(
    signs * 0.05, baseline, {"AgTech": 51.0}, increments=10
)
```

The workbook defines topology and polarity. The example uses illustrative
baselines, target, and uniform strength. For analysis, supply scenario-specific
baseline and target values on the internal 0–100 scale (exclusive endpoints)
and signed edge strengths in [-1, 1]. Zero denotes an absent edge. Targets
are incremental interventions and can receive feedback during propagation.
Increment zero is the baseline. Check `diagnostics.converged` for every
increment before interpreting results. The solver raises on values outside the
operating domain, which can happen when reinforcing effects aggregate.

The implementation follows the additive multiparent rule in the
[R source](https://github.com/gregorbj/FSDM/blob/63f8c517e8b931fcb0d45f3e4b01ae6f16dbefdc/R/fsdm.R).
The older [documentation](https://github.com/gregorbj/FSDM/tree/master/inst/documentation)
describes a multiplicative variant. This implementation returns increment
endpoints and diagnostics and uses the internal scale throughout.

## Running an FSDM JSON directory

`load_fsdm_model(model_dir)` creates a reusable model from the concept catalog
and signed weights. Use `load_fsdm_scenario(scenario_dir, model)` to bind
baseline values, intervention targets, and increments to it, then call
`run_fsdm_scenario(scenario)`. The CLI detects the R layout
`models/AECM/scenarios/IncreasePeace` and also accepts `--model-dir`.

To generate a new reduced model and scenario in memory, pass the full AECM
edge table with `From`, `To`, and `Valence` columns to
`generate_increase_peace(edges, seed=42)`. It follows the reduction and
random sampling rules in `aecm-fsdm.R`. The seed reproduces Python draws.
Reuse the saved JSON to recover the exact draws from the original R run.

The final section of the R script runs an FCMapper comparison with 25
iterations and a fixed PeaceOps value of 1. The Python runner uses FSDM's
incremental target and feedback rules, so the analyses answer different questions.

For a directory containing `concepts.json`, `relations.json`, `scenario.json`,
and `increments.json`, run the complete validation, simulation, and summary
workflow with:

```bash
python fsdm.py /path/to/IncreasePeace --output-dir results
```

This uses the reference fuzzy weights (`VL=.01`, `L=.20`, `ML=.35`, `M=.50`,
`MH=.67`, `H=.85`, `VH=1`) and exponential intervention increments. The
output directory receives `trajectory.csv`, `diagnostics.csv`, and
`summary.csv`; the source JSON is not changed.

If a dense reinforcing model exceeds the operating range, the command stops
and names the affected concepts. Calibrate the relationship strengths rather
than silently clipping the state. For sensitivity analysis, uniformly scale
the canonical weights, for example with `--weight-scale 0.5`; this is an
analytical assumption and should be recorded with the results.

The same workflow is available from Python:

```python
from fsdm import load_fsdm_directory, run_fsdm_directory

scenario = load_fsdm_directory("/path/to/IncreasePeace")
trajectory, diagnostics, summary = run_fsdm_directory(
    "/path/to/IncreasePeace"
)

print(scenario.weights.loc["PeaceOps"].loc[lambda values: values.ne(0)])
print(summary.head(10))
```

`trajectory.value` is converted back to the ranges declared by each concept;
`trajectory.scaled_value` retains the internal 0–100 solver value. Do not
interpret results unless every row in `diagnostics.converged` is true.

## Foundry integration

### Datasets and Ontology objects

Start with datasets for the simulation and promote records to Ontology
objects when analysts need to browse, link, or edit them in an app.

| Dataset | Recommended grain and fields | Ontology recommendation |
| --- | --- | --- |
| `aecm_nodes` | One row per node per model version. Keep `node_id` (workbook abbreviation), `name`, `topic`, and `definition`. | **AECM Concept** object. Use the abbreviation as the primary key if exposing one version. Use a stable version-qualified key if multiple versions coexist. |
| `aecm_edges` | One row per directed source–target pair per model version. Keep `source`, `target`, workbook `polarity`, and calibrated signed `weight` when available. | For graph navigation, expose a many-to-many **Influences** link backed by a join table. If users need to inspect or curate weight, rationale, or provenance, expose **AECM Influence** as an object with distinct links to its source and target concepts. |
| `aecm_scenarios` and `aecm_scenario_inputs` | One scenario header with `scenario_id`, model version, name, schedule, and solver settings. One input row per scenario and node, with `baseline` and nullable `target`. | Expose **AECM Scenario** if analysts need to select or manage scenarios. Keep input rows in a dataset unless analysts need to edit individual inputs in an Ontology app. |
| `aecm_runs`, `aecm_trajectory`, and `aecm_diagnostics` | One run header per `run_id` with scenario and model version. Trajectory has one row per run, increment, and node. Diagnostics has one row per run and increment. | Expose **AECM Simulation Run** if users need run history or status. Keep per-increment results in datasets. Publish a compact final-value or scenario-comparison view if an app needs it. |

Use the edge list as the canonical graph table after validating it against the
adjacency matrix. Keep the original workbook for provenance and derive the
dense matrix inside the transform. Store polarity separately from calibrated
weight so the workbook's signs remain traceable. Version the topology and
weights, and record which version and scenario inputs each run used.

Validate unique keys, known endpoint IDs, and one baseline per model node
before simulation. When joining across versions, include the version in the
key. Give forward and reverse Ontology links distinct names such as
**Influences** and **Influenced by** to preserve direction.

See Palantir's guides for [object types](https://www.palantir.com/docs/foundry/object-link-types/create-object-type)
and [link types](https://www.palantir.com/docs/foundry/object-link-types/create-link-type).

### Transform example

Put `fsdm.py` in your Python package. The example below assumes two small
tabular input datasets. The links dataset uses `source`, `target`, and signed
numeric `weight`. The scenario dataset has exactly one row per node with
`node_id`, `baseline`, and nullable `target`. Replace the dataset identifiers
and module import with the ones in your repository.

```python
from transforms.api import Input, Output, transform

from myproject.fsdm import simulate


@transform(
    links=Input("ri.foundry.main.dataset.LINKS"),
    scenario=Input("ri.foundry.main.dataset.SCENARIO"),
    values_out=Output("ri.foundry.main.dataset.VALUES"),
    diagnostics_out=Output("ri.foundry.main.dataset.DIAGNOSTICS"),
)
def compute(ctx, links, scenario, values_out, diagnostics_out):
    nodes = scenario.dataframe().toPandas().set_index("node_id", verify_integrity=True)
    edges = links.dataframe().toPandas()
    if not edges["source"].isin(nodes.index).all() or not edges["target"].isin(nodes.index).all():
        raise ValueError("Every link endpoint must appear in the scenario.")
    if edges["weight"].isna().any():
        raise ValueError("Link weights must be populated.")
    weights = (
        edges.pivot(index="source", columns="target", values="weight")
        .reindex(index=nodes.index, columns=nodes.index)
        .fillna(0.0)
    )
    values, diagnostics = simulate(
        weights, nodes["baseline"].to_dict(), nodes["target"].dropna().to_dict()
    )
    values_out.write_dataframe(ctx.spark_session.createDataFrame(values))
    diagnostics_out.write_dataframe(ctx.spark_session.createDataFrame(diagnostics))
```

To seed these datasets from Excel, use `load_aecm` and convert nonzero entries
in the returned matrix to edge rows, assigning calibrated magnitudes as
available. Join the node catalog to scenario observations by `node_id`.
For a PNG using the existing plot helper, pivot selected trajectory rows with
`index="node_id", columns="increment", values="value"` and pass the matrix to
`plot_net_change`.
