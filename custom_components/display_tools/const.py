"""Constants for the Display Tools integration."""

DOMAIN = "display_tools"
STORAGE_KEY = f"{DOMAIN}.storage"
STORAGE_VERSION = 1
SENSOR_ENTITY_ID = "sensor.display_tools"

# Доступные категории переводов
TRANSLATION_CATEGORIES = [
    'title',
    'state', 
    'entity',
    'entity_component',
    'exceptions',
    'config',
    'config_subentries',
    'config_panel',
    'options',
    'device_automation',
    'mfa_setup',
    'system_health',
    'application_credentials',
    'issues',
    'selector',
    'services'
]

# Размеры изображений для обложек
COVER_SIZES = {
    'small': (120, 120),
    'large': (160, 160)
}