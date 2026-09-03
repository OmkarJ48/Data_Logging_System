import pandas as pd
import numpy as np
from typing import Any, Dict, List, Optional, Tuple
from scipy.signal import find_peaks
import re
import warnings

from report_utils import coerce_report_datetime

def find_cycle_breakpoints(raw_data, channels_to_record, channel_map: dict[str, str]):
    cycle_count_data = raw_data[channel_map["Cycle Count"]]
    total_cycle_count = int(cycle_count_data.max())

    cycle_ranges = []

    for i in range(1, total_cycle_count + 1):
        matching = cycle_count_data[cycle_count_data == i]
        if matching.empty:
            continue

        start_idx = matching.index[0]
        end_idx = matching.index[-1]
        n_points = len(matching)

        if channels_to_record.loc[channel_map["Torque"]].all():
            one_quarter_idx = matching.index[n_points // 4]
            middle_idx = matching.index[n_points // 2]
            three_quarter_idx = matching.index[(3 * n_points) // 4]
        elif channels_to_record.loc[channel_map["Actuator"]].all():
            actuator_series = raw_data.loc[matching.index, channel_map["Actuator"]]
            if actuator_series.empty:
                one_quarter_idx = matching.index[n_points // 4]
                middle_idx = matching.index[n_points // 2]
                three_quarter_idx = matching.index[(3 * n_points) // 4]
            else:
                middle_idx = actuator_series.idxmax()
                middle_pos = list(matching.index).index(middle_idx)
                start_pos = 0
                end_pos = n_points - 1
                one_quarter_idx = matching.index[(start_pos + middle_pos) // 2]
                three_quarter_idx = matching.index[(middle_pos + end_pos) // 2]
        else:
            one_quarter_idx = matching.index[n_points // 4]
            middle_idx = matching.index[n_points // 2]
            three_quarter_idx = matching.index[(3 * n_points) // 4]

        cycle_ranges.append((
            i,
            start_idx,
            one_quarter_idx,
            middle_idx,
            three_quarter_idx,
            end_idx
        ))

    df_ranges = pd.DataFrame(cycle_ranges, columns=[
        "Cycle",
        "Start Index",
        "One-Quarter Index",
        "Middle Index",
        "Three-Quarter Index",
        "End Index",
    ])
    return df_ranges, total_cycle_count

def signed_distances_to_baseline(y: pd.Series) -> np.ndarray:
    if len(y) < 2: 
        return np.zeros(len(y))
    else:
        x = np.arange(len(y))
        m = (y.iloc[-1] - y.iloc[0]) / (len(y) - 1)
        b = y.iloc[0]
        # distance of each (x, y) to line y = m x + b
        return ((m * x - y + b) / np.hypot(m, -1))

def find_furthest_below_point(data):
    """Return (row, pos) of the point furthest below the baseline (max signed distance)."""
    if data.empty:
        raise ValueError("Cannot find the furthest-below point in an empty series.")
    sd = signed_distances_to_baseline(data)
    pos = int(np.argmax(sd))
    return data.iloc[pos], pos

def find_furthest_above_point(data):
    """Return (row, pos) of the point furthest above the baseline (min signed distance)."""
    if data.empty:
        raise ValueError("Cannot find the furthest-above point in an empty series.")
    sd = signed_distances_to_baseline(data)
    pos = int(np.argmin(sd))
    return data.iloc[pos], pos

EXTREMUM_LOOKAHEAD_STEPS = 2
THRESHOLD_VALLEY_MAX_GAP = 2
BTO_BREAKOUT_THRESHOLD_DELTA = 10
BTO_EXTENDED_BREAKOUT_PROMINENCE = 10
BTC_BREAKOUT_THRESHOLD_DELTA = 10
BTC_BREAKOUT_DROP_THRESHOLD = 10
BTC_BREAKOUT_LATER_MARGIN = 5
BTC_WORKING_PRESSURE_PROMINENCE = 10
BTC_WORKING_PRESSURE_CLUSTER_FRACTION = 0.05
BTC_WORKING_PRESSURE_CLUSTER_MIN_GAP = 100
RNC_BREAKOUT_DROP_THRESHOLD = 8
RNC_PRE_DROP_LOOKBACK = 50
HYDRAULIC_RAMP_START_FRACTION = 0.05
HYDRAULIC_RAMP_END_FRACTION = 0.90


def _is_better_extremum(candidate: float, current: float, mode: str) -> bool:
    if mode == "peak":
        return candidate >= current
    return candidate <= current


def _find_next_extremum_step(
    y: pd.Series,
    start_pos: int,
    direction: int,
    mode: str,
    lookahead_steps: int = EXTREMUM_LOOKAHEAD_STEPS,
) -> Optional[int]:
    """
    Return the next improving position within a small lookahead window.

    This lets the walker skip over a short-lived wobble when a stronger peak or
    valley appears immediately after it.
    """
    n = len(y)
    best_pos = None

    for step in range(1, lookahead_steps + 1):
        pos = start_pos + (direction * step)
        if pos < 0 or pos >= n:
            break

        baseline_pos = start_pos if best_pos is None else best_pos
        if _is_better_extremum(y.iloc[pos], y.iloc[baseline_pos], mode):
            best_pos = pos

    return best_pos

def _walk_to_extremum(y: pd.Series, start_pos: int, direction: int, mode: str = "peak") -> int:
    """
    Walk in one direction (-1 = left, +1 = right) to a nearby local extremum.

    The walk prefers monotonic improvement, but will look a couple of samples
    ahead before stopping so a one-sample reversal does not prematurely end the
    search.

    - mode="peak"  : walk uphill/flat until no higher point is visible
    - mode="valley": walk downhill/flat until no lower point is visible

    Returns the position (0..len-1) of the extremum reached in that direction.
    """

    i = start_pos

    while True:
        next_pos = _find_next_extremum_step(y, i, direction, mode)
        if next_pos is None:
            return i
        i = next_pos


def find_extremum_around_index(y: pd.Series, seed_index, mode: str = "peak") -> Tuple[float, Any]:
    """
    From a seed index (label), find the best local extremum reachable by walking
    left and right as long as values keep improving (or stay flat).

    mode="peak"   -> returns highest reachable local peak (rounded_value, index_label)
    mode="valley" -> returns lowest reachable local valley (rounded_value, index_label)
    """
    seed_pos = y.index.get_loc(seed_index)                 # convert label -> integer position

    left_pos  = _walk_to_extremum(y, seed_pos, direction=-1, mode=mode)
    right_pos = _walk_to_extremum(y, seed_pos, direction=+1, mode=mode)

    # choose whichever extremum is "better"
    if mode == "peak":
        best_pos = right_pos if y.iloc[right_pos] > y.iloc[left_pos] else left_pos
        best_val = round(float(y.iloc[best_pos]), 0)
    else:
        best_pos = right_pos if y.iloc[right_pos] < y.iloc[left_pos] else left_pos
        best_val = round(float(y.iloc[best_pos]), 2)

    best_idx = y.index[best_pos]                           # integer position -> label
    return best_val, best_idx


# --- Backwards-compatible wrappers in the same style as your originals ---

def find_peak_around_index(y: pd.Series, seed_index) -> Tuple[float, Any]:
    return find_extremum_around_index(y, seed_index, mode="peak")

def find_valley_around_index(y: pd.Series, seed_index) -> Tuple[float, Any]:
    return find_extremum_around_index(y, seed_index, mode="valley")


def find_last_interior_extremum(y: pd.Series, mode: str = "peak") -> Tuple[float, Any]:
    """
    Find the last non-edge local extremum in the series.

    This is useful when the right edge of a slice is defined by another signal,
    because the edge sample itself can be biased by that boundary and should not
    automatically win as the selected point.
    """
    if len(y) < 3:
        edge_idx = y.index[-1]
        return find_extremum_around_index(y, edge_idx, mode=mode)

    for pos in range(len(y) - 2, 0, -1):
        prev_val = y.iloc[pos - 1]
        cur_val = y.iloc[pos]
        next_val = y.iloc[pos + 1]

        if mode == "peak":
            is_extremum = cur_val >= prev_val and cur_val >= next_val
            rounded_value = round(float(cur_val), 0)
        else:
            is_extremum = cur_val <= prev_val and cur_val <= next_val
            rounded_value = round(float(cur_val), 2)

        if is_extremum:
            return rounded_value, y.index[pos]

    edge_idx = y.index[-1]
    return find_extremum_around_index(y, edge_idx, mode=mode)


def find_bto_breakout_valley(
    torque_data: pd.Series,
    one_quarter_idx,
    jto_idx=None,
    *,
    prefer_prominent: bool = False,
) -> Tuple[float, Any]:
    opening_slice = torque_data.loc[:one_quarter_idx]
    if opening_slice.empty:
        opening_slice = torque_data

    threshold = float(opening_slice.iloc[0]) - BTO_BREAKOUT_THRESHOLD_DELTA
    if (opening_slice < threshold).any():
        if prefer_prominent:
            prominent_valley = find_first_threshold_prominent_valley(
                opening_slice,
                threshold,
                prominence=BTO_EXTENDED_BREAKOUT_PROMINENCE,
            )
            if prominent_valley is not None:
                return prominent_valley

        return find_first_contiguous_threshold_valley(opening_slice, threshold)

    if jto_idx is None:
        jto_idx = torque_data.idxmin()

    if jto_idx in torque_data.index:
        extended_slice = torque_data.loc[:jto_idx].iloc[:-1]
    else:
        extended_slice = torque_data

    if extended_slice.empty or not (extended_slice < threshold).any():
        extended_slice = opening_slice

    prominent_valley = find_first_threshold_prominent_valley(
        extended_slice,
        threshold,
        prominence=BTO_EXTENDED_BREAKOUT_PROMINENCE,
    )
    if prominent_valley is not None:
        return prominent_valley

    return find_first_contiguous_threshold_valley(extended_slice, threshold)


def find_first_threshold_prominent_valley(
    y: pd.Series,
    threshold: float,
    prominence: float,
) -> Optional[Tuple[float, Any]]:
    below_threshold_positions = np.flatnonzero((y < threshold).to_numpy())
    if len(below_threshold_positions) == 0:
        return None

    candidate_slice = y.iloc[int(below_threshold_positions[0]):]
    valley_positions, _ = find_peaks(
        -candidate_slice.to_numpy(dtype=float),
        prominence=prominence,
    )
    for pos in valley_positions:
        pos = int(pos)
        if float(candidate_slice.iloc[pos]) < threshold:
            abs_idx = candidate_slice.index[pos]
            return round(float(candidate_slice.iloc[pos]), 2), abs_idx

    return None


def find_btc_breakout_peak(
    torque_data: pd.Series,
    middle_idx,
    three_quarter_idx,
    *,
    not_zero_pressure: bool,
    jtc_idx=None,
) -> Tuple[float, Any]:
    tq_slice = torque_data.loc[middle_idx:three_quarter_idx]
    if tq_slice.empty:
        tq_slice = torque_data

    if not_zero_pressure:
        working_pressure_peak = find_working_pressure_btc_peak(torque_data, jtc_idx)
        if working_pressure_peak is not None:
            return working_pressure_peak

    elif jtc_idx is not None and jtc_idx in tq_slice.index:
        # A few zero-pressure traces hit their biggest close-torque spike
        # before the nominal three-quarter split. In that shape, BTC should
        # stay on the breakout rise before JTC rather than collapsing onto
        # the early jacking plateau itself.
        pre_jtc_slice = tq_slice.loc[:jtc_idx].iloc[:-1]
        if not pre_jtc_slice.empty:
            peak_positions, _ = find_peaks(pre_jtc_slice.to_numpy(dtype=float))
            if len(peak_positions) != 0:
                last_peak_pos = int(peak_positions[-1])
                abs_idx = pre_jtc_slice.index[last_peak_pos]
                val = round(float(pre_jtc_slice.iloc[last_peak_pos]), 2)
                return val, abs_idx
            tq_slice = pre_jtc_slice

    if not not_zero_pressure:
        peak_positions, _ = find_peaks(tq_slice.to_numpy(dtype=float))
        threshold = float(tq_slice.iloc[0]) + BTC_BREAKOUT_THRESHOLD_DELTA
        significant_peak_positions = [
            int(pos)
            for pos in peak_positions
            if float(tq_slice.iloc[pos]) >= threshold
        ]

        if significant_peak_positions:
            first_peak_pos = significant_peak_positions[0]
            max_peak_pos = int(np.argmax(tq_slice.to_numpy(dtype=float)))

            if first_peak_pos < max_peak_pos:
                first_peak_val = float(tq_slice.iloc[first_peak_pos])
                max_peak_val = float(tq_slice.iloc[max_peak_pos])
                min_after_first_peak = float(
                    tq_slice.iloc[first_peak_pos:max_peak_pos + 1].min()
                )

                if (
                    (first_peak_val - min_after_first_peak) >= BTC_BREAKOUT_DROP_THRESHOLD
                    and (max_peak_val - first_peak_val) <= BTC_BREAKOUT_LATER_MARGIN
                ):
                    abs_idx = tq_slice.index[first_peak_pos]
                    val = round(first_peak_val, 2)
                    return val, abs_idx

    val = round(tq_slice.max(), 2)
    abs_idx = tq_slice.idxmax()
    return val, abs_idx


def find_working_pressure_btc_peak(
    torque_data: pd.Series,
    jtc_idx=None,
) -> Optional[Tuple[float, Any]]:
    if torque_data.empty:
        return None

    jto_idx = torque_data.idxmin()
    if jtc_idx is None:
        jtc_idx = torque_data.idxmax()

    if jto_idx not in torque_data.index or jtc_idx not in torque_data.index:
        return None

    close_breakout_slice = torque_data.loc[jto_idx:jtc_idx]
    if len(close_breakout_slice) < 4:
        return None

    # Exclude JTC itself; BTC is the close breakout peak before the final
    # jacking spike.
    close_breakout_slice = close_breakout_slice.iloc[:-1]
    if len(close_breakout_slice) < 3:
        return None

    peak_positions, _ = find_peaks(
        close_breakout_slice.to_numpy(dtype=float),
        prominence=BTC_WORKING_PRESSURE_PROMINENCE,
    )
    if len(peak_positions) == 0:
        return None

    peak_cluster = [int(peak_positions[0])]
    max_cluster_gap = max(
        BTC_WORKING_PRESSURE_CLUSTER_MIN_GAP,
        int(len(close_breakout_slice) * BTC_WORKING_PRESSURE_CLUSTER_FRACTION),
    )
    for pos in peak_positions[1:]:
        pos = int(pos)
        if pos - peak_cluster[-1] > max_cluster_gap:
            break
        peak_cluster.append(pos)

    first_peak_pos = max(
        peak_cluster,
        key=lambda pos: float(close_breakout_slice.iloc[pos]),
    )
    left_pos = _walk_to_extremum(
        close_breakout_slice,
        first_peak_pos,
        direction=-1,
        mode="peak",
    )
    right_pos = _walk_to_extremum(
        close_breakout_slice,
        first_peak_pos,
        direction=+1,
        mode="peak",
    )
    best_pos = (
        right_pos
        if close_breakout_slice.iloc[right_pos] > close_breakout_slice.iloc[left_pos]
        else left_pos
    )
    abs_idx = close_breakout_slice.index[best_pos]
    val = round(float(close_breakout_slice.iloc[best_pos]), 2)
    return val, abs_idx

def find_first_contiguous_threshold_valley(
    y: pd.Series,
    threshold: float,
    max_gap: int = THRESHOLD_VALLEY_MAX_GAP,
) -> Tuple[float, Any]:
    """
    Find the lowest point in the first contiguous run of samples below ``threshold``.

    A breakout trace can briefly bounce back above the threshold for a sample or
    two before dropping into the main valley. Allowing a short rebound gap keeps
    the search attached to that first real breakout instead of latching onto a
    shallow pre-dip.
    """
    if y.empty:
        raise ValueError("Cannot find a valley in an empty series.")

    below_threshold = y < threshold
    if not below_threshold.any():
        best_idx = y.idxmin()
        return round(float(y.loc[best_idx]), 2), best_idx

    start_pos = int(np.flatnonzero(below_threshold.to_numpy())[0])
    end_pos = start_pos
    rebound_gap = 0

    for pos in range(start_pos + 1, len(y)):
        if below_threshold.iloc[pos]:
            end_pos = pos
            rebound_gap = 0
            continue

        rebound_gap += 1
        if rebound_gap > max_gap:
            break

    breakout_slice = y.iloc[start_pos:end_pos + 1]
    best_idx = breakout_slice.idxmin()
    return round(float(y.loc[best_idx]), 2), best_idx


def find_hydraulic_opening_elbow(
    actuator_data: pd.Series,
    middle_idx,
    *,
    start_idx=None,
) -> Tuple[float, Any]:
    """
    Find the actuator opening elbow using the same geometric method as A5.

    ``start_idx`` is normally the pressure knee that precedes A5. If it is not
    available, the search starts from the beginning of the actuator cycle slice.
    """
    if actuator_data.empty:
        raise ValueError("Cannot find a hydraulic opening elbow in an empty series.")

    if start_idx is None or start_idx not in actuator_data.index:
        search_slice = actuator_data.loc[:middle_idx]
    else:
        search_slice = actuator_data.loc[start_idx:middle_idx]

    if search_slice.empty:
        search_slice = actuator_data.loc[:middle_idx]
    if search_slice.empty:
        search_slice = actuator_data

    _, idx = find_furthest_below_point(search_slice)
    abs_idx = search_slice.index[idx]
    return round(float(actuator_data.loc[abs_idx]), 0), abs_idx


def find_actuator_ramp_start(
    actuator_data: pd.Series,
    middle_idx,
) -> Any:
    opening_slice = actuator_data.loc[:middle_idx]
    if opening_slice.empty:
        return actuator_data.index[0]

    values = opening_slice.to_numpy(dtype=float)
    baseline_window = max(5, min(20, len(opening_slice) // 10))
    baseline = float(np.median(values[:baseline_window]))
    peak = float(np.max(values))
    rise = peak - baseline
    if rise <= 0:
        return opening_slice.index[0]

    threshold = baseline + (rise * HYDRAULIC_RAMP_START_FRACTION)
    ramp_start_candidates = opening_slice[opening_slice >= threshold]
    if ramp_start_candidates.empty:
        return opening_slice.index[0]

    ramp_start_idx = ramp_start_candidates.index[0]
    ramp_start_pos = opening_slice.index.get_loc(ramp_start_idx)
    if ramp_start_pos > 0:
        return opening_slice.index[ramp_start_pos - 1]
    return ramp_start_idx


def find_actuator_ramp_end(
    actuator_data: pd.Series,
    middle_idx,
) -> Any:
    opening_slice = actuator_data.loc[:middle_idx]
    if opening_slice.empty:
        return middle_idx

    values = opening_slice.to_numpy(dtype=float)
    baseline_window = max(5, min(20, len(opening_slice) // 10))
    baseline = float(np.median(values[:baseline_window]))
    peak = float(np.max(values))
    rise = peak - baseline
    if rise <= 0:
        return middle_idx

    threshold = baseline + (rise * HYDRAULIC_RAMP_END_FRACTION)
    ramp_end_candidates = opening_slice[opening_slice >= threshold]
    if ramp_end_candidates.empty:
        return middle_idx

    return ramp_end_candidates.index[0]


def find_hydraulic_a2_style_breakout(
    actuator_data: pd.Series,
    middle_idx,
    *,
    downstream_data: Optional[pd.Series] = None,
) -> Tuple[float, Any]:
    """
    Find hydraulic breakout using the signature A5 point as the baseline end.

    First find the A5-style actuator point. Then use the cycle start and A5
    point as the baseline and mark the actuator point furthest above it.
    """
    a5_start_idx = None
    if downstream_data is not None and not downstream_data.empty:
        downstream_opening = downstream_data.loc[:middle_idx]
        if not downstream_opening.empty:
            _, a4_pos = find_furthest_above_point(downstream_opening)
            a5_start_idx = downstream_opening.index[a4_pos]

    _, a5_idx = find_hydraulic_opening_elbow(
        actuator_data,
        middle_idx,
        start_idx=a5_start_idx,
    )

    baseline_start_idx = find_actuator_ramp_start(actuator_data, middle_idx)
    ramp_end_idx = find_actuator_ramp_end(actuator_data, middle_idx)
    if baseline_start_idx < a5_idx <= ramp_end_idx:
        baseline_end_idx = a5_idx
    else:
        baseline_end_idx = ramp_end_idx

    baseline_slice = actuator_data.loc[baseline_start_idx:baseline_end_idx]
    if baseline_slice.empty:
        baseline_slice = actuator_data.loc[:a5_idx]
    if baseline_slice.empty:
        baseline_slice = actuator_data.loc[:middle_idx]
    if baseline_slice.empty:
        baseline_slice = actuator_data

    _, actuator_pos = find_furthest_above_point(baseline_slice)
    breakout_idx = baseline_slice.index[actuator_pos]
    return round(float(actuator_data.loc[breakout_idx]), 0), breakout_idx


def trim_rnc_slice_before_breakout_dip(
    y: pd.Series,
    drop_threshold: float = RNC_BREAKOUT_DROP_THRESHOLD,
    lookback_points: int = RNC_PRE_DROP_LOOKBACK,
) -> pd.Series:
    if y.empty:
        return y

    running_max = float("-inf")
    for pos, value in enumerate(y.to_numpy(dtype=float)):
        running_max = max(running_max, value)
        if pos > 0 and (running_max - value) >= drop_threshold:
            window_start = max(0, pos - lookback_points)
            pre_drop = y.iloc[window_start:pos]
            return pre_drop if not pre_drop.empty else y.iloc[:pos]

    return y

def locate_calibration_points(cleaned_data, calibration_info):
    calibration_indices = pd.DataFrame(index=range(2), columns=range(5))
    date_time_index = cleaned_data.set_index('Datetime')

    for i, key_point in enumerate(calibration_info['key_points']):
        start_time = pd.to_datetime(key_point, format="%d/%m/%Y %H:%M:%S.%f", errors="coerce", dayfirst=True)
        end_time = start_time + pd.Timedelta(seconds=10)

        calibration_indices.iloc[0, i] = date_time_index.index.get_indexer([start_time], method="nearest")[0]
        calibration_indices.iloc[1, i] = date_time_index.index.get_indexer([end_time], method="nearest")[0]

    return calibration_indices

def calculate_succesful_calibration(cleaned_data, calibration_indices, calibration_info):
    display_table = pd.DataFrame()

    channel_index = calibration_info['channel_index']

    if channel_index <= 12:
        applied_values = [4000, 8000, 12000, 16000, 20000]
        index_labels = ['Applied (µA)', 'Counts (avg)', 'Converted (µA)', 'Abs Error (µA) - ±3.6 µA']
    elif channel_index <= 15:
        applied_values = [0, 2500, 5000, 7500, 10000]
        index_labels = ['Applied (mV)', 'Counts (avg)', 'Converted (mV)', 'Abs Error (mV) - ±1.0 mV']
    elif channel_index <= 16:
        applied_values = [-10000, -5000, 0, 5000, 10000]
        index_labels = ['Applied (mV)', 'Counts (avg)', 'Converted (mV)', 'Abs Error (mV) - ±1.0 mV']
    elif channel_index <= 23:
        applied_values = [-5.89, 9.28, 24.46, 39.64, 54.81]
        index_labels = ['Applied (mV)', 'Counts (avg)', 'Converted (mV)', 'Abs Error (mV) - ±0.12 mV']
    else:
        applied_values = [0, 0, 0, 0, 0]
        index_labels = ['Applied', 'Counts (avg)', 'Converted', 'Abs Error']

    slope = (applied_values[-1] - applied_values[0]) / calibration_info['max_range']
    intercept = applied_values[0]

    counts_series = pd.Series(dtype=float)
    expected_series = pd.Series(dtype=float)
    abs_error_series = pd.Series(dtype=float)

    for i in range(5):
        start_idx = calibration_indices.iloc[0, i]
        end_idx = calibration_indices.iloc[1, i]

        counts = cleaned_data.loc[start_idx:end_idx, calibration_info['channel_name']].mean()
        converted = (slope * counts) + intercept
        error = applied_values[i] - converted

        counts_series.loc[i+1] = counts
        expected_series.loc[i+1] = applied_values[i]
        abs_error_series.loc[i+1] = abs(error)

        display_table.loc[0, i+1] = applied_values[i]
        display_table.loc[1, i+1] = int(round(counts))
        display_table.loc[2, i+1] = round(converted, 3)
        display_table.loc[3, i+1] = round(abs(error), 2)

    display_table.index = index_labels
    display_table.insert(0, "0", display_table.index)

    return display_table, counts_series, expected_series, abs_error_series

def calculate_calibration_regression(counts: pd.Series, expected_counts: pd.Series) -> pd.Series:
    """Return polynomial coefficients mapping counts to expected counts."""

    labels = ["S3", "S2", "S1", "S0"]
    if counts is None or expected_counts is None:
        return pd.Series([np.nan] * 4, index=labels, dtype=float)

    counts_series = pd.to_numeric(pd.Series(counts), errors="coerce")
    expected_series = pd.to_numeric(pd.Series(expected_counts), errors="coerce")
    mask = ~(counts_series.isna() | expected_series.isna())

    valid_counts = counts_series[mask]
    valid_expected = expected_series[mask]

    if len(valid_counts) < 2:
        return pd.Series([np.nan] * 4, index=labels, dtype=float)

    degree = min(3, len(valid_counts) - 1)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        coefficients = np.polyfit(valid_counts, valid_expected, deg=degree)

    padded = np.full(4, np.nan)
    padded[-(degree + 1):] = coefficients
    return pd.Series(padded, index=labels, dtype=float)

def locate_key_time_rows(cleaned_data, hold_info: pd.Series):
    """Return indices of key time points closest to provided timestamps.
       Always includes all rows, leaving blanks for missing timestamps.
    """
    date_time_index = cleaned_data.set_index('Datetime')

    def parse_time(value):
        if pd.isna(value) or str(value).strip() == "":
            return None
        parsed = coerce_report_datetime(value)
        return None if pd.isna(parsed) else parsed

    # Parse timestamps
    sos_time = parse_time(hold_info.get('start_of_stabilisation'))
    soh_time = parse_time(hold_info.get('start_of_hold'))
    eoh_time = parse_time(hold_info.get('end_of_hold'))

    channel = hold_info['channel']
    pressure_col = f'{channel} (psi)'

    # Prep index table (always show all, blank if missing)
    index_data = {
        'SOS_Index': [None],
        'SOH_Index': [None],
        'EOH_Index': [None]
    }

    # Default blank table rows
    labels = ['Start of Stabilisation', 'Start of Hold', 'End of Hold']
    times   = [sos_time, soh_time, eoh_time]

    display_table_data = {
        '': labels,
        'Datetime': ['' for _ in labels],
        pressure_col: ['' for _ in labels],
        'Body Temperature (°C)': ['' for _ in labels]
    }

    # Populate only where valid
    for i, (label, ts) in enumerate(zip(labels, times)):
        if ts is None or pd.isna(ts):
            continue

        # Find nearest index
        nearest_idx = date_time_index.index.get_indexer([ts], method="nearest")[0]

        # Fill index table
        if label == 'Start of Stabilisation':
            index_data['SOS_Index'][0] = nearest_idx
        elif label == 'Start of Hold':
            index_data['SOH_Index'][0] = nearest_idx
        elif label == 'End of Hold':
            index_data['EOH_Index'][0] = nearest_idx

        # Fill display table
        pressure_val = cleaned_data.loc[nearest_idx, channel]
        temp_val = cleaned_data.loc[nearest_idx, 'Body Temperature']

        display_table_data['Datetime'][i] = ts.strftime("%d/%m/%Y %H:%M:%S")
        display_table_data[pressure_col][i] = int(pressure_val)
        display_table_data['Body Temperature (°C)'][i] = temp_val

    holds_indices = pd.DataFrame(index_data)
    display_table = pd.DataFrame(display_table_data)

    return holds_indices, display_table

def locate_bto_btc_rows(
    raw_data,
    cycles,
    channel_visibility,
    channel_map: dict[str, str],
    *,
    prefer_recorded_values: bool = True,
    test_metadata: Optional[dict] = None,
):
    if prefer_recorded_values:
        recorded_values = _recorded_bto_btc_values(cycles)
        if not recorded_values.empty:
            return recorded_values, None

    if channel_visibility.loc[channel_map["Torque"]].all():
        breakout_values: List[Dict[str, Any]] = []
        breakout_indices: List[Dict[str, Any]] = []
        not_zero_pressure = True
        if test_metadata is not None:
            not_zero_pressure = str(test_metadata.get("Test Pressure", "")).strip() != "0"

        torque_data = raw_data[channel_map["Torque"]]

        indices_ranges, _ = find_cycle_breakpoints(raw_data, channel_visibility, channel_map)

        for cycle, start_idx, one_quarter, middle_idx, three_quarter, end_idx in indices_ranges.itertuples(index=False, name=None):
            cycle_torque = torque_data.loc[start_idx:end_idx]
            jto_idx = cycle_torque.idxmin()
            jtc_idx = cycle_torque.idxmax()

            bto, bto_idx = find_bto_breakout_valley(
                cycle_torque,
                one_quarter,
                jto_idx=jto_idx,
            )
            btc, btc_idx = find_btc_breakout_peak(
                cycle_torque,
                middle_idx,
                three_quarter,
                not_zero_pressure=not_zero_pressure,
                jtc_idx=jtc_idx,
            )
            
            breakout_values.append({
                "Cycle": cycle,
                "BTO (lb·ft)": bto,
                "BTC (lb·ft)": btc,
            })
            breakout_indices.append({
                "Cycle": cycle,
                "BTO_Index": bto_idx,
                "BTC_Index": btc_idx,
            })
        return pd.DataFrame.from_records(breakout_values), pd.DataFrame.from_records(breakout_indices)

    return None, None


def _recorded_bto_btc_values(cycles) -> pd.DataFrame:
    columns = ['Cycle', 'BTO (lb·ft)', 'BTC (lb·ft)']
    if cycles is None or cycles.empty:
        return pd.DataFrame(columns=columns)

    required_columns = {'cycle_index', 'bto', 'btc'}
    if not required_columns.issubset(cycles.columns):
        return pd.DataFrame(columns=columns)

    breakout_values = cycles.loc[:, ['cycle_index', 'bto', 'btc']].copy()
    breakout_values[['bto', 'btc']] = breakout_values[['bto', 'btc']].apply(
        pd.to_numeric,
        errors='coerce',
    )

    measurements = breakout_values.loc[:, ['bto', 'btc']]
    has_complete_measurements = measurements.notna().all(axis=1)
    if not has_complete_measurements.all():
        return pd.DataFrame(columns=columns)

    breakout_values.rename(
        columns={'cycle_index': 'Cycle', 'bto': 'BTO (lb·ft)', 'btc': 'BTC (lb·ft)'},
        inplace=True,
    )
    breakout_values.reset_index(drop=True, inplace=True)
    return breakout_values

def locate_actuator_breakout_rows(
    raw_data,
    channel_visibility,
    channel_map: dict[str, str],
    test_metadata: dict,
):
    if test_metadata["Test Pressure"] == '0':
        return None, None

    if not channel_visibility.loc[channel_map["Actuator"]].all():
        return None, None

    breakout_values: List[Dict[str, Any]] = []
    breakout_indices: List[Dict[str, Any]] = []

    indices_ranges, _ = find_cycle_breakpoints(raw_data, channel_visibility, channel_map)

    for cycle, start_idx, _, middle_idx, _, end_idx in indices_ranges.itertuples(index=False, name=None):
        actuator_data = raw_data.loc[start_idx:end_idx, channel_map["Actuator"]]
        downstream_channel = channel_map.get("Downstream")
        downstream_data = (
            raw_data.loc[start_idx:end_idx, downstream_channel]
            if downstream_channel in raw_data.columns
            else None
        )
        breakout_value, breakout_idx = find_hydraulic_a2_style_breakout(
            actuator_data,
            middle_idx,
            downstream_data=downstream_data,
        )

        breakout_values.append({
            "Cycle": cycle,
            "Breakout (psi)": breakout_value,
        })
        breakout_indices.append({
            "Cycle": cycle,
            "Breakout_Index": breakout_idx,
        })

    return pd.DataFrame.from_records(breakout_values), pd.DataFrame.from_records(breakout_indices)

def locate_signature_key_points(
    channel_visibility: pd.DataFrame,
    raw_data: pd.DataFrame,
    channel_map: dict[str, str],
    test_metadata: dict,
) -> pd.DataFrame:
    
    if test_metadata["Test Pressure"] != '0':
        not_zero_pressure = True
    else:
        not_zero_pressure = False

    """
    Processes raw_data to find signature key points for each cycle.
    Returns a DataFrame with one row per cycle and columns for each key point and its index.
    """
    def find_a1() -> Tuple[Optional[float], Optional[int]]:
        """Finds A1 (Backseat Elbow)."""
        if channel_visibility["visible"].get("Backseat", False) and not_zero_pressure:
            bs_slice = backseat_data.loc[:middle_idx]
            _, idx = find_furthest_below_point(bs_slice)
            abs_idx = bs_slice.index[idx]
            return round(actuator_data.loc[abs_idx], 0), abs_idx
        return None, None

    def find_a2(end_idx: int) -> Tuple[Optional[float], Optional[int]]:
        """Finds A2 (Actuator Elbow before end_idx)."""
        ac_slice = actuator_data.loc[:end_idx]
        _, idx = find_furthest_above_point(ac_slice)
        abs_idx = ac_slice.index[idx]
        return round(actuator_data.loc[abs_idx], 0), abs_idx

    def find_a3() -> Tuple[Optional[float], Optional[int]]:
        """Finds A3 (Downstream Elbow)."""
        if not_zero_pressure:
            ds_slice = downstream_data.loc[:middle_idx]
            _, idx = find_furthest_below_point(ds_slice)
            abs_idx = ds_slice.index[idx]
            peak_val, peak_idx = find_peak_around_index(actuator_data, abs_idx)
            return round(peak_val), peak_idx
        return None, None

    def find_a4() -> Tuple[Optional[float], Optional[int]]:
        """Finds A4 (Downstream Knee)."""
        if not_zero_pressure:
            ds_slice = downstream_data.loc[:middle_idx]
            _, idx = find_furthest_above_point(ds_slice)
            abs_idx = ds_slice.index[idx]
            return round(actuator_data.loc[abs_idx], 0), abs_idx
        return None, None

    def find_a5(start_idx: int) -> Tuple[Optional[float], Optional[int]]:
        """Finds A5 (Actuator Elbow after start_idx)."""
        return find_hydraulic_opening_elbow(
            actuator_data,
            middle_idx,
            start_idx=start_idx,
        )

    def find_r1(end_idx: int) -> Tuple[Optional[float], Optional[int]]:
        """Finds R1 (Actuator Elbow in return stroke)."""
        ac_slice = actuator_data.loc[middle_idx:end_idx]
        _, idx = find_furthest_below_point(ac_slice)
        abs_idx = ac_slice.index[idx]
        return round(actuator_data.loc[abs_idx], 0), abs_idx

    def find_r2() -> Tuple[Optional[float], Optional[int]]:
        """Finds R2 (Downstream Knee in return stroke)."""
        if not_zero_pressure:
            ds_slice = downstream_data.loc[middle_idx:]
            _, idx = find_furthest_above_point(ds_slice)
            abs_idx = ds_slice.index[idx]
            return round(actuator_data.loc[abs_idx], 0), abs_idx
        return None, None

    def find_r3() -> Tuple[Optional[float], Optional[int]]:
        """Finds R3 (Downstream Elbow in return stroke)."""
        if not_zero_pressure:
            ds_slice = downstream_data.loc[middle_idx:]
            _, idx = find_furthest_below_point(ds_slice)
            abs_idx = ds_slice.index[idx]
            return round(actuator_data.loc[abs_idx], 0), abs_idx
        return None, None

    def find_r4(r3_idx: int, r1_idx: int) -> Tuple[Optional[float], Optional[int]]:
        """Finds R4 (Actuator Knee after start_idx)."""
        if r3_idx is None:
            ac_slice = actuator_data.loc[r1_idx:]
            _, end_idx = find_furthest_below_point(ac_slice)
            end_idx = ac_slice.index[end_idx]
            ac_slice = actuator_data.loc[r1_idx:end_idx]
        else:
            ac_slice = actuator_data.loc[r3_idx:]
            _, end_idx = find_furthest_below_point(ac_slice)
            end_idx = ac_slice.index[end_idx]
            ac_slice = actuator_data.loc[r3_idx:end_idx]
        _, idx = find_furthest_above_point(ac_slice)
        abs_idx = ac_slice.index[idx]
        return round(actuator_data.loc[abs_idx], 0), abs_idx

    def find_bto(jto_idx: Optional[int] = None) -> Tuple[float, int]:
        # BTO belongs to the initial opening breakout, not the later JTO dip.
        # Restrict the search to the opening quarter so the marker stays on the
        # first breakout valley. If a long idle section pushes that breakout
        # just after the nominal quarter split, extend only until JTO and use
        # the first threshold-crossing valley.
        return find_bto_breakout_valley(
            torque_data,
            one_quarter_idx,
            jto_idx=jto_idx,
            prefer_prominent=not_zero_pressure,
        )

    def find_rpo() -> Tuple[Optional[float], Optional[int]]:
        if not_zero_pressure:
            ds_slice = downstream_data.loc[:middle_idx]
            _, end_idx = find_furthest_below_point(ds_slice)
            end_idx = ds_slice.index[end_idx]
            tq_slice = torque_data.loc[:end_idx]
            val, abs_idx = find_last_interior_extremum(tq_slice, mode="valley")
            return val, abs_idx
        return None, None

    def find_rno(start_idx, end_idx) -> Tuple[float, int]:
        if not_zero_pressure:
            ds_slice = downstream_data.loc[:middle_idx]
            _, start_idx = find_furthest_above_point(ds_slice)
            start_idx = ds_slice.index[start_idx]
        else:
            tq_slice = torque_data.loc[start_idx:one_quarter_idx]
            # Zero-pressure traces can have a single-sample rebound immediately
            # after BTO. Smooth only the anchor search so that spike does not
            # pull the RNO window back into the breakout recovery tail.
            anchor_slice = tq_slice.rolling(window=5, center=True, min_periods=1).median()
            _, start_idx = find_furthest_above_point(anchor_slice)
            start_idx = anchor_slice.index[start_idx]

        tq_slice = torque_data.loc[one_quarter_idx:end_idx]
        _, end_idx = find_furthest_above_point(tq_slice)
        end_idx = tq_slice.index[end_idx]

        final_slice = torque_data.loc[start_idx:end_idx-1]
        val = round(final_slice.min(), 2)
        abs_idx = final_slice.idxmin()
        return val, abs_idx

    def find_jto() -> Tuple[float, int]:
        val = round(torque_data.min(), 2)
        abs_idx = torque_data.idxmin()
        return val, abs_idx

    def find_btc(jtc_idx: Optional[int] = None) -> Tuple[float, int]:
        return find_btc_breakout_peak(
            torque_data,
            middle_idx,
            three_quarter_idx,
            not_zero_pressure=not_zero_pressure,
            jtc_idx=jtc_idx,
        )

    def find_rnc(
        start_idx: int,
        end_idx: int,
        rpc_idx: Optional[int] = None,
    ) -> Tuple[float, int]:
        tq_slice = torque_data.loc[start_idx:three_quarter_idx]
        if tq_slice.empty:
            post_btc_torque = torque_data.loc[start_idx:]
            seed_pos = min(1, len(post_btc_torque) - 1)
            _, start_idx = find_valley_around_index(
                post_btc_torque,
                post_btc_torque.index[seed_pos],
            )
        else:
            _, start_idx = find_furthest_below_point(tq_slice)
            start_idx = tq_slice.index[start_idx]

        if not_zero_pressure:
            ds_slice = downstream_data.loc[middle_idx:]
            _, end_idx = find_furthest_below_point(ds_slice)
            end_idx = ds_slice.index[end_idx]
            if rpc_idx is not None and end_idx >= rpc_idx:
                end_idx = rpc_idx
        elif end_idx < three_quarter_idx:
            # Some zero-pressure close traces hit their biggest spike before the
            # nominal 75% split. When that happens, the historical
            # three_quarter->JTC search window inverts and would become empty.
            # Anchor the running-close search to the post-three-quarter tail
            # instead so we still return a meaningful plateau marker.
            _, start_idx = find_valley_around_index(torque_data, three_quarter_idx)
            _, end_idx = find_valley_around_index(torque_data, torque_data.index[-1])
        else:
            tq_slice = torque_data.loc[three_quarter_idx:end_idx]
            _, end_idx = find_furthest_below_point(tq_slice)
            end_idx = tq_slice.index[end_idx]

        final_slice = torque_data.loc[start_idx:end_idx]
        if len(final_slice) > 1:
            final_slice = final_slice.iloc[:-1]
        if not_zero_pressure:
            final_slice = trim_rnc_slice_before_breakout_dip(final_slice)
        if final_slice.empty:
            final_slice = torque_data.loc[start_idx:]
        val = round(final_slice.max(), 2)
        abs_idx = final_slice.idxmax()
        return val, abs_idx

    def find_rpc(end_idx: int) -> Tuple[Optional[float], Optional[int]]:
        if not_zero_pressure:
            ds_slice = downstream_data.loc[middle_idx:]
            _, start_idx = find_furthest_below_point(ds_slice)
            start_idx = ds_slice.index[start_idx]

            if start_idx >= end_idx:
                start_idx = three_quarter_idx if three_quarter_idx < end_idx else middle_idx

            tq_slice1 = torque_data.loc[start_idx:end_idx]
            if tq_slice1.empty:
                return None, None
            start_idx = tq_slice1.idxmin()

            tq_slice2 = torque_data.loc[start_idx:end_idx]
            if tq_slice2.empty:
                return None, None

            # Some traces linger on a shallow low-torque floor before the final
            # rise into JTC. Trimming that flat section keeps the elbow search
            # focused on the return-close ramp and avoids selecting the small
            # pre-rise dip as RPC on the last cycle.
            rise_candidates = tq_slice2[tq_slice2 >= (tq_slice2.iloc[0] + 2)]
            if not rise_candidates.empty:
                tq_slice2 = tq_slice2.loc[rise_candidates.index[0]:end_idx]

            _, idx = find_furthest_below_point(tq_slice2)
            abs_idx = tq_slice2.index[idx]
            return round(torque_data.loc[abs_idx], 0), abs_idx
        return None, None

    def find_jtc() -> Tuple[float, int]:
        val = round(torque_data.max(), 2)
        abs_idx = torque_data.idxmax()
        return val, abs_idx

    # Main loop
    df_cycle_breakpoints, total_cycles = find_cycle_breakpoints(raw_data, channel_visibility, channel_map)
    torque_signature_values: List[Dict[str, Any]] = []
    torque_signature_indices: List[Dict[str, Any]] = []
    actuator_signature_values: List[Dict[str, Any]] = []
    actuator_signature_indices: List[Dict[str, Any]] = []
    for cycle, start_idx, one_quarter_idx, middle_idx, three_quarter_idx, end_idx in df_cycle_breakpoints.itertuples(index=False, name=None):
        backseat_data   = raw_data.loc[start_idx:end_idx, channel_map["Backseat"]]
        actuator_data   = raw_data.loc[start_idx:end_idx, channel_map["Actuator"]]
        downstream_data = raw_data.loc[start_idx:end_idx, channel_map["Downstream"]]
        torque_data     = raw_data.loc[start_idx:end_idx, channel_map["Torque"]]

        if channel_visibility.loc[channel_map["Torque"]].all():
            jto, jto_idx = find_jto()
            bto, bto_idx = find_bto(jto_idx)
            rpo, rpo_idx = find_rpo()
            rno, rno_idx = find_rno(rpo_idx if rpo_idx is not None else bto_idx, jto_idx)
            jtc, jtc_idx = find_jtc()
            btc, btc_idx = find_btc(jtc_idx)
            rpc, rpc_idx = find_rpc(jtc_idx if jtc_idx is not None else end_idx)
            rnc, rnc_idx = find_rnc(btc_idx, jtc_idx, rpc_idx)
            torque_signature_values.append({
                "Cycle": cycle,
                "BTO": bto,
                "RPO": rpo,
                "RNO": rno,
                "JTO": jto,
                "BTC": btc,
                "RNC": rnc,
                "RPC": rpc,
                "JTC": jtc,
            })
            torque_signature_indices.append({
                "Cycle": cycle,
                "BTO_Index": bto_idx,
                "RPO_Index": rpo_idx,
                "RNO_Index": rno_idx,
                "JTO_Index": jto_idx,
                "BTC_Index": btc_idx,
                "RNC_Index": rnc_idx,
                "RPC_Index": rpc_idx,
                "JTC_Index": jtc_idx,        
            })
        else:
            a1, a1_idx = find_a1()
            a3, a3_idx = find_a3()
            a4, a4_idx = find_a4()
            a2, a2_idx = find_a2(a3_idx if a3_idx is not None else one_quarter_idx)
            a5, a5_idx = find_a5(a4_idx if a4_idx is not None else a2_idx)
            r2, r2_idx = find_r2()
            r1, r1_idx = find_r1(r2_idx if r2_idx is not None else end_idx)
            r3, r3_idx = find_r3()
            r4, r4_idx = find_r4(r3_idx, r1_idx)
            actuator_signature_values.append({
                "Cycle": cycle,
                "A1": a1,
                "A2": a2,
                "A3": a3,
                "A4": a4,
                "A5": a5,
                "R1": r1,
                "R2": r2,
                "R3": r3,
                "R4": r4,
            })
            actuator_signature_indices.append({
                "Cycle": cycle,
                "A1_Index": a1_idx,
                "A2_Index": a2_idx,
                "A3_Index": a3_idx,
                "A4_Index": a4_idx,
                "A5_Index": a5_idx,
                "R1_Index": r1_idx,
                "R2_Index": r2_idx,
                "R3_Index": r3_idx,
                "R4_Index": r4_idx,
            })

    if channel_visibility.loc[channel_map["Torque"]].all():
        torque_signature_values = pd.DataFrame.from_records(torque_signature_values).dropna(axis=1, how='all')
        torque_signature_values.loc[-1] = torque_signature_values.columns
        torque_signature_values.index = torque_signature_values.index + 1
        torque_signature_values = torque_signature_values.sort_index()
    else:
        actuator_signature_values = pd.DataFrame.from_records(actuator_signature_values).dropna(axis=1, how='all').astype('Int64')
        actuator_signature_values.loc[-1] = actuator_signature_values.columns
        actuator_signature_values.index = actuator_signature_values.index + 1
        actuator_signature_values = actuator_signature_values.sort_index()

    return (
        torque_signature_values, 
        pd.DataFrame.from_records(torque_signature_indices), 
        actuator_signature_values,
        pd.DataFrame.from_records(actuator_signature_indices),
    )

def calculate_number_of_turns_table(raw_data, channel_visibility, channel_map: dict[str, str]):
    no_turns_values: List[Dict[str, Any]] = []

    no_turns_series = raw_data[channel_map["Number Of Turns"]]
    rpm_series = raw_data[channel_map["Motor Speed"]]

    # Get precomputed cycle boundaries
    indices_ranges, _ = find_cycle_breakpoints(raw_data, channel_visibility, channel_map)

    for cycle, start_idx, _, middle_idx, _, end_idx in indices_ranges.itertuples(index=False, name=None):
        # Max Number of Turns
        no_turns_slice = no_turns_series.loc[start_idx:end_idx]
        max_no_turns = (no_turns_slice.max() - no_turns_slice.min()).round(2)

        # Max RPM during Open
        max_rpm_open_slice = rpm_series.loc[start_idx:middle_idx]
        max_rpm_open = round(max_rpm_open_slice.min(), 2)

        # Max RPM during Close
        max_rpm_close_slice = rpm_series.loc[middle_idx:end_idx]
        max_rpm_close = round(max_rpm_close_slice.max(), 2)

        # Store values
        no_turns_values.append({
            "Cycle": cycle,
            "Number of Turns": max_no_turns,
            "Max Opening Speed (rpm)": max_rpm_open,
            "Max Closing Speed (rpm)": max_rpm_close,
        })

    no_turns_values = pd.DataFrame.from_records(no_turns_values).dropna(axis=1, how='all')
    no_turns_values.loc[-1] = no_turns_values.columns
    no_turns_values.index = no_turns_values.index + 1
    no_turns_values = no_turns_values.sort_index()

    return no_turns_values
