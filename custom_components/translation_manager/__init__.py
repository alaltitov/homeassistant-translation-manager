"""
Translation Manager integration for Home Assistant.

This integration provides a service to fetch translations from Home Assistant's backend
and stores them in a sensor for easy access by ESPHome and other components.
"""
from __future__ import annotations

import logging
import voluptuous as vol
import json

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.typing import ConfigType
from homeassistant.components import websocket_api
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_KEY, STORAGE_VERSION, SENSOR_ENTITY_ID

_LOGGER = logging.getLogger(__name__)

# Schema for get_translation service
GET_TRANSLATION_SCHEMA = vol.Schema({
    vol.Required('language'): cv.string,
    vol.Required('key'): cv.string,
})

# Schema for bulk_get_translations service
BULK_GET_TRANSLATIONS_SCHEMA = vol.Schema({
    vol.Required('language'): cv.string,
    vol.Required('keys'): vol.All(cv.ensure_list, [cv.string]),
})

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Translation Manager integration from configuration."""
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Translation Manager from a config entry."""
    
    # Initialize storage
    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    stored_data = await store.async_load() or {"translations": {}}
    
    # Initialize hass.data
    hass.data[DOMAIN] = {
        "store": store,
        "translations": stored_data.get("translations", {}),
    }
    
    # Create initial sensor state
    await _update_sensor_state(hass)
    
    async def _fetch_translations_via_websocket(language: str) -> dict:
        """
        Fetch translations using WebSocket API.
        
        Args:
            language (str): Language code (e.g., 'ru', 'en')
            
        Returns:
            dict: Translation data for entity_component category
        """
        try:
            # Create WebSocket message
            message = {
                'type': 'frontend/get_translations',
                'category': 'entity_component',
                'language': language
            }
            
            # Use internal WebSocket API
            result = await hass.async_add_executor_job(
                _sync_websocket_request, hass, message
            )
            
            if result and 'resources' in result:
                return result['resources']
            else:
                _LOGGER.warning(f"No resources found for language {language}")
                return {}
                
        except Exception as e:
            _LOGGER.error(f"Error fetching translations via WebSocket: {e}")
            return {}
    
    def _sync_websocket_request(hass: HomeAssistant, message: dict) -> dict:
        """
        Synchronous WebSocket request helper.
        
        This is a workaround to make WebSocket requests from async context.
        """
        try:
            # Import here to avoid circular imports
            from homeassistant.components.frontend import async_get_translations
            
            # Use the frontend's translation function
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                result = loop.run_until_complete(
                    async_get_translations(
                        hass, 
                        message['language'], 
                        message['category']
                    )
                )
                return {'resources': result}
            finally:
                loop.close()
                
        except Exception as e:
            _LOGGER.error(f"Error in sync WebSocket request: {e}")
            return {}
    
    async def handle_get_translation(call: ServiceCall) -> None:
        """Handle the get_translation service call."""
        language = call.data.get("language")
        key = call.data.get("key")
        
        _LOGGER.debug(f"Getting translation for key '{key}' in language '{language}'")
        
        try:
            # Check if we already have translations for this language
            current_translations = hass.data[DOMAIN]["translations"]
            
            if language not in current_translations:
                # Fetch translations for this language
                _LOGGER.info(f"Fetching translations for language: {language}")
                translations = await _fetch_translations_via_websocket(language)
                
                if translations:
                    current_translations[language] = translations
                    hass.data[DOMAIN]["translations"] = current_translations
                    
                    # Save to storage
                    await hass.data[DOMAIN]["store"].async_save({
                        "translations": current_translations
                    })
                else:
                    _LOGGER.error(f"Failed to fetch translations for language: {language}")
                    return
            
            # Get the specific translation
            lang_translations = current_translations.get(language, {})
            translation_value = lang_translations.get(key, key)  # Fallback to key if not found
            
            _LOGGER.info(f"Translation found: {language}.{key} = '{translation_value}'")
            
            # Update sensor state
            await _update_sensor_state(hass)
            
        except Exception as e:
            _LOGGER.error(f"Error getting translation for {language}.{key}: {e}")
    
    async def handle_bulk_get_translations(call: ServiceCall) -> None:
        """Handle the bulk_get_translations service call."""
        language = call.data.get("language")
        keys = call.data.get("keys", [])
        
        _LOGGER.debug(f"Getting bulk translations for {len(keys)} keys in language '{language}'")
        
        # Process each key
        for key in keys:
            await handle_get_translation(ServiceCall(
                DOMAIN, 
                "get_translation", 
                {"language": language, "key": key}
            ))
    
    async def handle_clear_translations(call: ServiceCall) -> None:
        """Clear all translations."""
        hass.data[DOMAIN]["translations"] = {}
        
        # Save to storage
        await hass.data[DOMAIN]["store"].async_save({
            "translations": {}
        })
        
        # Update sensor
        await _update_sensor_state(hass)
        
        _LOGGER.info("Cleared all translations")
    
    async def _update_sensor_state(hass: HomeAssistant) -> None:
        """Update the sensor state with current translations."""
        translations = hass.data[DOMAIN]["translations"]
        
        # Calculate statistics
        total_keys = sum(len(lang_data) for lang_data in translations.values())
        supported_languages = list(translations.keys())
        
        # Create attributes with language data
        attributes = {
            "friendly_name": "Translation Manager",
            "icon": "mdi:translate",
            "translations_count": total_keys,
            "supported_languages": supported_languages,
        }
        
        # Add each language as an attribute with its translations
        for language, lang_translations in translations.items():
            # Convert to list of [key, value] pairs for easier access in ESPHome
            translation_list = []
            for key, value in lang_translations.items():
                translation_list.append([key, value])
            
            attributes[language] = translation_list
        
        # Set sensor state
        hass.states.async_set(
            SENSOR_ENTITY_ID,
            "ready" if translations else "empty",
            attributes
        )
    
    # Register services
    hass.services.async_register(
        DOMAIN,
        "get_translation",
        handle_get_translation,
        schema=GET_TRANSLATION_SCHEMA,
    )
    
    hass.services.async_register(
        DOMAIN,
        "bulk_get_translations",
        handle_bulk_get_translations,
        schema=BULK_GET_TRANSLATIONS_SCHEMA,
    )
    
    hass.services.async_register(
        DOMAIN,
        "clear_translations",
        handle_clear_translations,
    )
    
    _LOGGER.info("Translation Manager integration setup completed")
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Remove services
    hass.services.async_remove(DOMAIN, "get_translation")
    hass.services.async_remove(DOMAIN, "bulk_get_translations")
    hass.services.async_remove(DOMAIN, "clear_translations")
    
    # Remove sensor
    hass.states.async_remove(SENSOR_ENTITY_ID)
    
    # Clean up data
    hass.data.pop(DOMAIN, None)
    
    return True
