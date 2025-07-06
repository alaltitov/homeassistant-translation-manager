"""
Display Tools integration for Home Assistant.

This integration provides services to fetch translations from Home Assistant's backend
and process media player cover images for display devices.
"""
from __future__ import annotations

import logging
import os
import aiohttp
import voluptuous as vol
from PIL import Image
from io import BytesIO
import json

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store
from homeassistant.components.frontend import async_get_translations

from .const import DOMAIN, STORAGE_KEY, STORAGE_VERSION, SENSOR_ENTITY_ID, TRANSLATION_CATEGORIES, COVER_SIZES

_LOGGER = logging.getLogger(__name__)

# Schema for get_raw_translations service
GET_RAW_TRANSLATIONS_SCHEMA = vol.Schema({
    vol.Required('language'): cv.string,
})

# Schema for get_translations service
GET_TRANSLATIONS_SCHEMA = vol.Schema({
    vol.Required('language'): cv.string,
    vol.Required('category'): vol.In(TRANSLATION_CATEGORIES),
    vol.Optional('keys'): vol.All(cv.ensure_list, [cv.string]),
})

# Schema for get_translations_esphome service
GET_TRANSLATIONS_ESPHOME_SCHEMA = vol.Schema({
    vol.Required('language'): cv.string,
    vol.Required('category'): vol.In(TRANSLATION_CATEGORIES),
    vol.Optional('keys'): vol.Any(
        vol.All(cv.ensure_list, [cv.string]),
        cv.string,
        list,
        None
    ),
})

# Schema for save_media_cover service
SAVE_MEDIA_COVER_SCHEMA = vol.Schema({
    vol.Required('entity_id'): cv.entity_id,
    vol.Required('size'): vol.In(['small', 'large']),
})

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Display Tools integration from configuration."""
    return True

async def _fetch_translations_for_category(hass: HomeAssistant, language: str, category: str) -> dict:
    """
    Fetch all translations for a specific category and language.
    
    Args:
        hass: Home Assistant instance
        language (str): Language code (e.g., 'ru', 'en')
        category (str): Translation category (e.g., 'state', 'entity_component')
        
    Returns:
        dict: All translations for the category
    """
    try:
        translations = await async_get_translations(hass, language, category)
        return translations
    except Exception as e:
        _LOGGER.error(f"Error fetching translations for {language}.{category}: {e}")
        return {}

async def _filter_translations_by_keys(translations: dict, keys: list[str]) -> dict:
    """
    Filter translations dictionary by specific keys.
    
    Args:
        translations (dict): Full translations dictionary
        keys (list): List of keys to filter by
        
    Returns:
        dict: Filtered translations
    """
    if not keys:
        return translations
    
    filtered = {}
    for key in keys:
        if key in translations:
            filtered[key] = translations[key]
        else:
            filtered[key] = key  # Fallback to key itself
    
    return filtered

async def _download_and_process_cover(hass: HomeAssistant, entity_id: str, size: str) -> bool:
    """
    Download and process media player cover image.
    
    Args:
        hass: Home Assistant instance
        entity_id (str): Media player entity ID
        size (str): Size preset ('small' or 'large')
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Получаем состояние сущности
        state = hass.states.get(entity_id)
        if not state:
            _LOGGER.error(f"Entity {entity_id} not found")
            return False
        
        # Получаем URL изображения из атрибута entity_picture
        entity_picture = state.attributes.get('entity_picture')
        if not entity_picture:
            _LOGGER.error(f"No entity_picture found for {entity_id}")
            return False
        
        # Формируем полный URL если это относительный путь
        if entity_picture.startswith('/'):
            base_url = f"http://localhost:{hass.http.server_port}"
            image_url = f"{base_url}{entity_picture}"
        else:
            image_url = entity_picture
        
        # Получаем размеры для обработки
        target_size = COVER_SIZES[size]
        
        # Скачиваем изображение
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as response:
                if response.status != 200:
                    _LOGGER.error(f"Failed to download image from {image_url}, status: {response.status}")
                    return False
                
                image_data = await response.read()
        
        # Обрабатываем изображение с помощью PIL
        try:
            # Открываем изображение
            img = Image.open(BytesIO(image_data))
            
            # Конвертируем в RGB если необходимо (для JPEG)
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            
            # Изменяем размер с сохранением пропорций
            img.thumbnail(target_size, Image.Resampling.LANCZOS)
            
            # Создаем новое изображение с точными размерами и центрируем
            new_img = Image.new('RGB', target_size, (0, 0, 0))
            
            # Вычисляем позицию для центрирования
            x = (target_size[0] - img.width) // 2
            y = (target_size[1] - img.height) // 2
            
            # Вставляем изображение по центру
            new_img.paste(img, (x, y))
            
            # Создаем директорию если не существует
            output_dir = "/config/www/display_tools"
            os.makedirs(output_dir, exist_ok=True)
            
            # Сохраняем изображение
            output_path = os.path.join(output_dir, "cover.jpeg")
            new_img.save(output_path, "JPEG", quality=85)
            
            _LOGGER.info(f"Successfully saved cover image to {output_path} with size {target_size}")
            return True
            
        except Exception as e:
            _LOGGER.error(f"Error processing image: {e}")
            return False
            
    except Exception as e:
        _LOGGER.error(f"Error in _download_and_process_cover: {e}")
        return False

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Display Tools from a config entry."""
    
    # Initialize storage
    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    
    # Initialize hass.data
    hass.data[DOMAIN] = {
        "store": store,
    }
    
    # Загружаем сохраненные данные
    stored_data = await store.async_load()
    
    if stored_data:
        # Восстанавливаем сенсор с сохраненными данными
        attributes = {
            "friendly_name": "Display Tools",
            "icon": "mdi:monitor-dashboard",
            "language": stored_data.get("language", "unknown"),
            "category": stored_data.get("category", "unknown"),
            "translations_count": stored_data.get("translations_count", 0),
            "available_categories": TRANSLATION_CATEGORIES,
            "available_cover_sizes": list(COVER_SIZES.keys()),
            "requested_keys_count": stored_data.get("requested_keys_count", 0),
        }
        
        # Добавляем группированные переводы
        grouped_translations = stored_data.get("grouped_translations", {})
        for component, component_translations in grouped_translations.items():
            # Сохраняем как JSON строку для ESPHome
            attributes[component] = json.dumps(component_translations, ensure_ascii=False)
        
        hass.states.async_set(
            SENSOR_ENTITY_ID,
            stored_data.get("language", "empty"),
            attributes
        )
        
        _LOGGER.info(f"Restored Display Tools sensor with {len(grouped_translations)} component groups")
    else:
        # Создаем начальное состояние сенсора (пустое)
        hass.states.async_set(
            SENSOR_ENTITY_ID,
            "empty",
            {
                "friendly_name": "Display Tools",
                "icon": "mdi:monitor-dashboard",
                "available_categories": TRANSLATION_CATEGORIES,
                "available_cover_sizes": list(COVER_SIZES.keys()),
            }
        )
    
    async def handle_get_raw_translations(call: ServiceCall) -> ServiceResponse:
        """Handle the get_raw_translations service call - returns ALL translations for language."""
        language = call.data.get("language")
        
        try:
            result = {}
            
            # Получаем переводы для всех категорий
            for category in TRANSLATION_CATEGORIES:
                translations = await _fetch_translations_for_category(hass, language, category)
                if translations:
                    result[category] = translations
            
            return {
                "language": language,
                "categories": result,
                "total_categories": len(result)
            }
            
        except Exception as e:
            _LOGGER.error(f"Error in get_raw_translations service: {e}")
            return {
                "language": language,
                "categories": {},
                "error": str(e)
            }
    
    async def handle_get_translations(call: ServiceCall) -> ServiceResponse:
        """Handle the get_translations service call - returns translations for specific category."""
        language = call.data.get("language")
        category = call.data.get("category")
        keys = call.data.get("keys")
        
        try:
            # Получаем все переводы для категории
            translations = await _fetch_translations_for_category(hass, language, category)
            
            # Фильтруем по ключам если указаны
            if keys:
                translations = await _filter_translations_by_keys(translations, keys)
            
            return {
                "language": language,
                "category": category,
                "translations": translations,
                "total_translations": len(translations)
            }
            
        except Exception as e:
            _LOGGER.error(f"Error in get_translations service: {e}")
            return {
                "language": language,
                "category": category,
                "translations": {},
                "error": str(e)
            }
    
    async def handle_get_translations_esphome(call: ServiceCall) -> None:
        """Handle the get_translations_esphome service call - updates sensor for ESPHome."""
        language = call.data.get("language")
        category = call.data.get("category")
        keys_raw = call.data.get("keys")
        
        # Обработка keys с учетом специфики ESPHome
        keys = None
        if keys_raw is not None:
            try:
                if isinstance(keys_raw, list) and len(keys_raw) == 1:
                    # ESPHome передает список из одного элемента
                    single_item = keys_raw[0]
                    
                    if isinstance(single_item, str):
                        # Попробуйте сначала JSON
                        try:
                            keys = json.loads(single_item)
                        except json.JSONDecodeError:
                            # Если не JSON, разделите по запятым и очистите
                            keys = [k.strip() for k in single_item.split(',') if k.strip()]
                    else:
                        keys = [str(single_item)]
                        
                elif isinstance(keys_raw, list):
                    # Обычный список
                    keys = keys_raw
                    
                elif isinstance(keys_raw, str):
                    # Строка напрямую
                    try:
                        keys = json.loads(keys_raw)
                    except json.JSONDecodeError:
                        keys = [k.strip() for k in keys_raw.split(',') if k.strip()]
                        
                elif hasattr(keys_raw, '__iter__') and not isinstance(keys_raw, (str, bytes)):
                    # Итерируемый объект
                    keys = list(keys_raw)
                else:
                    keys = [str(keys_raw)]
                    
            except Exception as e:
                _LOGGER.error(f"Error processing keys: {e}")
                keys = None
        
        try:
            # Получаем все переводы для категории
            translations = await _fetch_translations_for_category(hass, language, category)
            
            # Фильтруем по ключам если указаны
            if keys:
                translations = await _filter_translations_by_keys(translations, keys)
            
            # Группируем переводы по компонентам
            grouped_translations = {}
            for key, value in translations.items():
                # Извлекаем компонент из ключа (например, vacuum из component.vacuum.entity_component._.state.cleaning)
                parts = key.split('.')
                if len(parts) >= 2 and parts[0] == 'component':
                    component = parts[1]  # vacuum, cover, climate, weather
                    # Извлекаем последнюю часть как ключ (cleaning, opening, heating, etc.)
                    final_key = parts[-1]
                    
                    if component not in grouped_translations:
                        grouped_translations[component] = {}
                    grouped_translations[component][final_key] = value
            
            # Получаем текущие данные из хранилища
            store = hass.data[DOMAIN]["store"]
            stored_data = await store.async_load() or {}
            
            # Обновляем сохраненные данные
            stored_data.update({
                "language": language,
                "category": category,
                "grouped_translations": grouped_translations,
                "translations_count": len(translations),
                "requested_keys_count": len(keys) if keys else 0,
            })
            
            # Сохраняем в хранилище
            await store.async_save(stored_data)
            
            # Создаем атрибуты для сенсора
            attributes = {
                "friendly_name": "Display Tools",
                "icon": "mdi:monitor-dashboard",
                "language": language,
                "category": category,
                "translations_count": len(translations),
                "available_categories": TRANSLATION_CATEGORIES,
                "available_cover_sizes": list(COVER_SIZES.keys()),
                "requested_keys_count": len(keys) if keys else 0,
            }
            
            # Добавляем группированные переводы как отдельные атрибуты (JSON строки)
            for component, component_translations in grouped_translations.items():
                attributes[component] = json.dumps(component_translations, ensure_ascii=False)
            
            # Обновляем сенсор
            hass.states.async_set(
                SENSOR_ENTITY_ID,
                language,  # Состояние = активный язык
                attributes
            )
            
            _LOGGER.info(f"Updated Display Tools sensor with {len(grouped_translations)} component groups for language {language}")
            
        except Exception as e:
            _LOGGER.error(f"Error in get_translations_esphome service: {e}")
            
            # В случае ошибки устанавливаем состояние error
            hass.states.async_set(
                SENSOR_ENTITY_ID,
                "error",
                {
                    "friendly_name": "Display Tools",
                    "icon": "mdi:monitor-off",
                    "error": str(e),
                    "available_categories": TRANSLATION_CATEGORIES,
                    "available_cover_sizes": list(COVER_SIZES.keys()),
                }
            )
    
    async def handle_save_media_cover(call: ServiceCall) -> None:
        """Handle the save_media_cover service call - downloads and processes media cover."""
        entity_id = call.data.get("entity_id")
        size = call.data.get("size")
        
        _LOGGER.info(f"Processing cover for {entity_id} with size {size}")
        
        try:
            success = await _download_and_process_cover(hass, entity_id, size)
            
            if success:
                _LOGGER.info(f"Successfully processed cover for {entity_id}")
            else:
                _LOGGER.error(f"Failed to process cover for {entity_id}")
                
        except Exception as e:
            _LOGGER.error(f"Error in save_media_cover service: {e}")
    
    # Register services
    hass.services.async_register(
        DOMAIN,
        "get_raw_translations",
        handle_get_raw_translations,
        schema=GET_RAW_TRANSLATIONS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    
    hass.services.async_register(
        DOMAIN,
        "get_translations",
        handle_get_translations,
        schema=GET_TRANSLATIONS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    
    hass.services.async_register(
        DOMAIN,
        "get_translations_esphome",
        handle_get_translations_esphome,
        schema=GET_TRANSLATIONS_ESPHOME_SCHEMA,
    )
    
    hass.services.async_register(
        DOMAIN,
        "save_media_cover",
        handle_save_media_cover,
        schema=SAVE_MEDIA_COVER_SCHEMA,
    )
    
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    
    # Remove services
    hass.services.async_remove(DOMAIN, "get_raw_translations")
    hass.services.async_remove(DOMAIN, "get_translations")
    hass.services.async_remove(DOMAIN, "get_translations_esphome")
    hass.services.async_remove(DOMAIN, "save_media_cover")
    
    # Remove sensor
    hass.states.async_remove(SENSOR_ENTITY_ID)
    
    # Clean up data
    hass.data.pop(DOMAIN, None)
    
    return True

