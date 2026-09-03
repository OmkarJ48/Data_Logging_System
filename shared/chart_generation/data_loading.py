"""Helpers for loading CSV test data."""

from pathlib import Path
import pandas as pd
from channel_mapping import create_channel_name_mapping
import json
import re

from report_utils import coerce_report_datetimes


def get_file_paths(primary_data_path: str, test_details_path: str, output_pdf_path: str):
    """Return standardised file paths used throughout the program."""
    return (
        primary_data_path,
        test_details_path,
        Path(output_pdf_path),
    )


def load_csv_file(file_path: str, **kwargs) -> pd.DataFrame:
    """Wrapper around :func:`pandas.read_csv` with friendly errors."""
    try:
        return pd.read_csv(file_path, **kwargs, dayfirst=True)
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"File not found: {file_path}") from exc
    except pd.errors.EmptyDataError as exc:
        raise ValueError(f"File is empty: {file_path}") from exc
    except Exception as exc:  # pragma: no cover - unexpected read error
        raise Exception(f"Error reading file {file_path}: {exc}") from exc
    
def load_test_information(test_details_path: str):
    """Load all test information from the test details CSV file."""

    root = json.load(open(test_details_path))
    test_metadata = root["metadata"]
    channel_info = pd.DataFrame(root["channel_info"])

    mass_spec_timings = pd.DataFrame(root.get("mass_spec_timings", []))
    holds = pd.DataFrame(root.get("holds", []))
    cycles = pd.DataFrame(root.get("cycles", []))
    calibration = root.get("calibration", {})

    test_section_number = str(test_metadata.get("Test Section Number", "")).strip()
    test_name = str(test_metadata.get("Test Name", "")).strip()
    prefix = f"{test_section_number} "
    if test_section_number and test_name.startswith(prefix):
        test_metadata["Test Name"] = test_name[len(prefix):]

    transducers_codes = channel_info[["channel", "transducer"]].fillna("")
    gauge_codes = channel_info[["channel", "gauge"]].fillna("")
    channel_visibility = channel_info.set_index('channel')[['visible']]

    # Create the channel name mapping
    custom_channel_names = channel_info["channel"].tolist()
    default_to_custom_map = create_channel_name_mapping(custom_channel_names)

    return (
        test_metadata,
        transducers_codes,
        gauge_codes,
        channel_visibility,
        mass_spec_timings,
        holds,
        cycles,
        calibration,
        default_to_custom_map,
        channel_info,
    )

def prepare_primary_data(primary_data_paths: list, channels_to_record: pd.DataFrame):
    """Load one or more primary data CSVs and return a cleaned subset."""

    def sort_key(path_str):
        path_str = str(path_str)
        match = re.search(r'_data_(\d+)\.csv$', path_str)
        if match:
            return (0, int(match.group(1)))
        return (1, path_str)

    # Sort files to ensure chronological order based on _data_X.csv naming
    primary_data_paths = sorted(primary_data_paths, key=sort_key)

    # Load and concatenate all data files
    all_raw_data = []
    for path in primary_data_paths:
        df = load_csv_file(path, header=0)
        all_raw_data.append(df)

    if not all_raw_data:
        raise ValueError("No primary data files provided.")

    raw_data = pd.concat(all_raw_data, ignore_index=True)

    # Identify which channels are actually recorded
    active_channels = channels_to_record[channels_to_record['visible'] == True].index.tolist()
    required_columns = ["Datetime"] + active_channels

    # Extract only the required columns
    data_subset = raw_data[required_columns].copy()

    # Support both the legacy dd/mm/yyyy format and the newer ISO timestamps
    # emitted by the DAQ pipeline.
    data_subset["Datetime"] = coerce_report_datetimes(data_subset["Datetime"])

    valid_datetime_mask = data_subset["Datetime"].notna()
    if not valid_datetime_mask.any():
        raise ValueError(
            "Could not parse any Datetime values from the primary data files."
        )
    if not valid_datetime_mask.all():
        data_subset = data_subset.loc[valid_datetime_mask].copy()
        raw_data = raw_data.loc[valid_datetime_mask].copy()

    # Drop duplicate timestamps so downstream consumers always see unique
    # Datetime values (while preserving the first occurrence).
    dedupe_mask = ~data_subset["Datetime"].duplicated(keep="first")
    if not dedupe_mask.all():
        data_subset = data_subset.loc[dedupe_mask].copy()
        raw_data = raw_data.loc[dedupe_mask].copy()

    # Ensure 'Datetime' is the first column
    columns_ordered = ["Datetime"] + [col for col in data_subset.columns if col != "Datetime"]
    data_subset = data_subset[columns_ordered]

    return data_subset, active_channels, raw_data
