"""FSDM scenario solver based on gregorbj/FSDM's Apache-2.0 R implementation."""
import argparse
import json
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_FUZZY_WEIGHTS = {
    "VL": 0.01, "L": 0.20, "ML": 0.35, "M": 0.50,
    "MH": 0.67, "H": 0.85, "VH": 1.00,
}
DEFAULT_SIGNS = {"Positive": 1.0, "Negative": -1.0}
INCREASE_PEACE_LINKS = {
    "TradeForeign": 1, "PeaceOps": 1, "IOCampaigns": -1, "MilAid": 1,
    "RuleofLaw": 1, "PolStability": 1, "SocialFragment": -1,
    "DomPolInterfere": -1, "MilSecCoop": 1,
}


@dataclass(frozen=True)
class FSDMModel:
    """Reusable concept metadata and signed source-by-target weights."""

    concepts: pd.DataFrame
    weights: pd.DataFrame


@dataclass(frozen=True)
class FSDMScenario:
    """Validated model and scenario inputs loaded from an FSDM directory."""

    concepts: pd.DataFrame
    weights: pd.DataFrame
    baseline: dict[str, float]
    targets: dict[str, float]
    increments: int
    operating_range: tuple[float, float]

def _read_json(path):
    try:
        with Path(path).open(encoding="utf-8") as stream:
            return json.load(stream)
    except FileNotFoundError as error:
        raise ValueError(f"Missing required FSDM file: {path}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in {path}: {error}") from error


def _rescale(value, source_range, target_range):
    source_min, source_max = source_range
    target_min, target_max = target_range
    return target_min + (value - source_min) * (target_max - target_min) / (
        source_max - source_min
    )


def load_fsdm_directory(directory, *, fuzzy_weights=None,
                        operating_range=(0.01, 99.99), model_directory=None):
    """Load and validate an FSDM model/scenario directory.

    Accepts colocated JSON files or the R layout with model files above
    scenarios/<name>. Pass model_directory to select the model explicitly.
    """
    directory = Path(directory)
    if model_directory is None:
        local = [directory / name for name in ("concepts.json", "relations.json")]
        model_directory = (
            directory.parent.parent
            if directory.parent.name == "scenarios" and not any(p.exists() for p in local)
            else directory
        )
    model = load_fsdm_model(model_directory, fuzzy_weights=fuzzy_weights)
    return load_fsdm_scenario(directory, model, operating_range=operating_range)


def load_fsdm_model(directory, *, fuzzy_weights=None):
    """Read the reusable model files from an R-style model directory."""
    directory = Path(directory)
    fuzzy_weights = DEFAULT_FUZZY_WEIGHTS if fuzzy_weights is None else fuzzy_weights
    if set(fuzzy_weights) != set(DEFAULT_FUZZY_WEIGHTS):
        raise ValueError("fuzzy_weights must define VL, L, ML, M, MH, H, and VH.")
    fuzzy_weights = {key: float(value) for key, value in fuzzy_weights.items()}
    if not all(np.isfinite(value) and 0 <= value <= 1 for value in fuzzy_weights.values()):
        raise ValueError("Fuzzy weights must be finite values in [0, 1].")
    concept_records = _read_json(directory / "concepts.json")
    relation_records = _read_json(directory / "relations.json")
    return _build_model(concept_records, relation_records, fuzzy_weights)


def _build_model(concept_records, relation_records, fuzzy_weights):
    if not isinstance(concept_records, list) or not concept_records:
        raise ValueError("concepts.json must be a non-empty JSON array.")

    concepts = pd.DataFrame(concept_records)
    required = {"name", "variable", "values"}
    if not required <= set(concepts):
        raise ValueError(f"Concepts must contain fields: {sorted(required)}")
    if concepts["variable"].isna().any() or concepts["variable"].duplicated().any():
        raise ValueError("Concept variables must be populated and unique.")
    ids = pd.Index(concepts["variable"].astype(str), name="node_id")

    ranges = []
    for node_id, values in zip(ids, concepts["values"]):
        if not isinstance(values, dict) or not {"min", "max"} <= set(values):
            raise ValueError(f"Concept {node_id!r} has no valid min/max range.")
        low, high = float(values["min"]), float(values["max"])
        if not np.isfinite([low, high]).all() or low >= high:
            raise ValueError(f"Concept {node_id!r} has an invalid value range.")
        ranges.append((low, high))
    concepts = concepts.copy()
    concepts["node_id"] = ids
    concepts["min_value"] = [item[0] for item in ranges]
    concepts["max_value"] = [item[1] for item in ranges]
    concepts = concepts.set_index("node_id")

    if not isinstance(relation_records, list):
        raise ValueError("relations.json must be a JSON array.")
    relation_sources = [str(record.get("name")) for record in relation_records]
    if (len(relation_sources) != len(set(relation_sources))
            or set(relation_sources) != set(ids)):
        raise ValueError("Relations must contain exactly one entry for every concept.")
    weights = pd.DataFrame(0.0, index=ids, columns=ids)
    seen_edges = set()
    for record in relation_records:
        source = str(record["name"])
        affects = record.get("affects", [])
        if not isinstance(affects, list):
            raise ValueError(f"The affects field for {source!r} must be an array.")
        for edge in affects:
            target = str(edge.get("variable"))
            direction = edge.get("direction")
            label = edge.get("weight")
            if target not in ids:
                raise ValueError(f"Relation {source!r} -> {target!r} has an unknown target.")
            if direction not in DEFAULT_SIGNS or label not in fuzzy_weights:
                raise ValueError(
                    f"Relation {source!r} -> {target!r} has an invalid direction or weight."
                )
            if (source, target) in seen_edges:
                raise ValueError(f"Duplicate relation: {source!r} -> {target!r}.")
            seen_edges.add((source, target))
            weights.at[source, target] = DEFAULT_SIGNS[direction] * fuzzy_weights[label]
    return FSDMModel(concepts, weights)


def load_fsdm_scenario(directory, model, *, operating_range=(0.01, 99.99)):
    """Bind scenario files to a reusable model."""
    directory = Path(directory)
    return _build_scenario(
        model, _read_json(directory / "scenario.json"),
        _read_json(directory / "increments.json"), operating_range,
    )


def _build_scenario(model, scenario_records, increment_data, operating_range):
    if (len(operating_range) != 2
            or not 0 < operating_range[0] < operating_range[1] < 100):
        raise ValueError("operating_range must be an increasing pair inside (0, 100).")
    concepts, weights = model.concepts, model.weights
    ids = concepts.index

    if not isinstance(scenario_records, list):
        raise ValueError("scenario.json must be a JSON array.")
    scenario = pd.DataFrame(scenario_records)
    if not {"name", "startvalue"} <= set(scenario):
        raise ValueError("Scenario records must contain name and startvalue.")
    if (scenario["name"].duplicated().any()
            or set(scenario["name"].astype(str)) != set(ids)):
        raise ValueError("Scenario must contain exactly one row for every concept.")
    scenario["name"] = scenario["name"].astype(str)
    scenario = scenario.set_index("name").reindex(ids)

    baseline = {}
    targets = {}
    for node_id in ids:
        source_range = (concepts.at[node_id, "min_value"],
                        concepts.at[node_id, "max_value"])
        start = float(scenario.at[node_id, "startvalue"])
        if not np.isfinite(start) or not source_range[0] <= start <= source_range[1]:
            raise ValueError(f"Start value for {node_id!r} is outside its declared range.")
        baseline[node_id] = _rescale(start, source_range, operating_range)
        change = scenario.at[node_id, "startchange"] if "startchange" in scenario else None
        if change is not None and not pd.isna(change) and str(change).upper() != "NA":
            change = float(change)
            if not np.isfinite(change) or not source_range[0] <= change <= source_range[1]:
                raise ValueError(f"Target value for {node_id!r} is outside its declared range.")
            targets[node_id] = _rescale(change, source_range, operating_range)
    if isinstance(increment_data, list) and len(increment_data) == 1:
        increment_data = increment_data[0]
    if (isinstance(increment_data, bool) or not isinstance(increment_data, int)
            or increment_data < 1):
        raise ValueError("increments.json must contain a positive integer or [positive integer].")
    return FSDMScenario(concepts, weights, baseline, targets, increment_data,
                        tuple(operating_range))


def build_aecm_model(weights, *, nodes=None, anchors=None, selection="incident",
                     edge_updates=None, value_ranges=None):
    """Build a model from signed weights, such as the matrix from load_aecm.

    edge_updates maps (source, target) to a signed weight or None to remove
    a link. Updates may introduce new concepts. With anchors, incident keeps
    their neighbors and links touching an anchor; induced keeps only links
    between anchors. Values default to a normalized 0–1 range.
    """
    ids = weights.index
    if (not ids.is_unique or ids.hasnans or not weights.columns.is_unique
            or set(ids) != set(weights.columns)):
        raise ValueError("Weight axes must contain the same unique concept IDs.")
    if selection not in {"incident", "induced"}:
        raise ValueError("selection must be 'incident' or 'induced'.")
    weights = weights.loc[ids, ids].astype(float)
    updates = edge_updates or {}
    for (source, target), value in updates.items():
        if value is not None:
            ids = ids.union([source, target], sort=False)
    weights = weights.reindex(index=ids, columns=ids, fill_value=0.0)
    for (source, target), value in updates.items():
        if source not in ids or target not in ids:
            raise ValueError(f"Unknown endpoint for {source!r} -> {target!r}.")
        weights.at[source, target] = 0.0 if value is None else float(value)
    values = weights.to_numpy()
    if not np.isfinite(values).all() or (np.abs(values) > 1).any():
        raise ValueError("Signed weights must be finite and in [-1, 1].")
    known_ids = set(ids)
    if anchors is not None:
        anchor_ids = set(anchors)
        if not anchor_ids or not anchor_ids <= set(ids):
            raise ValueError("anchors must contain one or more known concept IDs.")
        selected = ids.isin(anchor_ids)
        if selection == "incident":
            weights = weights.where(selected[:, None] | selected[None, :], 0.0)
            linked = weights.ne(0).to_numpy()
            selected |= linked.any(axis=0) | linked.any(axis=1)
        ids = ids[selected]
        weights = weights.loc[ids, ids]
    if ids.empty:
        raise ValueError("The model must contain at least one concept.")
    if nodes is None:
        concepts = pd.DataFrame(index=ids)
    else:
        metadata = nodes.set_index("node_id")
        if not metadata.index.is_unique or metadata.index.hasnans:
            raise ValueError("Node metadata must contain unique, populated IDs.")
        concepts = metadata.reindex(ids)
    concepts.index = concepts.index.rename("node_id")
    if "name" not in concepts:
        concepts["name"] = ids
    else:
        concepts["name"] = concepts["name"].fillna(concepts.index.to_series())
    ranges = value_ranges or {}
    if not set(ranges) <= known_ids:
        raise ValueError("Value ranges must refer to known concept IDs.")
    bounds = np.array([ranges.get(node, (0.0, 1.0)) for node in ids], dtype=float)
    if (bounds.shape != (len(ids), 2) or not np.isfinite(bounds).all()
            or (bounds[:, 0] >= bounds[:, 1]).any()):
        raise ValueError("Each concept needs finite increasing min/max bounds.")
    concepts[["min_value", "max_value"]] = bounds
    return FSDMModel(concepts, weights)


def build_fsdm_scenario(model, baseline, targets=None, *, increments=10,
                        operating_range=(0.01, 99.99)):
    """Create a scenario from values in the model's declared concept units."""
    targets = {} if targets is None else targets
    ids = set(model.concepts.index)
    if set(baseline) != ids or not set(targets) <= ids:
        raise ValueError("Supply a baseline for every concept and targets only for known concepts.")
    rows = [{"name": node, "startvalue": value, "startchange": targets.get(node)}
            for node, value in baseline.items()]
    return _build_scenario(model, rows, increments, operating_range)


def generate_increase_peace(edges, *, seed, increments=10):
    """Build model and scenario objects from the full AECM From/To/Valence table."""
    rng = np.random.default_rng(seed)
    anchors = list(INCREASE_PEACE_LINKS)
    retained = edges.loc[
        edges["From"].isin(anchors) | edges["To"].isin(anchors),
        ["From", "To", "Valence"],
    ]
    extra = pd.DataFrame({
        "From": anchors,
        "To": "AccessandInfluence",
        "Valence": ["Pos" if sign > 0 else "Neg" for sign in INCREASE_PEACE_LINKS.values()],
    })
    reduced = pd.concat([retained, extra], ignore_index=True)
    ids = list(dict.fromkeys([*reduced["From"], *reduced["To"]]))
    concepts = [
        {"name": node, "variable": node, "group": "Outcomes", "values": {"min": 0, "max": 1}}
        for node in ids
    ]
    outgoing = {node: [] for node in ids}
    labels = rng.choice(["VL", "L", "M", "H", "VH"], size=len(reduced))
    directions = {"pos": "Positive", "neg": "Negative"}
    for (source, target, valence), label in zip(reduced.itertuples(index=False, name=None), labels):
        direction = directions.get(str(valence).strip().lower())
        if direction is None:
            raise ValueError(f"Invalid AECM valence for {source!r} -> {target!r}: {valence!r}")
        outgoing[source].append({"variable": target, "direction": direction, "weight": label})
    relations = [{"name": node, "affects": outgoing[node]} for node in ids]
    model = _build_model(concepts, relations, DEFAULT_FUZZY_WEIGHTS)
    scenario_rows = []
    for node, baseline in zip(ids, rng.uniform(0.01, 0.99, size=len(ids))):
        row = {"name": node, "startvalue": baseline}
        if node == "PeaceOps":
            proposed_target = baseline * 1.1
            row["startchange"] = 0.99 if proposed_target > 1 else proposed_target
        scenario_rows.append(row)
    return model, _build_scenario(model, scenario_rows, increments, (0.01, 99.99))


def _read_aecm_dataset(dataset_alias):
    """Read a registered workspace alias, including CSV multi-line headers."""
    from foundry.transforms import Dataset

    dataset = Dataset.get(dataset_alias)
    schema = dataset.schema
    csv_params = schema.text_parser_params
    # read_table(format="pandas") does not support CSV skip_lines > 1.
    # Use the declared schema so preamble/header rows are not treated as data.
    if schema.format.value == "CSV" and csv_params and csv_params.skip_lines > 1:
        columns = [column.name for column in schema.columns]
        frames = []
        for file in dataset.files():
            with Path(file.download()).open(encoding="utf-8-sig", newline="") as stream:
                # Foundry counts physical lines, not parsed CSV records (the
                # original Excel headers contain embedded newlines).
                for _ in range(csv_params.skip_lines):
                    stream.readline()
                frames.append(pd.read_csv(
                    stream, header=None, names=columns,
                    sep=csv_params.field_delimiter,
                    quotechar=csv_params.quote_character,
                ))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=columns)
    return dataset.read_table(format="pandas")


def load_aecm(workbook=None):
    """Load AECM datasets and return ``(nodes, matrix)`` as pandas DataFrames.

    By default, read the Foundry node-definition, edge-list, and matrix datasets.
    Nodes have node_id, name, topic, and definition columns; the signed matrix
    has source IDs on rows and target IDs on columns, ordered to match nodes.
    The edge list is used to validate the matrix, not returned separately.
    Pass a workbook path to retain the original Excel-loading behavior.
    """
    if workbook is None:
        # The Jupyter sidecar resolves aliases from .foundry/aliases.yml,
        # not dataset RIDs.
        nodes = _read_aecm_dataset("cmoten_acem_node_definition")
        edges = _read_aecm_dataset("cmoten_acem_edge_list")
        matrix = _read_aecm_dataset("cmoten_acem_adjacency_matrix")
        matrix = matrix.set_index("Row__From_NodeColumn__To_Node")
    else:
        with pd.ExcelFile(workbook, engine="openpyxl") as excel:
            nodes = excel.parse("AECM 2.0 Node Definitions")
            edges = excel.parse("AECM 2.0 Edgelist")
            matrix = excel.parse("AECM 2.0 Adjacency Matrix", header=1, index_col=0)
    nodes = nodes.rename(columns={
        "AECM_NodeAbbreviation": "node_id",
        "AECM_Node_Name": "name",
        "Topic_Area": "topic",
        "AECM_Node_Definition": "definition",
        "AECM Node\nAbbreviation": "node_id",
        "AECM \nNode Name": "name",
        "Topic Area": "topic",
        "AECM Node Definition": "definition",
    })
    ids = nodes.set_index("node_id", verify_integrity=True).index
    if (
        ids.hasnans or not matrix.index.is_unique or not matrix.columns.is_unique
        or set(ids) != set(matrix.index) or set(ids) != set(matrix.columns)
    ):
        raise ValueError("Node definitions and matrix axes must contain the same unique IDs.")
    matrix = matrix.loc[ids, ids].rename_axis(index="source", columns="target")
    if edges.duplicated(["From", "To"]).any():
        raise ValueError("Duplicate directed edges in the AECM edge list.")
    expected = pd.DataFrame(0, index=ids, columns=ids)
    for source, target, valence in edges[["From", "To", "Valence"]].itertuples(index=False, name=None):
        sign = {"pos": 1, "neg": -1}.get(str(valence).strip().lower())
        if source not in ids or target not in ids or sign is None:
            raise ValueError(f"Invalid edge: {source!r}, {target!r}, {valence!r}")
        expected.at[source, target] = sign
    if not np.array_equal(matrix.to_numpy(), expected.to_numpy()):
        raise ValueError("The AECM edge list disagrees with the adjacency matrix.")
    return nodes, matrix


def simulate(weights, baseline, targets, *, increments=100, mode="linear",
             max_iterations=100, tolerance=0.01):
    """Run an FSDM scenario and return long-form values and increment diagnostics.

    weights is a DataFrame with source IDs on rows and target IDs on columns.
    baseline maps every node to a value in (0, 100). targets maps the subset
    being driven to values on the same scale. tolerance is a percent change.
    """
    ids = weights.index
    if (
        ids.empty or ids.hasnans or not ids.is_unique or not weights.columns.is_unique
        or set(ids) != set(weights.columns)
    ):
        raise ValueError("Weight rows and columns must contain identical unique node IDs.")
    matrix = weights.loc[ids, ids].to_numpy(dtype=float)
    if not np.isfinite(matrix).all() or (np.abs(matrix) > 1).any():
        raise ValueError("Weights must be finite and in [-1, 1].")
    if set(baseline) != set(ids) or not set(targets) <= set(ids):
        raise ValueError("Supply a baseline for every node and targets only for known nodes.")
    if (
        mode not in {"linear", "exponential"}
        or not isinstance(increments, int) or increments < 1
        or not isinstance(max_iterations, int) or max_iterations < 1
        or not np.isfinite(tolerance) or tolerance <= 0
    ):
        raise ValueError("Invalid schedule, iteration limits, or convergence tolerance.")
    values = np.array([baseline[node] for node in ids], dtype=float)
    driven = ids.get_indexer(list(targets))
    target_values = np.array(list(targets.values()), dtype=float)
    supplied = np.r_[values, target_values]
    if not ((supplied > 0) & (supplied < 100)).all():
        raise ValueError("Baseline and target values must be strictly between 0 and 100.")

    sources, destinations = np.nonzero(matrix)
    edge_weights = matrix[sources, destinations]
    history = [values.copy()]
    diagnostics = []
    for step in range(1, increments + 1):
        remaining = increments - step + 1
        ratios = np.ones(len(ids))
        current = values[driven]
        if mode == "linear":
            ratios[driven] = 1 + (target_values - current) / remaining / current
        else:
            ratios[driven] = (target_values / current) ** (1 / remaining)
        values = values * ratios

        for iteration in range(1, max_iterations + 1):
            source_ratio = ratios[sources]
            source_now = values[sources]
            rising = source_ratio >= 1
            proportional_change = source_ratio - 1
            source_before = source_now[rising] / source_ratio[rising]
            proportional_change[rising] = (
                (source_now[rising] - source_before) / (100 - source_before)
            )
            signed_effect = edge_weights * proportional_change
            target_now = values[destinations]
            headroom = np.where(signed_effect > 0, 100 - target_now, target_now)
            delta = np.bincount(destinations, weights=signed_effect * headroom, minlength=len(ids))
            updated = values + delta
            if not ((updated > 0) & (updated < 100)).all():
                bad = ids[~((updated > 0) & (updated < 100))].tolist()
                raise ValueError(f"Out-of-range values at increment {step}, iteration {iteration}: {bad}")
            ratios = updated / values
            values = updated
            max_change = float(np.max(np.abs(ratios - 1)) * 100)
            if max_change < tolerance:
                break
        history.append(values.copy())
        diagnostics.append((step, iteration, max_change < tolerance, max_change))

    trajectory = pd.DataFrame({
        "increment": np.repeat(np.arange(increments + 1), len(ids)),
        "node_id": np.tile(ids, increments + 1),
        "value": np.concatenate(history),
    })
    return trajectory, pd.DataFrame(
        diagnostics, columns=["increment", "iterations", "converged", "max_change_pct"]
    )


def run_fsdm_directory(directory, *, mode="exponential", fuzzy_weights=None,
                       operating_range=(0.01, 99.99), max_iterations=100,
                       tolerance=0.01, model_directory=None):
    """Load, run, and summarize an FSDM JSON model/scenario directory.

    Returns ``(trajectory, diagnostics, summary)``. The trajectory includes
    both internal solver values and values converted back to the units declared
    in concepts.json. Summary rows are ordered by absolute net change.
    """
    scenario = load_fsdm_directory(
        directory, fuzzy_weights=fuzzy_weights, operating_range=operating_range,
        model_directory=model_directory,
    )
    return run_fsdm_scenario(
        scenario, mode=mode, max_iterations=max_iterations, tolerance=tolerance,
    )


def run_fsdm_scenario(scenario, *, mode="exponential", max_iterations=100,
                      tolerance=0.01):
    """Run a loaded or generated scenario and return the three analysis tables."""
    trajectory, diagnostics = simulate(
        scenario.weights, scenario.baseline, scenario.targets,
        increments=scenario.increments, mode=mode,
        max_iterations=max_iterations, tolerance=tolerance,
    )
    trajectory = trajectory.rename(columns={"value": "scaled_value"})
    metadata_columns = ["node_id", "name", "min_value", "max_value"]
    if "group" in scenario.concepts:
        metadata_columns.insert(2, "group")
    metadata = scenario.concepts.reset_index()[metadata_columns]
    trajectory = trajectory.merge(
        metadata, on="node_id", how="left", validate="many_to_one"
    )
    trajectory["value"] = trajectory.apply(
        lambda row: _rescale(
            row["scaled_value"], scenario.operating_range,
            (row["min_value"], row["max_value"]),
        ),
        axis=1,
    )

    first = trajectory[trajectory["increment"] == 0].set_index("node_id")
    last = trajectory[
        trajectory["increment"] == scenario.increments
    ].set_index("node_id")
    summary_columns = [column for column in ("name", "group") if column in metadata]
    summary = metadata.set_index("node_id")[summary_columns].copy()
    summary["start_value"] = first["value"]
    summary["final_value"] = last["value"]
    summary["net_change"] = summary["final_value"] - summary["start_value"]
    nonzero_baseline = summary["start_value"].where(summary["start_value"].ne(0))
    summary["percent_change"] = summary["net_change"] / nonzero_baseline * 100
    summary["is_target"] = summary.index.isin(scenario.targets)
    summary = (
        summary.assign(abs_net_change=summary["net_change"].abs())
        .sort_values("abs_net_change", ascending=False)
        .drop(columns="abs_net_change")
        .reset_index()
    )
    return trajectory, diagnostics, summary


def run_at_weight(weight, *, model, edge, baseline, targets, increments=10):
    """Run a scenario with one edited edge and return final values by node ID.

    ``edge`` is a (source, target) tuple. Supply model and scenario inputs
    explicitly rather than relying on notebook globals. The original model is
    not mutated. Raises AssertionError if any increment fails to converge.

    Example::

        final_values = fsdm.run_at_weight(
            0.5, model=model, edge=edge, baseline=baseline, targets=targets,
        )
    """
    edited = build_aecm_model(
        model.weights, nodes=model.concepts.reset_index(),
        edge_updates={edge: weight},
    )
    scenario = build_fsdm_scenario(
        edited, baseline, targets=targets, increments=increments,
    )
    _, diagnostics, summary = run_fsdm_scenario(scenario)
    assert diagnostics["converged"].all(), "Not all scenario increments converged."
    return summary.set_index("node_id")["final_value"]


def run_fsdm_monte_carlo(
    scenario, weight_ranges, *, draws=200, seed=None, **solver_options
):
    """Sample independent uniform signed weights and compare matched runs.

    weight_ranges maps (source, target) to (low, high). Returns three
    DataFrames: sampled weights, draw status, and intervention-minus-control
    final values for each concept in converged pairs.
    """
    if isinstance(draws, bool) or not isinstance(draws, int) or draws < 1:
        raise ValueError("draws must be a positive integer.")
    if not weight_ranges:
        raise ValueError("Supply at least one edge weight range.")

    rng = np.random.default_rng(seed)
    samples = {}
    for (source, target), (low, high) in weight_ranges.items():
        if source not in scenario.weights.index or target not in scenario.weights.columns:
            raise ValueError(f"Unknown edge endpoint: {source!r} -> {target!r}")
        if not -1 <= low <= high <= 1:
            raise ValueError(f"Invalid signed weight range for {source!r} -> {target!r}")
        samples[source, target] = rng.uniform(low, high, size=draws)

    sampled_weights = pd.DataFrame([
        {"draw": draw, "source": source, "target": target, "weight": weights[draw]}
        for (source, target), weights in samples.items()
        for draw in range(draws)
    ])
    status = []
    outcomes = []
    for draw in range(draws):
        weights = scenario.weights.copy()
        for (source, target), values in samples.items():
            weights.at[source, target] = values[draw]

        trial = replace(scenario, weights=weights)
        control = replace(trial, targets={})
        try:
            _, trial_diagnostics, trial_summary = run_fsdm_scenario(trial, **solver_options)
            _, control_diagnostics, control_summary = run_fsdm_scenario(control, **solver_options)
        except ValueError as error:
            status.append({"draw": draw, "converged": False, "error": str(error)})
            continue

        converged = bool(
            trial_diagnostics["converged"].all() and control_diagnostics["converged"].all()
        )
        status.append({
            "draw": draw,
            "converged": converged,
            "error": None if converged else "At least one increment did not converge.",
        })
        if converged:
            trial_final = trial_summary.set_index("node_id")["final_value"]
            control_final = control_summary.set_index("node_id")["final_value"]
            changes = (trial_final - control_final).rename("change").reset_index()
            outcomes.append(changes.assign(draw=draw))

    changes = (
        pd.concat(outcomes, ignore_index=True)
        if outcomes else pd.DataFrame(columns=["node_id", "change", "draw"])
    )
    return sampled_weights, pd.DataFrame(status), changes


def run_at_weight(
    weight, *, model, edge, baseline, targets, increments=10
):
    edited = build_aecm_model(
        model.weights,
        nodes=model.concepts.reset_index(),
        edge_updates={edge: weight},
    )

    scenario = build_fsdm_scenario(
        edited,
        baseline,
        targets=targets,
        increments=increments,
    )

    _, diagnostics, summary = run_fsdm_scenario(scenario)

    assert diagnostics["converged"].all(), (
        "Not all scenario increments converged."
    )

    return summary.set_index("node_id")["final_value"]


def _main():
    parser = argparse.ArgumentParser(description="Run an FSDM JSON scenario directory.")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--mode", choices=("linear", "exponential"),
                        default="exponential")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--weight-scale", type=float, default=1.0,
        help="Multiply every canonical fuzzy weight by this value in (0, 1].",
    )
    parser.add_argument("--top", type=int, default=10,
                        help="Number of largest changes to print.")
    args = parser.parse_args()
    if not 0 < args.weight_scale <= 1:
        parser.error("--weight-scale must be in (0, 1].")
    fuzzy_weights = {
        label: value * args.weight_scale
        for label, value in DEFAULT_FUZZY_WEIGHTS.items()
    }
    try:
        trajectory, diagnostics, summary = run_fsdm_directory(
            args.directory, mode=args.mode, fuzzy_weights=fuzzy_weights,
            model_directory=args.model_dir,
        )
    except ValueError as error:
        parser.exit(2, f"FSDM validation/simulation error: {error}\n")
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        trajectory.to_csv(args.output_dir / "trajectory.csv", index=False)
        diagnostics.to_csv(args.output_dir / "diagnostics.csv", index=False)
        summary.to_csv(args.output_dir / "summary.csv", index=False)
    print(summary.head(max(args.top, 0)).to_string(index=False))
    print(
        f"\nConverged increments: {int(diagnostics['converged'].sum())}/"
        f"{len(diagnostics)}"
    )


if __name__ == "__main__":
    _main()


