from __future__ import annotations

"""Helpers for generating per-part mass spectrometer reports."""

from pathlib import Path
from typing import List

import pandas as pd

from graph_plotter import plot_channel_data, plot_crosses
from pdf_helpers import draw_test_details, insert_plot_and_logo, draw_table
from report_utils import sanitise_report_filename_component


def generate_mass_spec_reports(
    *,
    cleaned_data: pd.DataFrame,
    part_windows: pd.DataFrame,
    mass_spec_channel: str,
    test_metadata: pd.DataFrame,
    transducer_codes: pd.DataFrame,
    gauge_codes: pd.DataFrame,
    pdf_output_path: Path,
    channel_visibility: pd.DataFrame,
    channel_map: dict[str, str],
    raw_data: pd.DataFrame,
) -> List[Path]:
    """Generate a mass spectrometer report for each part window.

    Parameters
    ----------
    cleaned_data:
        Full cleaned dataset containing the mass spectrometer channel.
    part_windows:
        DataFrame describing start and stop times for each part. The
        DataFrame is expected to have columns named ``Part``, ``Start``
        and ``Stop`` (case insensitive). Any rows with missing or invalid
        times are ignored.
    mass_spec_channel:
        The name of the mass spectrometer channel in ``cleaned_data``.
    test_metadata, transducer_details:
        Metadata required for :func:`draw_test_details`.
    pdf_output_path:
        Directory in which to save the generated PDFs.
    channels_to_record, channel_map, raw_data:
        Passed through to :func:`plot_channel_data` and
        :func:`draw_test_details` for consistency with the main report
        generation routines.

    Returns
    -------
    list[pathlib.Path]
        A list of paths to the generated PDF files.
    """

    if part_windows is None or part_windows.empty:
        return []

    # Normalise column names for easier lookups
    normalised = {
        c.lower(): c for c in part_windows.columns
    }
    part_col = normalised.get("label")
    start_col = normalised.get("start")
    stop_col = normalised.get("stop")

    if not (part_col and start_col and stop_col):
        return []

    generated_paths: List[Path] = []

    for _, row in part_windows.iterrows():
        part = str(row.get(part_col, "")).strip()
        start = pd.to_datetime(row.get(start_col), errors="coerce", dayfirst=True)
        stop = pd.to_datetime(row.get(stop_col), errors="coerce", dayfirst=True)
        if pd.isna(start) or pd.isna(stop) or start >= stop:
            continue

        data_slice = cleaned_data[
            (cleaned_data["Datetime"] >= start)
            & (cleaned_data["Datetime"] <= stop)
        ]
        if data_slice.empty or mass_spec_channel not in data_slice.columns:
            continue

        figure, _, _ = plot_channel_data(
            active_channels=[mass_spec_channel],
            cleaned_data=data_slice,
            test_metadata=test_metadata,
            is_table=True,
            channel_map=channel_map,
        )

        meta = test_metadata.copy()
        meta['Test Name'] = part

        filename_parts = [
            sanitise_report_filename_component(
                meta.get('Test Section Number'),
                default="Part",
            ),
            sanitise_report_filename_component(part, default="Part"),
            sanitise_report_filename_component(
                meta.get('Date Time'),
                default="unknown-time",
            ),
        ]
        filename = "_".join(filename_parts) + ".pdf"
        output_path = pdf_output_path / filename

        mass_spec_max_index = pd.DataFrame({"Part": [part], "Max Value_Index": [data_slice[mass_spec_channel].idxmax()]})

        plot_crosses(
            df=mass_spec_max_index,
            channel=mass_spec_channel,
            data=data_slice,
            ax=figure.axes[0],
        )

        pdf = draw_test_details(
            meta,
            transducer_codes,
            gauge_codes,
            [mass_spec_channel],
            data_slice,
            output_path,
            True,
            raw_data,
        )
        max_val = data_slice[mass_spec_channel].max()
        formatted = f"{max_val:.2e}"

        mass_spec_max = pd.DataFrame({"Part": [part], "Max Value (mbarl/sec)": [formatted],})
        mass_spec_max.loc[-1] = mass_spec_max.columns
        mass_spec_max.index = mass_spec_max.index + 1
        mass_spec_max = mass_spec_max.sort_index()
        mass_spec_max.columns = range(mass_spec_max.shape[1])
        draw_table(pdf_canvas=pdf, dataframe=mass_spec_max)
        insert_plot_and_logo(figure, pdf, True)
        generated_paths.append(output_path)

    return generated_paths
