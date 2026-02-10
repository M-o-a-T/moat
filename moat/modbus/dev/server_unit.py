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
        self._client_unit = None  # The client unit for forwarding
        self._forward = False  # Whether to forward unslotted registers

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
        # Track if we found any unslotted registers
        has_unslotted = False

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

            # Find all slots involved and check for unslotted registers
            for offset in range(address, address + count):
                slot = self._slot_cache.get((reg_type_key, offset))
                if slot is not None:
                    slots_to_check.add(slot)
                else:
                    # Register has no slot - needs forwarding if forward=true
                    has_unslotted = True

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
                    else:
                        try:
                            reg = self.store[reg_type_key].get(offset + 1)
                            if reg is not None:
                                has_unslotted = True
                        except (KeyError, AttributeError):
                            pass

        # Read unslotted registers on-demand by forwarding to client
        if has_unslotted and self._forward and self._client_unit is not None:
            logger.debug(
                "Server request forwarding to client for unslotted registers",
            )
            try:
                # Forward the request to the client host
                response = await self._client_unit.host.execute(request)
                # Decode the response into unslotted registers in our datastore
                if hasattr(response, "registers"):
                    from moat.modbus.types import IntValue  # noqa: PLC0415

                    # For register reads, update/create unslotted registers
                    address = request.address
                    regs = response.registers

                    for i, val in enumerate(regs):
                        offset = address + i
                        has_slot = self._slot_cache.get((reg_type_key, offset))

                        if not has_slot:
                            # Register has no slot - update or create it
                            # Note: DataBlock dict keys are 0-indexed (Modbus addresses)
                            try:
                                server_reg = self.store[reg_type_key].get(offset)
                                if server_reg is not None:
                                    # Register exists, update it
                                    server_reg.decode([val])
                                else:
                                    # Register doesn't exist, create a temporary one
                                    temp_reg = IntValue()
                                    temp_reg.decode([val])
                                    self.store[reg_type_key][offset] = temp_reg
                            except (KeyError, AttributeError):
                                # Create the register type store if it doesn't exist
                                if reg_type_key not in self.store:
                                    from moat.modbus.types import DataBlock  # noqa: PLC0415

                                    self.store[reg_type_key] = DataBlock()
                                # Now add the register
                                temp_reg = IntValue()
                                temp_reg.decode([val])
                                self.store[reg_type_key][offset] = temp_reg
            except Exception as exc:
                logger.warning("Failed to forward request to client: %r", exc)

        # Check and refresh stale data for each slot
        for slot in slots_to_check:
            async with slot.read_lock:
                # Determine if we should read:
                # 1. Slot has no read_delay: always read on-demand
                # 2. Slot has age parameter: check if stale
                # 3. Otherwise: rely on periodic reads only
                should_read = False

                if slot.read_delay is None:
                    # On-demand read (no periodic task)
                    should_read = True
                    logger.debug(
                        "Server request triggered on-demand read for %s (no read_delay)",
                        slot,
                    )
                elif slot.age is not None:
                    # Age-based refresh for periodically-read slots
                    current_time = anyio.current_time()
                    if slot.t_read is None or (current_time - slot.t_read) >= slot.age:
                        should_read = True
                        logger.debug(
                            "Server request triggered refresh for %s (age %.1fs >= %.1fs)",
                            slot,
                            current_time - slot.t_read if slot.t_read else float("inf"),
                            slot.age,
                        )

                if should_read:
                    slot.t_read = anyio.current_time()
                    await slot.getValues()

        # Now process the request normally
        return await request.update_datastore(self)
