# Colour mapping for known channels
CHANNEL_COLOUR_MAP = {
    'Upstream': '#FF0000',
    'Downstream': '#00B050',
    'Body': '#FFA500',
    'Actuator': '#000000',
    'Hyperbaric': '#0000FF',
    'Backseat': '#00FFFF',
    'Spring Chamber': '#FF00FF',
    'Primary Stem Seal': '#80FF00',
    'Secondary Stem Seal': '#400080',
    'Relief Port': '#008080',
    'BX Port': '#800000',
    'Flow Meter': '#808000',
    'Mass Spectrometer Mantissa': '#FF66CC',
    'Mass Spectrometer': '#66B2FF',
    'LVDT': '#99FF33',
    'Torque': '#663300',
    'Number Of Turns': '#00FFAA',
    'Motor Speed': '#336699',
    'Ambient Temperature': '#0000FF',
    'Body Temperature': '#00B050',
    'Monitor Temperature': '#FFA500',
    'Chamber Temperature': '#000000',
    'Hyperbaric Temperature': '#FF0000',
    'Close': '#00FFFF',
    'Open': '#FF00FF',
    'Cycle Count': '#80FF00',
}

CHANNEL_LINESTYLE_MAP = {
    'Upstream': '-',
    'Downstream': '-',
    'Body': '-',
    'Actuator': '-',
    'Hyperbaric': '-',
    'Backseat': '-',
    'Spring Chamber': '-',
    'Primary Stem Seal': '-',
    'Secondary Stem Seal': '-',
    'Relief Port': '-',
    'BX Port': '-',
    'Flow Meter': '-',
    'Mass Spectrometer Mantissa': '-',
    'Mass Spectrometer': '-',
    'LVDT': '-',
    'Torque': '-',
    'Number Of Turns': '-',
    'Motor Speed': '-',
    'Ambient Temperature': ':',
    'Body Temperature': ':',
    'Monitor Temperature': ':',
    'Chamber Temperature': ':',
    'Hyperbaric Temperature': ':',
    'Close': ':',
    'Open': ':',
    'Cycle Count': ':',
}

CHANNEL_UNITS_MAP = {
    'Upstream': 'psi',
    'Downstream': 'psi',
    'Body': 'psi',
    'Actuator': 'psi',
    'Hyperbaric': 'psi',
    'Backseat': 'psi',
    'Spring Chamber': 'psi',
    'Primary Stem Seal': 'psi',
    'Secondary Stem Seal': 'psi',
    'Relief Port': 'psi',
    'BX Port': 'psi',
    'Leak Rate': 'ml/min',
    'Mass Spectrometer Mantissa': 'mbarl/sec',
    'Mass Spectrometer': 'mbarl/sec',
    'LVDT': 'mm',
    'Torque': 'lbs-ft',
    'Number Of Turns': '',
    'Motor Speed': 'rpm',
    'Ambient Temperature': '°C',
    'Body Temperature': '°C',
    'Monitor Temperature': '°C',
    'Chamber Temperature': '°C',
    'Hyperbaric Temperature': '°C',
    'Close': '',
    'Open': '',
    'Cycle Count': ''
}

CHANNEL_AXIS_NAMES_MAP = {
    'Upstream': 'Pressure',
    'Downstream': 'Pressure',
    'Body': 'Pressure',
    'Actuator': 'Actuator',
    'Hyperbaric': 'Pressure',
    'Backseat': 'Pressure',
    'Spring Chamber': 'Pressure',
    'Primary Stem Seal': 'Pressure',
    'Secondary Stem Seal': 'Pressure',
    'Relief Port': 'Pressure',
    'BX Port': 'Pressure',
    'Flow Meter': 'Leak Rate',
    'Mass Spectrometer Mantissa': 'Mass Spectrometer',
    'Mass Spectrometer': 'Mass Spectrometer',
    'LVDT': 'LVDT',
    'Torque': 'Torque',
    'Number Of Turns': 'Number Of Turns',
    'Motor Speed': 'Motor Speed',
    'Ambient Temperature': 'Temperature',
    'Body Temperature': 'Temperature',
    'Monitor Temperature': 'Temperature',
    'Chamber Temperature': 'Temperature',
    'Hyperbaric Temperature': 'Temperature',
    'Close': 'Valve State',
    'Open': 'Valve State',
    'Cycle Count': 'Cycle Count'
}

AXIS_COLOUR_MAP = {
    'Pressure': '#FF0000',              # Vivid Red
    'Actuator': '#000000',            # Black
    'Leak Rate': '#808000',             # Medium Lavender
    'Mass Spectrometer': '#66B2FF',     # Saddle Brown
    'LVDT': '#99FF33',                  # Maroon
    'Torque': '#663300',                # Dark Gold
    'Number Of Turns': '#00FFAA',       # Navy Blue
    'Motor Speed': '#336699',           # Emerald Green
    'Temperature': '#0000FF',           # Vivid Blue
    'Valve State' : "#00FFFF",
    'Cycle Count': '#80FF00'            # Orange
}


AXIS_PRIORITY = [
    'Pressure',
    'Actuator', 
    'Torque', 
    'Pneumatic', 
    'Leak Rate', 
    'Mass Spectrometer',
    'Number Of Turns', 
    'Motor Speed', 
    'LVDT',
    'Valve State',
    'Cycle Count',
    'Temperature'
]

AXIS_LOCATIONS = [
    'left',
    'right_1', 
    'right_2', 
    'right_3', 
    'right_4', 
    'right_5', 
    'right_6', 
    'right_7', 
    'right_8', 
    'right_9'
]
