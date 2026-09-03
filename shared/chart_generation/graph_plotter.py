"""Plotting utilities for R&D test reports."""

import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import MultipleLocator

from plotter_info import (
    CHANNEL_COLOUR_MAP,
    CHANNEL_LINESTYLE_MAP,
    CHANNEL_UNITS_MAP,
    CHANNEL_AXIS_NAMES_MAP,
    AXIS_COLOUR_MAP,
    AXIS_LOCATIONS,
    AXIS_PRIORITY,
)
from report_utils import coerce_report_datetimes

def plot_crosses(df, channel, data, ax, label_positions=None):
    if df is not None:
        label_positions = label_positions or {}

        # Ensure the annotated axis is drawn above the others
        ax.set_zorder(3)
        ax.patch.set_visible(False)

        # Predefined annotation positions for all key points
        predefined_positions = {
            "Max Value": {"x_offset": 0, "y_offset": 10},
            "A1": {"x_offset": -14.14, "y_offset": 0},
            "A2": {"x_offset": -10, "y_offset": 10},
            "A3": {"x_offset": 10,  "y_offset": 10},
            "A4": {"x_offset": 0, "y_offset": -14.14},
            "A5": {"x_offset": -10, "y_offset": 10},
            "R1": {"x_offset": 10,  "y_offset": 10},
            "R2": {"x_offset": -10, "y_offset": -10},
            "R3": {"x_offset": 10,  "y_offset": 10},
            "R4": {"x_offset": -10, "y_offset": -10},
            "BTO": {"x_offset": -10,  "y_offset": -10},
            "RPO": {"x_offset": 0, "y_offset": -14.14},
            "RNO": {"x_offset": 0, "y_offset": 14.14},
            "JTO": {"x_offset": 0,  "y_offset": -14.14},
            "BTC": {"x_offset": -10, "y_offset": 10},
            "RPC": {"x_offset": -10, "y_offset": 10},
            "JTC": {"x_offset": 0,  "y_offset": 14.14},
            "RNC": {"x_offset": 0, "y_offset": -14.14},
            "SOS": {"x_offset": 10, "y_offset": 10},
            "SOH": {"x_offset": 10, "y_offset": 10},
            "EOH": {"x_offset": 10, "y_offset": 10},
            "Breakout": {"x_offset": 10, "y_offset": 10},
        }

        idx_cols = [c for c in df.columns if c.endswith("_Index")]

        for col in idx_cols:
            label = col.removesuffix("_Index")
            idxs = df[col].dropna().astype(int)

            for idx in idxs:
                t = data["Datetime"].loc[idx]
                y = data[channel].loc[idx]

                # Use predefined first, then user-defined overrides if given
                pos = label_positions.get(label, predefined_positions.get(label, {}))
                offset_x = pos.get("x_offset", 0)
                offset_y = pos.get("y_offset", 5)

                ax.plot(
                    t, y,
                    marker='x',
                    linestyle='none',
                    markersize=8,
                    color='black',
                )
                ax.annotate(
                    label,
                    xy=(t, y),
                    xytext=(offset_x, offset_y),
                    textcoords="offset points",
                    ha="center",  # must be 'center', not 'centre'
                    va="center",
                    fontsize=10,
                )

def axis_location(active_channels, custom_to_default_map):
    """Map each active channel to an axis position."""
    axis_types = [CHANNEL_AXIS_NAMES_MAP.get(custom_to_default_map.get(ch)) for ch in active_channels]
    axis_types_set = set(axis_types)
    axis_types_present = [a for a in AXIS_PRIORITY if a in axis_types_set]
    return {
        axis_type: loc
        for axis_type, loc in zip(axis_types_present, AXIS_LOCATIONS)
    }

def _prepare_plot_data(cleaned_data):
    """Prepare data for plotting by converting Datetime column."""
    data_for_plot = cleaned_data.copy()
    data_for_plot["Datetime"] = coerce_report_datetimes(data_for_plot["Datetime"])
    return data_for_plot

def _setup_axes(is_table, axis_map):
    """Set up the main figure and twin axes."""
    figsize = (11.96, 8.49) if is_table else (11.96, 9.37)
    fig, ax_main = plt.subplots(figsize=figsize)
    axes = {'left': ax_main}
    for axis_name in set(axis_map.values()):
        if axis_name == "left":
            continue
        ax = ax_main.twinx()
        if axis_name.startswith("right_"):
            idx = int(axis_name.split("_")[1])
            ax.spines["right"].set_position(("axes", 1 + 0.1 * (idx - 1)))
        axes[axis_name] = ax
    return fig, axes, ax_main

def _plot_channels(active_channels, data_for_plot, axis_map, axes, custom_to_default_map):
    """Plot each active channel on its corresponding axis."""

    plotted_lines, plotted_labels, color_map, axis_label_map = [], [], {}, {}
    for ch in active_channels:
        default_ch = custom_to_default_map.get(ch)
        axis_type = axis_map.get(CHANNEL_AXIS_NAMES_MAP.get(default_ch))
        if not axis_type:
            continue
        ax = axes[axis_type]
        color = CHANNEL_COLOUR_MAP.get(default_ch, 'black')
        linestyle = CHANNEL_LINESTYLE_MAP.get(default_ch, "-")
        unit = CHANNEL_UNITS_MAP.get(default_ch, '')
        label = f"{ch} ({unit})" if unit else ch
        line, = ax.plot(
            data_for_plot['Datetime'], 
            data_for_plot[ch], 
            label=label, 
            color=color, 
            linestyle=linestyle,
            linewidth=1
        )
        color_map[axis_type] = color
        plotted_lines.append(line)
        plotted_labels.append(label)
        if axis_type not in axis_label_map:
            axis_name = CHANNEL_AXIS_NAMES_MAP.get(default_ch, '')
            axis_unit = CHANNEL_UNITS_MAP.get(default_ch, '')
            axis_label_map[axis_type] = f"{axis_name} ({axis_unit})".strip() if axis_unit else axis_name
    return plotted_lines, plotted_labels, color_map, axis_label_map

def _style_axes(
    axes,
    axis_label_map,
    color_map,
    cleaned_data,
    test_metadata,
    *,
    lock_temperature_axis=True,
):
    """Apply styling to all axes.

    Parameters
    ----------
    lock_temperature_axis:
        When ``True`` the temperature axis uses the standard -60 to 260 °C
        range. When ``False`` the axis limits are derived from the plotted
        data.
    """
    temperature_channels = [ch for ch in cleaned_data.columns if 'temperature' in str(ch).lower()]
    max_value = cleaned_data[temperature_channels].max()
    min_value = cleaned_data[temperature_channels].min()
    max_value = max_value.max()
    min_value = min_value.min()
    if max_value > 260 or min_value < -60:
            lock_temperature_axis = False
    for axis_type, ax in axes.items():
        axis_label = axis_label_map.get(axis_type, '')
        axis_name = axis_label.split('(')[0].strip() if axis_label else ''
        axis_color = AXIS_COLOUR_MAP.get(axis_name, color_map.get(axis_type, 'black'))
        if axis_label:
            ax.set_ylabel(axis_label, color=axis_color)
            ax.tick_params(axis='y', colors=axis_color)
        ax.margins(x=0)
        ax.spines['top'].set_visible(False)
        if axis_type == 'left':
            ax.spines['left'].set_edgecolor(axis_color)
            ax.spines['left'].set_linewidth(0.5)
            ax.spines['right'].set_visible(False)
        else:
            ax.spines['right'].set_edgecolor(axis_color)
            ax.spines['right'].set_linewidth(0.5)
            ax.spines['left'].set_visible(False)
        if 'temperature' in axis_name.lower():
            if lock_temperature_axis:
                ax.set_ylim(-60, 260)
                ax.yaxis.set_major_locator(MultipleLocator(10))
            else:
                ax.relim()
                ax.autoscale_view()
        if 'pressure' in axis_name.lower():
            if test_metadata["Test Pressure"] == '0' and test_metadata["Program Name"] != 'Calibration':
                ax.set_ylim(-1, 1000)
            else:
                _, y_max = ax.get_ylim()
                ax.set_ylim(0, y_max)
        if 'actuator' in axis_name.lower():
            _, y_max = ax.get_ylim()
            ax.set_ylim(0, y_max)
        if 'torque' in axis_name.lower():
            ax.set_ylim(-250, 250)
        if 'valve state' in axis_name.lower():
            ax.set_ylim(-0.05, 1.05)
            ax.set_yticks([0, 1])
            ax.yaxis.set_minor_locator(matplotlib.ticker.NullLocator())
        ax.spines['bottom'].set_edgecolor('black')
        ax.spines['bottom'].set_linewidth(0.5)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m/%Y\n%H:%M:%S'))
        x_values = coerce_report_datetimes(cleaned_data['Datetime'])
        x_min, x_max = x_values.min(), x_values.max()
        if pd.notna(x_min) and pd.notna(x_max):
            if x_min == x_max:
                ax.set_xticks([x_min])
            else:
                ax.set_xticks(pd.date_range(start=x_min, end=x_max, periods=10))

def _configure_legend(fig, plotted_lines, plotted_labels):
    """Configure and position the legend."""
    if not plotted_lines:
        return 0.05
    max_cols = 5
    n_channels = len(plotted_labels)
    ncol = min(n_channels, max_cols)
    nrows = (n_channels + max_cols - 1) // max_cols
    legend_y = 0.02 + 0.03 * (nrows - 1)
    bottom_margin = 0.05 * nrows
    fig.legend(
        plotted_lines, plotted_labels, loc='lower center', ncol=ncol,
        frameon=False, bbox_to_anchor=(0.5, legend_y)
    )
    return bottom_margin

def plot_channel_data(
    active_channels,
    cleaned_data,
    test_metadata,
    is_table,
    channel_map,
    *,
    lock_temperature_axis=True,
):
    """Return matplotlib figure and axes for the given channel data.

    Parameters
    ----------
    lock_temperature_axis:
        When ``True`` the temperature axis is locked to the standard range
        used in the existing reports. When ``False`` the axis range is
        derived from the plotted data.
    """
    custom_to_default_map = {v: k for k, v in channel_map.items()}
    data_for_plot = _prepare_plot_data(cleaned_data)
    axis_map = axis_location(active_channels, custom_to_default_map)
    fig, axes, ax_main = _setup_axes(is_table, axis_map)

    plotted_lines, plotted_labels, color_map, axis_label_map = _plot_channels(
        active_channels, data_for_plot, axis_map, axes, custom_to_default_map
    )

    _style_axes(
        axes,
        axis_label_map,
        color_map,
        cleaned_data,
        test_metadata,
        lock_temperature_axis=lock_temperature_axis,
    )

    bottom_margin = _configure_legend(fig, plotted_lines, plotted_labels)

    for name, ax in axes.items():
        if ax is not ax_main:
            ax.set_zorder(1)
            ax.patch.set_visible(False)
    ax_main.set_zorder(2)
    ax_main.patch.set_visible(False)

    plt.tight_layout(rect=[0, bottom_margin, 1, 1])

    return fig, axes, axis_map
