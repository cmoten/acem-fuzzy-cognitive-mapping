"""Plot the change from the first to the last column of a values matrix."""

from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure


def plot_net_change(values, output_path="net_change.png") -> Path:
    """Save a PNG of last-minus-first values for each row and return its path.

    Accepts a numeric 2-D array, nested list, or pandas DataFrame with at
    least one row and two columns. DataFrames provide row and period labels.
    """
    matrix = np.asarray(values, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[1] < 2:
        raise ValueError("Expected a matrix with at least one row and two columns.")
    if not np.isfinite(matrix).all():
        raise ValueError("Matrix values must be finite.")

    row_count, column_count = matrix.shape
    if isinstance(values, pd.DataFrame):
        labels = [str(label) for label in values.index]
        first, last = values.columns[0], values.columns[-1]
    else:
        labels = [f"Row {i + 1}" for i in range(row_count)]
        first, last = "Column 1", f"Column {column_count}"

    with np.errstate(over="ignore"):
        differences = matrix[:, -1] - matrix[:, 0]
    if not np.isfinite(differences).all():
        raise ValueError("The first-to-last differences must be finite.")

    output_path = Path(output_path)
    if output_path.suffix.lower() != ".png":
        raise ValueError("The output path must end in .png.")

    fig = Figure(figsize=(max(7, row_count * 0.65), 4.5), layout="constrained")
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    positions = np.arange(row_count)
    colors = ["#2a78d6" if change >= 0 else "#eb6834" for change in differences]
    bars = ax.bar(positions, differences, color=colors, width=0.5)
    dark = "#3d3c39"
    ax.axhline(0, color=dark, linewidth=1)
    span = np.max(np.abs(differences))
    margin = span * 0.25 if span else 1
    ax.set_ylim(min(0, differences.min()) - margin, max(0, differences.max()) + margin)

    for bar, change in zip(bars, differences):
        outside = change == 0 or abs(change) < span * 0.18
        padding = 4 if outside else -4
        offset = padding if change >= 0 else -padding
        ax.annotate(
            f"{change:+.1f}",
            xy=(bar.get_x() + bar.get_width() / 2, change),
            xytext=(0, offset),
            textcoords="offset points",
            ha="center",
            va="bottom" if offset > 0 else "top",
            color=dark if outside else "white",
            fontweight="bold",
        )

    ax.set_xticks(positions, labels, rotation=30 if row_count > 8 else 0)
    ax.set_title(f"Net Change ({first} to {last})")
    ax.set_ylabel("Difference (End - Start)")
    ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(output_path, format="png", dpi=150)
    return output_path


if __name__ == "__main__":
    example = pd.DataFrame(
        np.random.RandomState(42).rand(4, 4),
        index=["Concept A", "Concept B", "Concept C", "Concept D"],
        columns=["Q1", "Q2", "Q3", "Q4"],
    )
    print(plot_net_change(example))
