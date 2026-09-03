"""Program specific handlers for creating PDFs."""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import math
import pandas as pd

from graph_plotter import (
    plot_channel_data,
    plot_crosses,
)
from plotter_info import CHANNEL_AXIS_NAMES_MAP
from pdf_helpers import (
    draw_table,
    draw_test_details,
    draw_regression_table,
    evaluate_calibration_thresholds,
    build_test_title,
    insert_plot_and_logo,
)
from additional_info_functions import (
    locate_bto_btc_rows,
    locate_actuator_breakout_rows,
    locate_key_time_rows,
    locate_signature_key_points,
    find_cycle_breakpoints,
    locate_calibration_points,
    calculate_succesful_calibration,
    calculate_calibration_regression,
    calculate_number_of_turns_table,
)
from report_utils import sanitise_report_filename_component

class BaseReportGenerator:
    def __init__(self, **kwargs):
        self.program_name = kwargs.get("program_name")
        self.pdf_output_path = kwargs.get("pdf_output_path")
        self.test_metadata = kwargs.get("test_metadata")
        self.transducer_codes = kwargs.get("transducer_codes")
        self.gauge_codes = kwargs.get("gauge_codes")
        self.channel_visibility = kwargs.get("channel_visibility")
        self.mass_spec_timings = kwargs.get("mass_spec_timings")
        self.holds = kwargs.get("holds")
        self.cycles = kwargs.get("cycles")
        self.calibration = kwargs.get("calibration")
        self.active_channels = kwargs.get("active_channels")
        self.cleaned_data = kwargs.get("cleaned_data")
        self.raw_data = kwargs.get("raw_data")
        self.channel_map = kwargs.get("channel_map")
        self.channel_info = kwargs.get("channel_info")

        if isinstance(self.test_metadata, pd.DataFrame):
            self.test_metadata = self.test_metadata.iloc[:, 0].to_dict()
        elif isinstance(self.test_metadata, pd.Series):
            self.test_metadata = self.test_metadata.to_dict()

    def _channels_for_main_plot(self, include_mass_spec: bool = False) -> List[str]:
        """Return the active channels for the primary plot.

        Unless ``include_mass_spec`` is ``True`` the channel mapped from the
        default ``"Mass Spectrometer"`` entry is removed so it does not appear
        on standard report pages.
        """

        channels = list(self.active_channels or [])
        if include_mass_spec:
            return channels

        mass_spec_channel = None
        if self.channel_map:
            mass_spec_channel = self.channel_map.get("Mass Spectrometer")

        if mass_spec_channel and mass_spec_channel in channels:
            channels = [ch for ch in channels if ch != mass_spec_channel]

        return channels
    
    def _is_channel_recorded(self, default_channel: str) -> bool:
        """Return ``True`` when the default channel has recorded data."""

        if not isinstance(self.channel_visibility, pd.DataFrame):
            return False

        if not self.channel_map or default_channel not in self.channel_map:
            return False

        channel_name = self.channel_map[default_channel]
        if channel_name not in self.channel_visibility.index:
            return False

        return self.channel_visibility.loc[channel_name, 'visible']

    @staticmethod
    def _coerce_metadata_bool(value: Any) -> bool:
        """Interpret booleans stored as native values or common strings."""

        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}

        try:
            if pd.isna(value):
                return False
        except TypeError:
            pass

        return bool(value)

    def _metadata_bool(self, *keys: str, default: bool = False) -> bool:
        """Return the first present metadata flag coerced to bool."""

        if not isinstance(self.test_metadata, dict):
            return default

        for key in keys:
            if key in self.test_metadata:
                return self._coerce_metadata_bool(self.test_metadata.get(key))

        return default

    def _show_breakout_values_enabled(self) -> bool:
        """Support both the legacy and new breakout-table metadata flags."""

        return self._metadata_bool("Show Breakout Values", "Show Breakout Torque", default=False)

    def build_output_path(self, test_metadata) -> Path:
        """Construct the output PDF path from metadata."""
        full_name = build_test_title(test_metadata)
        safe_name = sanitise_report_filename_component(full_name, default="Report")
        safe_timestamp = sanitise_report_filename_component(
            test_metadata.get('Date Time'),
            default="unknown-time",
        )
        return self.pdf_output_path / (
            f"{safe_name}_"
            f"{safe_timestamp}.tmp.pdf"
        )
    
    def finalize_output_path(self, temp_path: Path) -> Path:
        """Rename the temporary PDF path to its final name and return it."""

        name = temp_path.name

        if not name.endswith(".tmp.pdf"):
            return temp_path  # not a temp pdf

        final_path = Path(temp_path.parent, name[:-8] + ".pdf")

        # if exists, delete old
        if final_path.exists():
            final_path.unlink()

        if not temp_path.exists():
            return final_path

        temp_path.replace(final_path)  # atomic rename

        return final_path


    def generate(self) -> Path:
        """Generate the report."""
        raise NotImplementedError

class GenericReportGenerator(BaseReportGenerator):
    def generate(self) -> Path:
        is_table = False
        unique_path = self.build_output_path(self.test_metadata)
        figure, _, _ = plot_channel_data(
            active_channels=self._channels_for_main_plot(),
            cleaned_data=self.cleaned_data,
            test_metadata=self.test_metadata,
            is_table=is_table,
            channel_map=self.channel_map,
        )
        pdf = draw_test_details(
            test_metadata=self.test_metadata,
            transducer_codes=self.transducer_codes,
            gauge_codes=self.gauge_codes,
            active_channels=self.active_channels,
            cleaned_data=self.cleaned_data,
            pdf_output_path=unique_path,
            is_table=is_table,
            raw_data=self.raw_data,
        )
        insert_plot_and_logo(figure, pdf, is_table)
        return self.finalize_output_path(unique_path)
        
class NumberOfTurnsReportGenerator(BaseReportGenerator):
    def generate(self) -> Path:
        is_table = True
        unique_path = self.build_output_path(self.test_metadata)
        figure, _, _ = plot_channel_data(
            active_channels=self._channels_for_main_plot(),
            cleaned_data=self.cleaned_data,
            test_metadata=self.test_metadata,
            is_table=is_table,
            channel_map=self.channel_map,
        )
        pdf = draw_test_details(
            test_metadata=self.test_metadata,
            transducer_codes=self.transducer_codes,
            gauge_codes=self.gauge_codes,
            active_channels=self.active_channels,
            cleaned_data=self.cleaned_data,
            pdf_output_path=unique_path,
            is_table=is_table,
            raw_data=self.raw_data,
        )
        table = calculate_number_of_turns_table(
            raw_data=self.raw_data,
            channel_visibility=self.channel_visibility,
            channel_map=self.channel_map,
        )
        draw_table(pdf_canvas=pdf, dataframe=table)
        insert_plot_and_logo(figure, pdf, is_table)
        return self.finalize_output_path(unique_path)
    
class HoldsReportGenerator(BaseReportGenerator):
    """Generate reports for hold tests.

    The ``additional_info`` DataFrame is expected to contain a single header
    row followed by groups of three data rows describing individual holds.
    """

    def generate(self) -> List[Path]:
        title_prefix = self.test_metadata['Test Section Number']

        generated_paths: List[Path] = []

        multi_cycle = int(self.holds["cycle_index"].max()) > 1

        for _, hold in self.holds.iterrows():
            path = self._generate_single_hold_report(title_prefix, hold, multi_cycle)
            generated_paths.append(path)

        return generated_paths


    def _generate_single_hold_report(self, title_prefix, hold_info, multi_cycle):
        is_table = True
        operation_type = str(self.test_metadata.get("Type of Operation", "")).strip()

        if multi_cycle:
            self.test_metadata['Test Section Number'] = (
                f"{title_prefix}.{hold_info['cycle_index']}"
            )

        if operation_type == "1":
            breakout_value = hold_info.get('breakout_0_psi')
            running_value = hold_info.get('breakout_wp')

            if pd.isna(breakout_value):
                breakout_value = hold_info.get('breakout_torque')
            if pd.isna(running_value):
                running_value = hold_info.get('running_torque')

            self.test_metadata['Breakout Label'] = 'Breakout @ 0 psi'
            self.test_metadata['Running Label'] = 'Breakout @ WP'
            self.test_metadata['Breakout Unit'] = 'psi'
            self.test_metadata['Running Unit'] = 'psi'
        else:
            breakout_value = hold_info.get('breakout_torque')
            running_value = hold_info.get('running_torque')
            self.test_metadata['Breakout Label'] = 'Breakout Torque'
            self.test_metadata['Running Label'] = 'Running Torque'
            self.test_metadata['Breakout Unit'] = 'ft.lbs'
            self.test_metadata['Running Unit'] = 'ft.lbs'

        self.test_metadata['Breakout Torque'] = breakout_value
        self.test_metadata['Running Torque'] = running_value

        unique_path = self.build_output_path(self.test_metadata)
        holds_indices, display_table = locate_key_time_rows(self.cleaned_data, hold_info)

        figure, axes, axis_map = plot_channel_data(
            active_channels=self._channels_for_main_plot(),
            cleaned_data=self.cleaned_data,
            test_metadata=self.test_metadata,
            is_table=is_table,
            channel_map=self.channel_map,
        )
        hold_channel = hold_info['channel']
        custom_to_default_map = {v: k for k, v in self.channel_map.items()}
        default_hold_channel = custom_to_default_map.get(hold_channel, hold_channel)
        axis_type = CHANNEL_AXIS_NAMES_MAP.get(default_hold_channel, 'Pressure')
        axis_location = axis_map.get(axis_type, 'left')

        plot_crosses(
            df=holds_indices,
            channel=hold_channel,
            data=self.cleaned_data,
            ax=axes[axis_location],
        )
        pdf = draw_test_details(
            self.test_metadata, self.transducer_codes, self.gauge_codes, self.active_channels,
            self.cleaned_data, unique_path, is_table, self.raw_data
        )

        display_table.loc[-1] = display_table.columns
        display_table.index = display_table.index + 1
        display_table = display_table.sort_index()
        display_table.columns = range(display_table.shape[1])

        draw_table(pdf_canvas=pdf, dataframe=display_table)
        insert_plot_and_logo(figure, pdf, is_table)
        return self.finalize_output_path(unique_path)
    
class BreakoutsReportGenerator(BaseReportGenerator):
    def generate(self) -> List[Path]:
        breakout_requested = self._show_breakout_values_enabled()
        operation_type = str(self.test_metadata.get("Type of Operation", "")).strip()
        plot_channel, axis_key = self._breakout_plot_target(operation_type)
        show_breakout = breakout_requested and self._is_breakout_source_recorded(operation_type)
        if show_breakout:
            breakout_values, breakout_indices = self._resolve_breakout_rows(show_breakout, operation_type)
        else:
            breakout_values = pd.DataFrame(columns=['Cycle'])
            breakout_indices = pd.DataFrame(columns=['Cycle'])

        cycle_ranges, _ = find_cycle_breakpoints(self.raw_data, self.channel_visibility, self.channel_map)
        all_cycles = cycle_ranges['Cycle'].tolist() if not cycle_ranges.empty else []
        generated_paths = []

        if breakout_values is None:
            breakout_values = pd.DataFrame(columns=['Cycle'])
        if breakout_indices is None:
            breakout_indices = pd.DataFrame(columns=['Cycle'])

        if show_breakout and breakout_values.empty:
            show_breakout = False

        if show_breakout:
            cycles_to_display = all_cycles[-3:] or all_cycles
        else:
            cycles_to_display = all_cycles

        if not cycles_to_display:
            return generated_paths

        path = self._generate_breakout_cycles_page(
            cycles=cycles_to_display,
            cycle_ranges=cycle_ranges,
            breakout_values=breakout_values,
            breakout_indices=breakout_indices,
            show_breakout=show_breakout,
            plot_channel=plot_channel,
            axis_key=axis_key,
        )
        generated_paths.append(path)

        return generated_paths
    
    def _generate_breakout_cycles_page(
        self,
        cycles,
        cycle_ranges,
        breakout_values,
        breakout_indices,
        show_breakout,
        plot_channel,
        axis_key,
    ):
        ordered_cycles = sorted(cycles)
        unique_path = self.build_output_path(self.test_metadata)
        data_slice = self._slice_data(self.cleaned_data, cycle_ranges, ordered_cycles)
        breakout_table = self._prepend_column_header_row(
            self._renumber_cycle_column(
                self._filter_cycles_dataframe(breakout_values, ordered_cycles)
            )
        )
        displayed_cycle_count = len(ordered_cycles) if show_breakout else None

        figure, axes, axis_map = plot_channel_data(
            self._channels_for_main_plot(),
            data_slice,
            self.test_metadata,
            is_table=show_breakout,
            channel_map=self.channel_map,
        )

        if show_breakout:
            axis_location = axis_map.get(axis_key)
            index_slice = self._filter_cycles_dataframe(breakout_indices, ordered_cycles)
            if axis_location is not None and not index_slice.empty:
                plot_crosses(
                    df=index_slice,
                    channel=plot_channel,
                    data=data_slice,
                    ax=axes[axis_location],
                )

            pdf = draw_test_details(
                self.test_metadata,
                self.transducer_codes,
                self.gauge_codes,
                self.active_channels,
                data_slice,
                unique_path,
                True,
                self.raw_data,
                has_breakout_table=(axis_key == 'Torque' and not breakout_table.empty),
                cycle_count_override=displayed_cycle_count,
            )
            draw_table(pdf_canvas=pdf, dataframe=breakout_table)
            insert_plot_and_logo(figure, pdf, True)
        else:
            pdf = draw_test_details(
                self.test_metadata,
                self.transducer_codes,
                self.gauge_codes,
                self.active_channels,
                data_slice,
                unique_path,
                False,
                self.raw_data,
            )
            insert_plot_and_logo(figure, pdf, False)

        return self.finalize_output_path(unique_path)
    
    def _slice_data(self, data, cycle_ranges, cycles):
        if cycle_ranges.empty:
            raise ValueError("Could not find any cycle ranges in the primary data.")

        missing_cycles = [
            cycle for cycle in cycles if cycle not in set(cycle_ranges['Cycle'].tolist())
        ]
        if missing_cycles:
            available_cycles = cycle_ranges['Cycle'].tolist()
            raise ValueError(
                "Requested cycle(s) "
                f"{missing_cycles} are not present in the primary data. "
                f"Available cycle(s): {available_cycles}."
            )

        start_idx = cycle_ranges.loc[cycle_ranges['Cycle'] == cycles[0], 'Start Index'].iat[0]
        end_idx = cycle_ranges.loc[cycle_ranges['Cycle'] == cycles[-1], 'End Index'].iat[0]
        return data.loc[start_idx:end_idx]

    def _resolve_breakout_rows(self, show_breakout: bool, operation_type: str):
        if not self._is_breakout_source_recorded(operation_type):
            return pd.DataFrame(columns=['Cycle']), pd.DataFrame(columns=['Cycle'])

        legacy_operation_type = operation_type == ""
        use_legacy_actuator_fallback = (
            legacy_operation_type
            and not self._is_channel_recorded('Torque')
            and self._is_channel_recorded('Actuator')
        )

        if show_breakout and (operation_type == "1" or use_legacy_actuator_fallback):
            breakout_values, breakout_indices = locate_actuator_breakout_rows(
                self.raw_data,
                self.channel_visibility,
                self.channel_map,
                self.test_metadata,
            )
            if breakout_values is None:
                breakout_values = pd.DataFrame(columns=['Cycle', 'Breakout'])
            if breakout_indices is None:
                breakout_indices = pd.DataFrame(columns=['Cycle'])
            return breakout_values, breakout_indices

        if show_breakout and operation_type == "0":
            breakout_values = self._recorded_breakout_values_from_cycles(self.cycles)
            if not breakout_values.empty:
                return breakout_values, pd.DataFrame(columns=['Cycle'])

        force_raw_breakout_lookup = show_breakout and (
            operation_type in {"2", "3", "4"}
            or legacy_operation_type
        )
        breakout_values, breakout_indices = locate_bto_btc_rows(
            self.raw_data,
            self.cycles,
            self.channel_visibility,
            self.channel_map,
            prefer_recorded_values=not force_raw_breakout_lookup,
            test_metadata=self.test_metadata,
        )

        if breakout_values is None and force_raw_breakout_lookup:
            breakout_values, breakout_indices = locate_bto_btc_rows(
                self.raw_data,
                self.cycles,
                self.channel_visibility,
                self.channel_map,
                prefer_recorded_values=True,
                test_metadata=self.test_metadata,
            )

        if show_breakout and operation_type == "0":
            breakout_indices = pd.DataFrame(columns=['Cycle'])

        return breakout_values, breakout_indices

    def _is_breakout_source_recorded(self, operation_type: str) -> bool:
        if operation_type == "":
            return self._is_channel_recorded('Torque') or self._is_channel_recorded('Actuator')
        if operation_type == "0":
            return True
        if operation_type == "1":
            return self._is_channel_recorded('Actuator')
        return self._is_channel_recorded('Torque')

    def _breakout_plot_target(self, operation_type: str) -> tuple[Optional[str], str]:
        if (
            operation_type == "1"
            or (
                operation_type == ""
                and not self._is_channel_recorded('Torque')
                and self._is_channel_recorded('Actuator')
            )
        ):
            return self.channel_map.get('Actuator'), 'Actuator'
        return self.channel_map.get('Torque'), 'Torque'

    @staticmethod
    def _recorded_breakout_values_from_cycles(cycles: Optional[pd.DataFrame]) -> pd.DataFrame:
        if cycles is None or cycles.empty:
            return pd.DataFrame(columns=['Cycle', 'BTO (lb·ft)', 'BTC (lb·ft)'])

        required_columns = {'cycle_index', 'bto', 'btc'}
        if not required_columns.issubset(cycles.columns):
            return pd.DataFrame(columns=['Cycle', 'BTO (lb·ft)', 'BTC (lb·ft)'])

        breakout_values = cycles.loc[:, ['cycle_index', 'bto', 'btc']].copy()
        breakout_values[['bto', 'btc']] = breakout_values[['bto', 'btc']].apply(
            pd.to_numeric,
            errors='coerce',
        )
        measurements = breakout_values.loc[:, ['bto', 'btc']]
        has_complete_measurements = measurements.notna().all(axis=1)
        if not has_complete_measurements.all():
            return pd.DataFrame(columns=['Cycle', 'BTO (lb·ft)', 'BTC (lb·ft)'])

        breakout_values.rename(
            columns={'cycle_index': 'Cycle', 'bto': 'BTO (lb·ft)', 'btc': 'BTC (lb·ft)'},
            inplace=True,
        )
        breakout_values.reset_index(drop=True, inplace=True)
        return breakout_values

    @staticmethod
    def _prepend_column_header_row(dataframe: Optional[pd.DataFrame]) -> pd.DataFrame:
        if dataframe is None:
            return pd.DataFrame()

        if dataframe.empty:
            return dataframe.copy()

        table = dataframe.copy()
        table.loc[-1] = table.columns
        table.index = table.index + 1
        table = table.sort_index()
        table.reset_index(drop=True, inplace=True)
        return table

    @staticmethod
    def _filter_cycles_dataframe(dataframe: Optional[pd.DataFrame], cycles: List[int]) -> pd.DataFrame:
        if dataframe is None:
            return pd.DataFrame()

        if dataframe.empty or 'Cycle' not in dataframe.columns:
            return dataframe.copy()

        cycle_values = pd.to_numeric(dataframe['Cycle'], errors='coerce')
        filtered = dataframe.loc[cycle_values.isin(cycles)].copy()
        filtered.reset_index(drop=True, inplace=True)
        return filtered

    @staticmethod
    def _renumber_cycle_column(dataframe: Optional[pd.DataFrame]) -> pd.DataFrame:
        if dataframe is None:
            return pd.DataFrame()

        renumbered = dataframe.copy()
        if renumbered.empty or 'Cycle' not in renumbered.columns:
            return renumbered

        renumbered.loc[:, 'Cycle'] = range(1, len(renumbered) + 1)
        return renumbered

class SignaturesReportGenerator(BreakoutsReportGenerator):
    def generate(self) -> List[Path]:
        torque_values, torque_indices, actuator_values, actuator_indices = locate_signature_key_points(
            self.channel_visibility, self.raw_data, self.channel_map, self.test_metadata
        )

        cycle_ranges, _ = find_cycle_breakpoints(self.raw_data, self.channel_visibility, self.channel_map)
        all_cycles = cycle_ranges['Cycle'].tolist() if not cycle_ranges.empty else []
        generated_paths = []
        show_breakout = self._show_breakout_values_enabled()

        if self._is_channel_recorded('Torque'):
            values_df, indices_df, plot_channel, axis_key = torque_values, torque_indices, self.channel_map['Torque'], 'Torque'
        else:
            values_df, indices_df, plot_channel, axis_key = actuator_values, actuator_indices, self.channel_map['Actuator'], 'Actuator'

        if show_breakout:
            values_df = self._select_first_and_last_rows(values_df)
            cycles_to_display = all_cycles[-3:] or all_cycles
        else:
            cycles_to_display = all_cycles

        if not cycles_to_display:
            return generated_paths

        path = self._generate_signature_cycles_page(
            cycles=cycles_to_display,
            cycle_ranges=cycle_ranges,
            values_df=values_df,
            indices_df=indices_df,
            plot_channel=plot_channel,
            axis_key=axis_key,
            show_breakout=show_breakout,
        )
        generated_paths.append(path)

        return generated_paths

    def _generate_signature_cycles_page(
        self,
        cycles,
        cycle_ranges,
        values_df,
        indices_df,
        plot_channel,
        axis_key,
        show_breakout,
    ):
        ordered_cycles = sorted(cycles)
        unique_path = self.build_output_path(self.test_metadata)
        data_slice = self._slice_data(self.cleaned_data, cycle_ranges, ordered_cycles)
        displayed_cycle_count = len(ordered_cycles) if show_breakout else 3

        figure, axes, axis_map = plot_channel_data(
            self._channels_for_main_plot(),
            data_slice,
            self.test_metadata,
            is_table=show_breakout,
            channel_map=self.channel_map,
        )

        if show_breakout:
            axis_location = axis_map.get(axis_key)
            if axis_location is not None:
                index_slice = indices_df[indices_df['Cycle'].isin(ordered_cycles)]
                plot_crosses(
                    df=index_slice,
                    channel=plot_channel,
                    data=data_slice,
                    ax=axes[axis_location],
                )

            pdf = draw_test_details(
                self.test_metadata,
                self.transducer_codes,
                self.gauge_codes,
                self.active_channels,
                data_slice,
                unique_path,
                True,
                self.raw_data,
                has_breakout_table=True,
                cycle_count_override=displayed_cycle_count,
            )

            draw_table(pdf_canvas=pdf, dataframe=values_df)
            insert_plot_and_logo(figure, pdf, True)
        else:
            pdf = draw_test_details(
                self.test_metadata,
                self.transducer_codes,
                self.gauge_codes,
                self.active_channels,
                data_slice,
                unique_path,
                False,
                self.raw_data,
                cycle_count_override=displayed_cycle_count,
            )
            insert_plot_and_logo(figure, pdf, False)

        return self.finalize_output_path(unique_path)
        
    @staticmethod
    def _select_first_and_last_rows(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
        indices = [df.index[0], *df.index[-3:]]
        seen = []
        for idx in indices:
            if idx not in seen:
                seen.append(idx)

        subset = df.loc[seen].copy()
        subset.reset_index(drop=True, inplace=True)

        if "Cycle" in subset.columns:
            start = max(len(subset) - 3, 0)
            cycle_values = [pd.NA] * len(subset)
            cycle_values[start:] = list(range(1, len(subset) - start + 1))
            subset.loc[:, "Cycle"] = cycle_values

        subset.at[0, 'Cycle'] = 'Cycle'

        return subset
    
class CalibrationReportGenerator(BaseReportGenerator):
    def generate(self) -> Path:
        is_table = True
        unique_path = self.build_output_path(self.test_metadata)
        calibration_indices = locate_calibration_points(self.cleaned_data, self.calibration)
        (
            average_values,
            counts_series,
            expected_series,
            abs_errors,
        ) = calculate_succesful_calibration(
            self.cleaned_data,
            calibration_indices,
            self.calibration,
        )

        breach_mask = evaluate_calibration_thresholds(average_values, abs_errors)
        has_breach = not breach_mask.empty and breach_mask.to_numpy().any()
        regression_coefficients = None
        if has_breach:
            regression_coefficients = calculate_calibration_regression(
                counts_series,
                expected_series,
            )

        figure, axes, axis_map = plot_channel_data(
            active_channels=self._channels_for_main_plot(include_mass_spec=True),
            cleaned_data=self.cleaned_data,
            test_metadata=self.test_metadata,
            is_table=is_table,
            channel_map=self.channel_map,
            lock_temperature_axis=False,
        )
        custom_to_default_map = {v: k for k, v in self.channel_map.items()}
        for phase in calibration_indices.index:
            positions = calibration_indices.loc[phase].dropna().astype(int).tolist()
            times = self.cleaned_data["Datetime"].iloc[positions]
            channel_name = self.calibration['channel_name']
            default_channel_name = custom_to_default_map.get(channel_name, channel_name)
            axis_type = CHANNEL_AXIS_NAMES_MAP.get(default_channel_name)
            axis_location = axis_map.get(axis_type, "left")
            axis = axes.get(axis_location, axes["left"])
            values = self.cleaned_data[channel_name].iloc[positions]
            axis.scatter(
                times, values, marker='x', s=50, color='black', label=f'calib_{phase}'
            )
        
        pdf = draw_test_details(
            self.test_metadata, self.transducer_codes, self.gauge_codes, self.active_channels,
            self.cleaned_data, unique_path, is_table, self.raw_data
        )
        draw_table(pdf_canvas=pdf, dataframe=average_values)
        if regression_coefficients is not None and not regression_coefficients.dropna().empty:
            draw_regression_table(pdf, regression_coefficients)
        insert_plot_and_logo(figure, pdf, is_table)
        return self.finalize_output_path(unique_path)
    
class DoNothingReportGenerator(BaseReportGenerator):
    def generate(self) -> None:
        return None

HANDLERS: Dict[str, Callable[..., Any]] = {
    "Initial Cycle": GenericReportGenerator,
    "Atmospheric Breakouts": BreakoutsReportGenerator,
    "Atmospheric Cyclic": BreakoutsReportGenerator,
    "PR2 Dynamic Cycle Test": BreakoutsReportGenerator,
    "Petrobras Dynamic Cycle Test": BreakoutsReportGenerator,
    "Pulse Cycle Test": GenericReportGenerator,
    "Signature Performance Test": SignaturesReportGenerator,
    "Holds": HoldsReportGenerator,
    "5 to 10% PR2 Test": HoldsReportGenerator,
    "Operation Cycle Test": BreakoutsReportGenerator,
    "Number of Turns & RPM Verification Test": NumberOfTurnsReportGenerator,
    "Calibration": CalibrationReportGenerator,
    "Data Logger": GenericReportGenerator,
}
