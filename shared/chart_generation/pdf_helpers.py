"""Utilities for creating PDF reports from test data."""

import io
import os
from typing import Optional

import matplotlib as mpl
import matplotlib.pyplot as plt
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.colors import Color
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle

mpl.rcParams['agg.path.chunksize'] = 10000

CALIBRATION_THRESHOLDS = {
    "Abs Error (µA) - ±3.6 µA": 3.6,
    "Abs Error (mV) - ±0.12 mV": 0.12,
    "Abs Error (mV) - ±1.0 mV": 1.0,
}

def format_measurement(value, unit: str):
    """Return a measurement string with units or special cases."""
    if value is None:
        return "N/A"
    if isinstance(value, str):
        stripped = value.strip()
        if stripped in {"See Table", "N/A"} or stripped.endswith(unit):
            return stripped
    try:
        if float(value) == 0:
            return "N/A"
    except (TypeError, ValueError):
        return f"{value} {unit}"
    return f"{value} {unit}"

def format_torque(value):
    """Return a torque string with units or special cases."""
    return format_measurement(value, "ft.lbs")

class Layout:
    """Class to hold all layout constants for the PDF report."""
    PAGE_WIDTH, PAGE_HEIGHT = landscape(A4)

    # Margins
    MARGIN_LEFT = 15
    MARGIN_RIGHT = 15
    MARGIN_TOP = 15
    MARGIN_BOTTOM = 15

    # Main content area
    CONTENT_X_START = MARGIN_LEFT
    CONTENT_Y_START = MARGIN_BOTTOM
    CONTENT_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT
    CONTENT_HEIGHT = PAGE_HEIGHT - MARGIN_TOP - MARGIN_BOTTOM

    # Header section
    HEADER_X = CONTENT_X_START
    HEADER_Y = 515
    HEADER_W = 600
    HEADER_H = 65

    # Graph index/table section
    TABLE_X = CONTENT_X_START
    TABLE_Y = CONTENT_Y_START
    TABLE_W = HEADER_W
    TABLE_H = 51.5

    # Graph section
    GRAPH_X = CONTENT_X_START
    GRAPH_Y_NO_TABLE = CONTENT_Y_START
    GRAPH_H_NO_TABLE = 470
    GRAPH_Y_TABLE = CONTENT_Y_START + TABLE_H
    GRAPH_H_TABLE = GRAPH_H_NO_TABLE - TABLE_H
    GRAPH_W = HEADER_W

    # Right-hand side boxes
    RIGHT_COL_X = 630
    RIGHT_COL_W = 197

    LOGO_X = RIGHT_COL_X
    LOGO_Y = 515
    LOGO_W = 197
    LOGO_H = 65

    INFO_RIGHT_X = RIGHT_COL_X
    INFO_RIGHT_Y = 300
    INFO_RIGHT_W = RIGHT_COL_W
    INFO_RIGHT_H = 185

    CYCLE_COUNT_X = RIGHT_COL_X
    CYCLE_COUNT_Y = 278.75
    CYCLE_COUNT_W = RIGHT_COL_W
    CYCLE_COUNT_H = 17.5

    TEST_PRESSURE_X = RIGHT_COL_X
    TEST_PRESSURE_Y = 257.5
    TEST_PRESSURE_W = RIGHT_COL_W
    TEST_PRESSURE_H = 17.5

    BREAKOUT_TORQUE_X = RIGHT_COL_X
    BREAKOUT_TORQUE_Y = 218.75
    BREAKOUT_TORQUE_W = RIGHT_COL_W
    BREAKOUT_TORQUE_H = 35

    STAMP_X = RIGHT_COL_X
    STAMP_Y = 35
    STAMP_W = RIGHT_COL_W
    STAMP_H = 180

    FOOTER_TEXT_Y = 10

    # Text positions
    MAIN_TITLE_X = 315
    MAIN_TITLE_Y = 500

    HEADER_COL1_LABEL_X = 20
    HEADER_COL1_VALUE_X = 140
    HEADER_COL2_LABEL_X = 402.5
    HEADER_COL2_VALUE_X = 487.5

    HEADER_ROW1_Y = 571.875
    HEADER_ROW2_Y = 555.625
    HEADER_ROW3_Y = 539.375
    HEADER_ROW4_Y = 523.125

    RIGHT_COL_LABEL_X = 635
    RIGHT_COL_VALUE_X = 725

    EQUIPMENT_TITLE_Y = 475
    DATA_LOGGER_Y = 457.5
    SERIAL_NO_Y = 442.5
    TRANSDUCERS_Y = 427.5
    GAUGES_Y = 367.5

    TORQUE_TRANSDUCER_Y = 307.5
    CYCLE_COUNT_TEXT_Y = 287.5
    TEST_PRESSURE_TEXT_Y = 266.25
    BREAKOUT_TORQUE_TEXT_Y = 245
    RUNNING_TORQUE_TEXT_Y = 227.5

    STAMP_TITLE_Y = 45
    OPERATIVE_Y = 22.5
    OPERATIVE_VALUE_X = 685

    TRANSDUCER_TABLE_START_X = 635
    TRANSDUCER_TABLE_START_Y = 412.5
    TRANSDUCER_COL_WIDTH = 39.375
    TRANSDUCER_ROW_HEIGHT = 15

    GAUGE_TABLE_START_X = 635
    GAUGE_TABLE_START_Y = 352.5
    GAUGE_COL_WIDTH = 50
    GAUGE_ROW_HEIGHT = 15


def evaluate_calibration_thresholds(
    table: pd.DataFrame,
    precise_errors: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """Return a boolean mask indicating threshold breaches for calibration tables."""

    if table is None or table.empty:
        return pd.DataFrame()

    mask: dict[str, pd.Series] = {}
    for row_label, threshold in CALIBRATION_THRESHOLDS.items():
        if row_label not in table.index:
            continue

        if precise_errors is not None and row_label.startswith("Abs Error"):
            values = pd.to_numeric(
                precise_errors.reindex(table.columns),
                errors="coerce",
            )
        else:
            values = pd.to_numeric(table.loc[row_label], errors="coerce")

        mask[row_label] = values.abs() > threshold

    if not mask:
        return pd.DataFrame(index=[], columns=table.columns, dtype=bool)

    result = pd.DataFrame(mask).T.fillna(False)
    return result.astype(bool)

def insert_plot_and_logo(figure, pdf, is_table):
    png_figure = io.BytesIO()
    figure.savefig(png_figure, format='PNG', bbox_inches='tight', dpi=500)
    png_figure.seek(0)
    plt.close(figure)
    fig_img = ImageReader(png_figure)

    if is_table:
        pdf.drawImage(
            fig_img,
            Layout.GRAPH_X+1,
            Layout.GRAPH_Y_TABLE+1,
            Layout.GRAPH_W-2,
            Layout.GRAPH_H_TABLE-2,
            preserveAspectRatio=False,
            mask="auto",
        )
    else:
        pdf.drawImage(
            fig_img,
            Layout.GRAPH_X+1,
            Layout.GRAPH_Y_NO_TABLE+1,
            Layout.GRAPH_W-2,
            Layout.GRAPH_H_NO_TABLE-2,
            preserveAspectRatio=False,
            mask="auto",
        )

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    image_path = os.path.join(BASE_DIR, "R&D.png")

    try:
        pdf.drawImage(
            image_path,
            Layout.LOGO_X,
            Layout.LOGO_Y,
            Layout.LOGO_W,
            Layout.LOGO_H,
            preserveAspectRatio=True,
            mask="auto",
        )
    except Exception as e:
        print(f"Warning: Could not load logo image at {image_path}. Error: {e}")

    pdf.save()
    plt.close('all')

def draw_bounding_box(pdf_canvas, x, y, width, height):
    pdf_canvas.setLineWidth(0.5)
    pdf_canvas.rect(x, y, width, height)

def draw_text_on_pdf(
    pdf_canvas,
    text,
    x,
    y,
    font="Helvetica",
    colour="black",
    size=10,
    left_aligned=False,
    replace_empty=False,
):
    text = "" if text is None else str(text)
    if replace_empty:
        text = "N/A" if not text.strip() else text

    pdf_canvas.setFont(font, size)
    text_width = pdf_canvas.stringWidth(text, font, size)
    text_height = size * 0.7

    draw_x = x if left_aligned else x - (text_width / 2)
    draw_y = y - (text_height / 2)

    pdf_canvas.setFillColor(colour if colour else colors.black)
    pdf_canvas.drawString(draw_x, draw_y, text)
    pdf_canvas.setFillColor(colors.black)

def draw_layout_boxes(pdf, is_table):
    PDF_LAYOUT_BOXES = [
        (Layout.HEADER_X, Layout.HEADER_Y, Layout.HEADER_W, Layout.HEADER_H),
        (Layout.GRAPH_X, Layout.GRAPH_Y_TABLE, Layout.GRAPH_W, Layout.GRAPH_H_TABLE) if is_table else (Layout.GRAPH_X, Layout.GRAPH_Y_NO_TABLE, Layout.GRAPH_W, Layout.GRAPH_H_NO_TABLE),
        (Layout.TABLE_X, Layout.TABLE_Y, Layout.TABLE_W, Layout.TABLE_H) if is_table else (0, 0, 0, 0),
        (Layout.CYCLE_COUNT_X, Layout.CYCLE_COUNT_Y, Layout.CYCLE_COUNT_W, Layout.CYCLE_COUNT_H),
        (Layout.TEST_PRESSURE_X, Layout.TEST_PRESSURE_Y, Layout.TEST_PRESSURE_W, Layout.TEST_PRESSURE_H),
        (Layout.BREAKOUT_TORQUE_X, Layout.BREAKOUT_TORQUE_Y, Layout.BREAKOUT_TORQUE_W, Layout.BREAKOUT_TORQUE_H),
        (Layout.STAMP_X, Layout.STAMP_Y, Layout.STAMP_W, Layout.STAMP_H),
        (Layout.INFO_RIGHT_X, Layout.INFO_RIGHT_Y, Layout.INFO_RIGHT_W, Layout.INFO_RIGHT_H),
    ]
    for box in PDF_LAYOUT_BOXES:
        draw_bounding_box(pdf, *box)

def _combine_section_and_name(section_number: Optional[str], test_name: Optional[str]) -> str:
    """Return a formatted test title with the section number prefix."""

    section = str(section_number or "").strip()
    name = str(test_name or "").strip()

    if not section:
        return name
    if not name:
        return section
    if name.startswith(section):
        return name
    return f"{section} {name}".strip()


def build_test_title(test_metadata) -> str:
    """Construct the display title for a test from its metadata."""

    section = test_metadata.get("Test Section Number")  # returns None if missing
    name = test_metadata['Test Name']
    return _combine_section_and_name(section, name)

def draw_headers(pdf, test_metadata, cleaned_data, light_blue):
    draw_text_on_pdf(
        pdf,
        build_test_title(test_metadata),
        Layout.MAIN_TITLE_X,
        Layout.MAIN_TITLE_Y,
        font="Helvetica-Bold",
        size=16,
    )
    draw_text_on_pdf(
        pdf, "Data Recording Equipment Used", Layout.RIGHT_COL_X + (Layout.RIGHT_COL_W / 2), Layout.EQUIPMENT_TITLE_Y, "Helvetica-Bold", size=12
    )
    draw_text_on_pdf(
        pdf, "3rd Party Stamp and Date", Layout.RIGHT_COL_X + (Layout.RIGHT_COL_W / 2), Layout.STAMP_TITLE_Y, "Helvetica-Bold", size=12
    )

def prepare_transducer_dataframe(transducer_codes, gauge_codes, active_channels):
    # Select used transducers and gauges
    active_transducers = transducer_codes[transducer_codes['channel'].isin(active_channels)]
    non_torque_transducers = active_transducers[
        active_transducers['channel'].astype(str).str.strip().str.lower() != 'torque'
    ]
    used_transducers = non_torque_transducers['transducer']
    used_gauges = gauge_codes[gauge_codes['channel'].isin(active_channels)]['gauge']

    # Drop blank/NaN/empty-string rows and shift up
    used_transducers = used_transducers[used_transducers.fillna("") != ""].reset_index(drop=True)
    used_gauges = used_gauges[used_gauges.fillna("") != ""].reset_index(drop=True)

    # Add 14 empty rows at the end
    empty_rows = pd.DataFrame([""] * 14)

    # Concatenate, ensure no NaNs
    used_transducers = pd.concat([used_transducers, empty_rows], ignore_index=True).fillna("")
    used_gauges = pd.concat([used_gauges, empty_rows], ignore_index=True).fillna("")

    return used_transducers, used_gauges

def build_static_text_positions(test_metadata, light_blue, black, max_cycle=None):    
    breakout_label = test_metadata.get('Breakout Label', 'Breakout Torque')
    running_label = test_metadata.get('Running Label', 'Running Torque')
    breakout_unit = test_metadata.get('Breakout Unit', 'ft.lbs')
    running_unit = test_metadata.get('Running Unit', 'ft.lbs')

    return [
        (Layout.HEADER_COL1_LABEL_X, Layout.HEADER_ROW1_Y, "Test Procedure Reference", black, False),
        (Layout.HEADER_COL1_VALUE_X, Layout.HEADER_ROW1_Y, test_metadata['Test Procedure Reference'], light_blue, True),
        (Layout.HEADER_COL1_LABEL_X, Layout.HEADER_ROW2_Y, "Unique No.", black, False),
        (Layout.HEADER_COL1_VALUE_X, Layout.HEADER_ROW2_Y, test_metadata['Unique Number'], light_blue, True),
        (Layout.HEADER_COL1_LABEL_X, Layout.HEADER_ROW3_Y, "R&D Reference", black, False),
        (Layout.HEADER_COL1_VALUE_X, Layout.HEADER_ROW3_Y, test_metadata['R&D Reference'], light_blue, True),
        (Layout.HEADER_COL1_LABEL_X, Layout.HEADER_ROW4_Y, "Valve Description", black, False),
        (Layout.HEADER_COL1_VALUE_X, Layout.HEADER_ROW4_Y, test_metadata['Valve Description'], light_blue, True),

        (Layout.HEADER_COL2_LABEL_X, Layout.HEADER_ROW1_Y, "Job No.", black, False),
        (Layout.HEADER_COL2_VALUE_X, Layout.HEADER_ROW1_Y, test_metadata['Job Number'], light_blue, True),
        (Layout.HEADER_COL2_LABEL_X, Layout.HEADER_ROW2_Y, "Test Description", black, False),
        (Layout.HEADER_COL2_VALUE_X, Layout.HEADER_ROW2_Y, test_metadata['Test Section Number'], light_blue, True),
        (Layout.HEADER_COL2_LABEL_X, Layout.HEADER_ROW3_Y, "Test Date", black, False),
        (Layout.HEADER_COL2_LABEL_X, Layout.HEADER_ROW4_Y, "Valve Drawing No.", black, False),
        (Layout.HEADER_COL2_VALUE_X, Layout.HEADER_ROW4_Y, test_metadata['Valve Drawing Number'], light_blue, True),

        (Layout.RIGHT_COL_LABEL_X, Layout.TEST_PRESSURE_TEXT_Y, "Test Pressure", black, False),
        (Layout.RIGHT_COL_VALUE_X, Layout.TEST_PRESSURE_TEXT_Y, f"{test_metadata['Test Pressure']} psi", light_blue, True),
        (Layout.RIGHT_COL_LABEL_X, Layout.CYCLE_COUNT_TEXT_Y, "Cycle Count", black, False),
        (Layout.RIGHT_COL_VALUE_X, Layout.CYCLE_COUNT_TEXT_Y - 1.25, f"{max_cycle}" if max_cycle is not None else "", light_blue, True),
        (Layout.RIGHT_COL_LABEL_X, Layout.BREAKOUT_TORQUE_TEXT_Y, breakout_label, black, False),
        (Layout.RIGHT_COL_VALUE_X, Layout.BREAKOUT_TORQUE_TEXT_Y, format_measurement(test_metadata.get('Breakout Torque'), breakout_unit), light_blue, True),
        (Layout.RIGHT_COL_LABEL_X, Layout.RUNNING_TORQUE_TEXT_Y, running_label, black, False),
        (Layout.RIGHT_COL_VALUE_X, Layout.RUNNING_TORQUE_TEXT_Y, format_measurement(test_metadata.get('Running Torque'), running_unit), light_blue, True),

        (Layout.RIGHT_COL_LABEL_X, Layout.DATA_LOGGER_Y, "Data Logger", black, False),
        (Layout.RIGHT_COL_VALUE_X, Layout.DATA_LOGGER_Y, test_metadata['Data Logger'], light_blue, True),
        (Layout.RIGHT_COL_LABEL_X, Layout.SERIAL_NO_Y, "Serial No.", black, False),
        (Layout.RIGHT_COL_VALUE_X, Layout.SERIAL_NO_Y, test_metadata['Serial Number'], light_blue, True),
        (Layout.RIGHT_COL_LABEL_X, Layout.TRANSDUCERS_Y, "Transducers", black, False),
        (Layout.RIGHT_COL_LABEL_X, Layout.GAUGES_Y, "Gauges", black, False),

        (Layout.RIGHT_COL_LABEL_X, Layout.OPERATIVE_Y, "Operative:", black, False),
        (Layout.OPERATIVE_VALUE_X, Layout.OPERATIVE_Y, test_metadata['Operative'], light_blue, False),
    ]

def build_transducer_and_gauge_positions(used_transducers, used_gauges, light_blue):
    positions = []
    for i in range(14):
        x = Layout.TRANSDUCER_TABLE_START_X + (i % 5) * Layout.TRANSDUCER_COL_WIDTH
        y = Layout.TRANSDUCER_TABLE_START_Y - (i // 5) * Layout.TRANSDUCER_ROW_HEIGHT
        positions.append((x, y, used_transducers.iloc[i, 0], light_blue, False))
    for i in range(12):
        x = Layout.GAUGE_TABLE_START_X + (i % 4) * Layout.GAUGE_COL_WIDTH
        y = Layout.GAUGE_TABLE_START_Y - (i // 4) * Layout.GAUGE_ROW_HEIGHT
        positions.append((x, y, used_gauges.iloc[i, 0], light_blue, False))
    return positions

def build_torque_and_stamp_positions(transducer_codes, test_metadata, light_blue, black):
    torque_transducer = ""
    if transducer_codes is not None and {'channel', 'transducer'}.issubset(transducer_codes.columns):
        torque_rows = transducer_codes[
            transducer_codes['channel'].astype(str).str.strip().str.lower() == 'torque'
        ]
        if not torque_rows.empty:
            torque_value = torque_rows['transducer'].iloc[0]
            if pd.notna(torque_value):
                torque_transducer = str(torque_value)
    return [
        (Layout.RIGHT_COL_LABEL_X, Layout.TORQUE_TRANSDUCER_Y, "Torque Transducer", black, False),
        (Layout.RIGHT_COL_VALUE_X, Layout.TORQUE_TRANSDUCER_Y, torque_transducer, light_blue, True),
    ]

def draw_table(pdf_canvas, dataframe, x=15, y=15, width=600, height=51.5):
    """Render a pandas DataFrame as a table on the PDF canvas (no headers, no index) with calibration colouring."""
    if dataframe is None or dataframe.empty:
        return

    # Remove all-null columns
    df = dataframe.dropna(axis=1, how="all")

    # Table data = just the values (no headers, no index)
    data = df.astype(str).values.tolist()
    if not data or not data[0]:
        return

    # ---- Dimensions ----
    rows = len(data)
    cols = len(data[0])
    col_width  = width / cols
    row_height = height / rows

    table = Table(
        data,
        colWidths=col_width,
        rowHeights=[row_height] * rows,
    )

    # Base style (uniform across all cells)
    style = TableStyle([
        ('ALIGN',      (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME',   (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE',   (0, 0), (-1, -1), 8),
        ('GRID',       (0, 0), (-1, -1), 0.5, colors.black),
        ('BACKGROUND', (0, 0), (-1, -1), colors.white),
        ('TEXTCOLOR',  (0, 0), (-1, -1), colors.black),
    ])

    breach_mask = evaluate_calibration_thresholds(df)

    for i, row_label in enumerate(df.index.astype(str)):
        if row_label not in CALIBRATION_THRESHOLDS:
            continue

        numeric_row = pd.to_numeric(df.loc[row_label], errors="coerce")
        breaches = (
            breach_mask.loc[row_label]
            if row_label in breach_mask.index
            else pd.Series(index=df.columns, data=False)
        )

        for col_offset, (column_key, value) in enumerate(numeric_row.items(), start=0):
            if pd.isna(value):
                continue
            breached = bool(breaches.get(column_key, False))
            style.add(
                'BACKGROUND',
                (col_offset, i),
                (col_offset, i),
                colors.red if breached else colors.limegreen,
            )

    table.setStyle(style)

    # ---- Draw ----
    table.wrapOn(pdf_canvas, width, height)
    table.drawOn(pdf_canvas, x, y)


def draw_regression_table(
    pdf_canvas,
    coefficients: Optional[pd.Series],
    x: float = Layout.STAMP_X + 5,
    y: Optional[float] = None,
    width: float = Layout.STAMP_W - 10,
    padding: float = 5,
):
    """Draw the polynomial coefficients table within the stamp area."""

    if coefficients is None:
        return

    series = pd.Series(coefficients).reindex(["S3", "S2", "S1", "S0"])
    if series.dropna().empty:
        return

    data = [["Coefficient", "Value"]]
    for label, value in series.items():
        display = "N/A" if pd.isna(value) else f"{value:.5g}"
        data.append([label, display])

    table = Table(
        data,
        colWidths=[width * 0.45, width * 0.55],
    )

    style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
    ])
    table.setStyle(style)

    available_height = Layout.STAMP_H - (2 * padding)
    _, table_height = table.wrap(width, available_height)
    draw_y = (
        Layout.STAMP_Y + Layout.STAMP_H - padding - table_height
        if y is None
        else y
    )

    table.drawOn(pdf_canvas, x, draw_y)

def draw_all_text(pdf, pdf_text_positions):
    for x, y, text, colour, replace_empty in pdf_text_positions:
        draw_text_on_pdf(pdf, text, x, y, colour=colour, size=10, left_aligned=True, replace_empty=replace_empty)

def draw_footer_metadata(pdf_canvas, test_metadata) -> None:
    """Render the run timestamp in the bottom-right corner of the page."""

    date_time = test_metadata["Date Time"]
    if not date_time:
        return

    font = "Helvetica-Oblique"
    size = 8
    colour = Color(0.5, 0.5, 0.5)

    text_width = pdf_canvas.stringWidth(date_time, font, size)
    x = Layout.PAGE_WIDTH - Layout.MARGIN_RIGHT - text_width

    draw_text_on_pdf(
        pdf_canvas,
        date_time,
        x,
        Layout.FOOTER_TEXT_Y,
        colour=colour,
        font=font,
        size=size,
        left_aligned=True,
    )

def draw_test_details(
    test_metadata,
    transducer_codes,
    gauge_codes,
    active_channels,
    cleaned_data,
    pdf_output_path,
    is_table,
    raw_data,
    has_breakout_table: bool = False,
    cycle_count_override: Optional[int] = None,
):
    if is_table and has_breakout_table:
        for field in ("Breakout Torque", "Running Torque"):
            test_metadata[field] = "See Table"

    pdf = canvas.Canvas(str(pdf_output_path), pagesize=landscape(A4))
    pdf.setStrokeColor(colors.black)
    draw_layout_boxes(pdf, is_table)
    light_blue = Color(0.325, 0.529, 0.761)
    black = Color(0, 0, 0)
    draw_headers(pdf, test_metadata, cleaned_data, light_blue)
    if cycle_count_override is not None:
        max_cycle = cycle_count_override
    elif test_metadata["Program Name"] in {"Signatures", "Signature Performance Test"}:
        max_cycle = 3
    else:
        max_cycle = int(raw_data["Cycle Count"].max())
    used_transducers, used_gauges = prepare_transducer_dataframe(transducer_codes, gauge_codes, active_channels)
    pdf_text_positions = build_static_text_positions(test_metadata, light_blue, black, max_cycle)
    report_date = ""
    if not cleaned_data.empty:
        first_timestamp = cleaned_data.iloc[0]["Datetime"]
        if pd.notna(first_timestamp):
            report_date = first_timestamp.strftime("%d/%m/%Y")
    draw_text_on_pdf(
        pdf,
        report_date,
        Layout.HEADER_COL2_VALUE_X,
        Layout.HEADER_ROW3_Y,
        colour=light_blue,
        left_aligned=True,
    )
    pdf_text_positions += build_torque_and_stamp_positions(transducer_codes, test_metadata, light_blue, black)
    pdf_text_positions += build_transducer_and_gauge_positions(used_transducers, used_gauges, light_blue)
    draw_all_text(pdf, pdf_text_positions)
    draw_footer_metadata(pdf, test_metadata)
    return pdf
