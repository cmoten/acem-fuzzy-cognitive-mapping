"""Notebook-friendly plotting of paired FSDM final-value comparisons."""
from io import BytesIO

import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure


def plot_net_changes(
    comparison, *, columns=None, scale=100, show=True, save_path=None,
    figsize=None, dpi=150,
):
    """Plot the second scenario's final value minus the first scenario's.

    Parameters
    ----------
    comparison : pandas.DataFrame
        One row per node, indexed by node ID or display label. Row order is
        preserved, so sort or slice before calling to choose the plotted nodes.
        A precomputed ``difference`` column is ignored; differences are computed
        from the two selected scenario columns.
    columns : pair of column names, optional
        Baseline and intervention columns, in that order. By default use the
        two columns other than ``difference`` (e.g. Control and Increased aid).
    scale : positive float, default 100
        Multiplier applied before subtracting. For final values normalized to
        0–1, 100 gives percentage-point differences. Use 1 for original units.
    show : bool, default True
        Display a PNG inline through IPython. Set False for scripts or tests.
    save_path : path-like, optional
        Also save the figure locally; the extension selects the format
        (e.g. PNG, SVG, or PDF). Parent directories must already exist.
    figsize : (width, height), optional
        Figure dimensions in inches. Default width grows with the node count.
    dpi : positive number, default 150
        Resolution used for the inline PNG and saved raster images.

    Returns
    -------
    (matplotlib.figure.Figure, matplotlib.axes.Axes)
        Figure and axes for further customization or saving. With show=False,
        nothing is displayed automatically.

    Examples
    --------
    >>> fig, ax = plot_net_changes(comparison)
    >>> fig, ax = plot_net_changes(comparison.head(15), save_path="net_changes.png")
    >>> fig, ax = plot_net_changes(comparison, scale=1, show=False)
    """
    if not isinstance(comparison, pd.DataFrame):
        raise TypeError("comparison must be a pandas DataFrame.")
    if comparison.empty:
        raise ValueError("comparison must contain at least one row.")
    if not comparison.columns.is_unique:
        raise ValueError("comparison must have unique column names.")
    if columns is None:
        columns = [column for column in comparison.columns if column != "difference"]
    if isinstance(columns, str) or len(columns) != 2 or columns[0] == columns[1]:
        raise ValueError("Select exactly two distinct scenario columns, in baseline/intervention order.")
    if any(column not in comparison.columns for column in columns):
        raise ValueError("Both selected scenario columns must exist in comparison.")
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("scale must be a positive finite number.")
    if not np.isfinite(dpi) or dpi <= 0:
        raise ValueError("dpi must be a positive finite number.")

    try:
        matrix = comparison.loc[:, list(columns)].to_numpy(dtype=float)
    except (TypeError, ValueError) as error:
        raise ValueError("Scenario values must be numeric and finite.") from error
    if not np.isfinite(matrix).all():
        raise ValueError(
            "Scenario values must be numeric and finite; check for missing or unaligned node IDs."
        )
    with np.errstate(over="ignore", invalid="ignore"):
        differences = (matrix[:, 1] - matrix[:, 0]) * scale
    if not np.isfinite(differences).all():
        raise ValueError("Scaled differences must be finite.")

    labels = [str(label) for label in comparison.index]
    row_count = len(labels)
    first, last = columns
    fig = Figure(
        figsize=figsize if figsize is not None else (max(7, row_count * 0.65), 4.5),
        layout="constrained",
    )
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    positions = np.arange(row_count)
    colors = ["#2a78d6" if change >= 0 else "#eb6834" for change in differences]
    bars = ax.bar(positions, differences, color=colors, width=0.5)
    dark = "#3d3c39"
    ax.axhline(0, color=dark, linewidth=1)
    span = np.max(np.abs(differences))
    margin = span * 0.25 if span else 1
    ax.set_ylim(min(0, differences.min() - margin), max(0, differences.max() + margin))

    for bar, change in zip(bars, differences):
        outside = change == 0 or abs(change) < span * 0.18
        padding = 4 if outside else -4
        offset = padding if change >= 0 else -padding
        ax.annotate(
            f"{change:+.1f}",
            xy=(bar.get_x() + bar.get_width() / 2, change),
            xytext=(0, offset), textcoords="offset points", ha="center",
            va="bottom" if offset > 0 else "top",
            color=dark if outside else "white", fontweight="bold",
        )
    ax.set_xticks(positions, labels, rotation=30 if row_count > 8 else 0)
    ax.set_title(f"Net change in final values from {first} to {last}")
    ax.set_ylabel(f"Difference ({last} - {first})" + (f" × {scale:g}" if scale != 1 else ""))
    ax.spines[["top", "right"]].set_visible(False)

    if save_path is not None:
        fig.savefig(save_path, dpi=dpi)
    if show:
        from IPython.display import Image, display

        with BytesIO() as buffer:
            fig.savefig(buffer, format="png", dpi=dpi)
            display(Image(data=buffer.getvalue()))
    return fig, ax
