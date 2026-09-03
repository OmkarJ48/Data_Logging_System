"""
Handles the mapping between default and custom channel names.
"""

# The default channel names in their fixed, expected order.
DEFAULT_CHANNEL_NAMES = [
    "Upstream",
    "Downstream",
    "Body",
    "Actuator",
    "Hyperbaric",
    "Backseat",
    "Spring Chamber",
    "Primary Stem Seal",
    "Secondary Stem Seal",
    "Relief Port",
    "BX Port",
    "Flow Meter",
    "Mass Spectrometer Mantissa",
    "Mass Spectrometer",
    "LVDT",
    "Torque",
    "Number Of Turns",
    "Motor Speed",
    "Ambient Temperature",
    "Body Temperature",
    "Monitor Temperature",
    "Chamber Temperature",
    "Hyperbaric Water Temperature",
    "Close",
    "Open",
    "Cycle Count",
]

def create_channel_name_mapping(custom_channel_names: list[str]) -> dict[str, str]:
    """
    Creates a mapping from default channel names to custom channel names.

    Args:
        custom_channel_names: A list of the channel names as they appear in the
            test_details.csv file. This list should be in the same order as the
            default channel names, but may be shorter for programs that do
            not use every channel.

    Returns:
        A dictionary mapping each default name to its corresponding custom name.
        e.g., {'Upstream': 'Environmental Port', 'Downstream': 'Downstream'}
    """
    mapping = {}
    for index, default_name in enumerate(DEFAULT_CHANNEL_NAMES):
        if index < len(custom_channel_names):
            mapping[default_name] = custom_channel_names[index]
        else:
            # Fall back to the default name when no custom name is provided so
            # consumers always have a usable key without raising.
            mapping[default_name] = default_name

    return mapping
