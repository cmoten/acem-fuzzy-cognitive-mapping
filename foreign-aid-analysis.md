# Foreign economic assistance scenario analysis

This walkthrough reproduces the AECM exercise with `fsdm.py` and `plot_net_change.py`. Run the snippets in order in one IPython session from the project directory. The Excel loader requires `openpyxl`.

## 1. Identify the intervention concept

```python
import pandas as pd
import fsdm

nodes, signs = fsdm.load_aecm("AECM 2.0 Model.xlsx")
print(nodes.loc[nodes["name"].str.contains(
    "foreign economic assistance", case=False, na=False
), ["node_id", "name"]])
anchor = "EconAssistForeign"
```

## 2. Inspect incoming and outgoing relationships

```python
print(signs.loc[anchor].loc[lambda row: row.ne(0)])
print(signs[anchor].loc[lambda col: col.ne(0)])
```

Assistance has positive outgoing links to political corruption and state capture, disaster preparation, economic growth and development, reliance on foreign suppliers, strength of governing institutions, government provision of services, investment in infrastructure, non-government provision of services, and technology transfer. Its outgoing link to humanitarian crisis is negative. Corruption and government services feed back negatively into assistance. Humanitarian crisis feeds back positively.

## 3. Build the incident-link model

```python
model = fsdm.build_aecm_model(
    signs * 0.05, nodes=nodes, anchors=[anchor], selection="incident"
)
print(len(model.concepts), model.weights.ne(0).sum().sum())
```

The model has 11 concepts and 13 directed links. It keeps links that touch the anchor. Every link uses the workbook sign and an illustrative magnitude of 0.05.

## 4. Define the control and increased-aid scenarios

```python
baseline = dict.fromkeys(model.concepts.index, 0.50)
targets = {anchor: 0.60}
control = fsdm.build_fsdm_scenario(model, baseline, increments=10)
increased_aid = fsdm.build_fsdm_scenario(
    model, baseline, targets=targets, increments=10
)
```

The control has no intervention. The aid scenario uses the same normalized baselines and moves assistance toward 0.60. Feedback can move the final value away from the target.

## 5. Run both scenarios and check convergence

```python
control_trajectory, control_diagnostics, control_summary = fsdm.run_fsdm_scenario(control)
aid_trajectory, aid_diagnostics, aid_summary = fsdm.run_fsdm_scenario(increased_aid)
assert control_diagnostics["converged"].all() and aid_diagnostics["converged"].all()
control_final = control_summary.set_index("node_id")["final_value"]
aid_final = aid_summary.set_index("node_id")["final_value"]
```

Both runs converged at all 10 increments. The control remained at baseline. The default per-increment relative change tolerance is 0.01%.

## 6. Compare final values

```python
comparison = pd.DataFrame({"Control": control_final, "Increased aid": aid_final})
comparison["difference"] = comparison["Increased aid"] - comparison["Control"]
comparison = comparison.sort_values("difference", key=lambda x: x.abs(), ascending=False)
print(comparison.to_string(float_format="{:.6f}".format))
```

Assistance ended at 0.599878. Humanitarian crisis changed by −0.005490 and the other nine related concepts changed by +0.005490 at displayed precision.

## 7. Interpret the results

Interpret direction separately from desirability. Growth and services increased, alongside corruption and reliance on foreign suppliers. An overall welfare judgment requires priorities and tradeoffs. The crisis change represents −0.549 percentage points on the normalized scale. Estimating avoided crisis incidents would require a calibrated mapping to observed events.

## 8. Plot net change

```python
from plot_net_change import plot_net_change

values = comparison[["Control", "Increased aid"]] * 100
print(plot_net_change(values, "foreign_aid_net_change.png").resolve())
```

The helper subtracts the first column from the last. Multiplying normalized values by 100 expresses differences in percentage points.

## 9. Test a single safeguard assumption

```python
edge = (anchor, "CorruptGrand")
focus = ["CorruptGrand", "HumanCrisis", "EconGrowDevel"]

def run_at_weight(weight):
    edited = fsdm.build_aecm_model(
        model.weights, nodes=model.concepts.reset_index(),
        edge_updates={edge: weight},
    )
    scenario = fsdm.build_fsdm_scenario(edited, baseline, targets=targets, increments=10)
    _, diagnostics, summary = fsdm.run_fsdm_scenario(scenario)
    assert diagnostics["converged"].all()
    return summary.set_index("node_id")["final_value"]

safeguard_final = run_at_weight(0.02)
print(pd.DataFrame({"Aid": aid_final, "Aid with safeguard": safeguard_final})
      .loc[[*focus, anchor]].round(6))
```

Reducing the aid-to-corruption weight from +0.05 to +0.02 reduced the corruption increase from 0.005490 to 0.002203. Crisis and growth scores matched the aid-only run at six decimals. Aid ended at 0.599903 with the weaker feedback.

## 10. Sweep the corruption weight

```python
sweep = pd.DataFrame({
    weight: (run_at_weight(weight) - control_final).loc[focus]
    for weight in (0.00, 0.01, 0.02, 0.03, 0.04, 0.05)
}).T
print(sweep.to_string(float_format="{:.6f}".format))
```

The corruption change increased from 0 to 0.005490, roughly 0.0011 per 0.01 of weight. The other two outcomes varied by at most 0.000007 across the sweep.

## 11–13. Pilot, package, and reproduce the Monte Carlo analysis

The pilot sampled one weight uniformly across [0, 0.05] with 200 draws and seed 42. It was then packaged as `run_fsdm_monte_carlo` and reproduced with the same settings. Reload `fsdm` if working in an IPython session that started before the function was added.

```python
def percentiles(frame, column):
    return (frame.groupby("node_id")[column].quantile([0.05, 0.50, 0.95])
            .unstack().reindex(focus))

sampled, status, changes = fsdm.run_fsdm_monte_carlo(
    increased_aid, {edge: (0.0, 0.05)}, draws=200, seed=42
)
print(status["converged"].sum(), len(status))
print(percentiles(changes, "change").round(6))
```

All 200 draws converged. The corruption change had 5th, median, and 95th percentiles of 0.000351, 0.002637, and 0.005141. Each draw uses its own matched no-intervention control.

## 14. Vary three links together

```python
ranges = {
    edge: (0.0, 0.05),
    (anchor, "HumanCrisis"): (-0.075, -0.025),
    (anchor, "EconGrowDevel"): (0.025, 0.075),
}
sampled_three, status_three, changes_three = fsdm.run_fsdm_monte_carlo(
    increased_aid, ranges, draws=200, seed=42
)
print(percentiles(changes_three, "change").round(6))
```

All 200 draws converged. The independent uniform ranges preserve the specified link signs.

| Concept | 5th percentile | Median | 95th percentile |
|---|---:|---:|---:|
| Corruption and state capture | 0.000351 | 0.002637 | 0.005141 |
| Humanitarian crisis | −0.007856 | −0.005461 | −0.003106 |
| Economic growth | 0.002998 | 0.005516 | 0.007893 |

## 15. Compare paired safeguard draws

```python
safeguard_ranges = dict(ranges)
safeguard_ranges[edge] = (0.0, 0.02)
sampled_safe, status_safe, changes_safe = fsdm.run_fsdm_monte_carlo(
    increased_aid, safeguard_ranges, draws=200, seed=42
)
paired = changes_three.merge(
    changes_safe, on=["draw", "node_id"], suffixes=("_aid", "_safe"),
    validate="one_to_one",
)
paired["effect_pp"] = 100 * (paired["change_safe"] - paired["change_aid"])
print(paired["draw"].nunique())
print(percentiles(paired, "effect_pp").round(6))
```

This implementation pairs draws by using the same seed, draw count, and edge order. The aid-to-corruption weight becomes 40% of its original sampled value, with the other weights matched. All 200 pairs converged. The modeled corruption reduction was 0.158 percentage points at the median, with a middle 90% range of 0.021 to 0.308 points. The corresponding crisis and growth percentile ranges stayed within 0.001 points of zero.

## Translate the assumption into a planning question

The modeled safeguard was a 60% reduction in one relationship weight. A planner could evaluate candidate measures such as independent disbursement audits, public contract disclosure, or competitive procurement. Record the proposed mechanism, the evidence behind its plausible effect range, and indicators to monitor, such as the share of awards made without competition. Use aid with safeguards versus aid alone to assess incremental mitigation, and aid with safeguards versus the no-increase control to assess remaining modeled risk. The reported percentiles reflect specified model inputs and sampling assumptions.
