"""
Server UnitContext with age-based refresh support.
"""

from __future__ import annotations

import anyio
import logging

from moat.modbus.server import UnitContext

logger = logging.getLogger(__name__)


class ServerUnitContext(UnitContext):
    """
    UnitContext that checks data age before serving values.

    When a read request comes in, this checks if any of the requested
    registers have an age parameter and are stale. If so, it triggers
    a re-read from the client before serving the values.
    """

    def __init__(self, server=None, unit=None):
        super().__init__(server, unit)
        self._slot_cache = {}  # Cache of register -> slot mappings

    def add_mapping(self, register, reg_type_key, slot):
        """Track which slot a register belongs to for age checking.

        Args:
            register: The register address (single register, even for multi-register values)
            reg_type_key: The register type key ('h', 'i', 'c', 'd')
            slot: The Slot object associated with this register
        """
        self._slot_cache[(reg_type_key, register)] = slot

    async def process_request(self, request):
        """Process a request, checking for stale data first."""
        function_code = request.function_code

        # Collect slots that need refreshing
        slots_to_check = set()

        # Handle read operations
        if function_code in (1, 2, 3, 4):  # Read Coils, Discrete, Holding, Input
            # Determine which type of register
            if function_code == 1:  # Read Coils
                reg_type_key = "c"
            elif function_code == 2:  # Read Discrete Inputs
                reg_type_key = "d"
            elif function_code == 3:  # Read Holding Registers
                reg_type_key = "h"
            else:  # function_code == 4  # Read Input Registers
                reg_type_key = "i"

            # Get the address range being requested
            address = request.address
            count = getattr(request, "count", 1)

            # Find all slots involved in this request
            for offset in range(address, address + count):
                slot = self._slot_cache.get((reg_type_key, offset))
                if slot is not None:
                    slots_to_check.add(slot)

        elif function_code == 23:  # Read/Write Multiple Registers
            # This function code reads from one range and writes to another
            read_address = getattr(request, "read_address", None)
            read_count = getattr(request, "read_count", 0)

            if read_address is not None and read_count > 0:
                reg_type_key = "h"  # Always holding registers for FC23
                for offset in range(read_address, read_address + read_count):
                    slot = self._slot_cache.get((reg_type_key, offset))
                    if slot is not None:
                        slots_to_check.add(slot)

        # Check and refresh stale data for each slot
        for slot in slots_to_check:
            if slot.age is not None:
                async with slot.read_lock:
                    current_time = anyio.current_time()
                    if slot.t_read is None or (current_time - slot.t_read) >= slot.age:
                        logger.debug(
                            "Server request triggered refresh for %s (age %.1fs >= %.1fs)",
                            slot,
                            current_time - slot.t_read if slot.t_read else float("inf"),
                            slot.age,
                        )
                        slot.t_read = current_time
                        await slot.getValues()

        # Now process the request normally
        return await request.update_datastore(self)
