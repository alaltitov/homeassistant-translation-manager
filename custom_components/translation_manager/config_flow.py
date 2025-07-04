"""Config flow for Translation Manager integration."""
from __future__ import annotations

import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class TranslationManagerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow handler for Translation Manager integration."""
    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle a flow initialized by the user."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(
                title="Translation Manager",
                data={}
            )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
        )
