API
===

.. automodule:: moat.dev.heat
   :members:
   :undoc-members:
   :show-inheritance:

.. automodule:: moat.dev.heat.config
   :exclude-members: UnitCfg, Backoff, ServiceCfg, EmergencyCfg, M

.. The config models only show their own docstring, not pydantic's __init__.

.. autoclass:: moat.dev.heat.config.UnitCfg
   :class-doc-from: class

.. autoclass:: moat.dev.heat.config.Backoff
   :class-doc-from: class
   :members: min, max, factor

.. autoclass:: moat.dev.heat.config.ServiceCfg
   :class-doc-from: class
   :members: host, backoff, recovery

.. autoclass:: moat.dev.heat.config.EmergencyCfg
   :class-doc-from: class

.. automodule:: moat.dev.heat.link
   :members:

.. automodule:: moat.dev.heat.state
   :members:
   :exclude-members: State, S

.. autoclass:: moat.dev.heat.state.State
   :class-doc-from: class

.. automodule:: moat.dev.heat.pid
   :members:
   :exclude-members: PIDCfg, PIDLog, PIDState

.. autoclass:: moat.dev.heat.pid.PIDCfg
   :class-doc-from: class
   :members: log, rebase_after

.. autoclass:: moat.dev.heat.pid.PIDLog
   :class-doc-from: class
   :members:

.. autoclass:: moat.dev.heat.pid.PIDState
   :class-doc-from: class

.. automodule:: moat.dev.heat.unit
   :members:

.. automodule:: moat.dev.heat.sim.plant
   :members: Plant

.. automodule:: moat.dev.heat.sim.config
   :members: PlantCfg

.. automodule:: moat.dev.heat.sim.scenario
   :members:

.. automodule:: moat.dev.heat.sim.link
   :members:

.. automodule:: moat.dev.heat.flow
   :members:
   :exclude-members: FlowCfg, FlowRequest, FlowState

.. autoclass:: moat.dev.heat.flow.FlowRequest
   :class-doc-from: class
   :members: pwm, rate, temp, min_pwm, preload, seq, to_link

.. autoclass:: moat.dev.heat.flow.FlowCfg
   :class-doc-from: class

.. autoclass:: moat.dev.heat.flow.FlowState
   :class-doc-from: class

.. automodule:: moat.dev.heat.errors
   :members:
   :exclude-members: ErrorsCfg, ErrorsState

.. autoclass:: moat.dev.heat.errors.ErrorsCfg
   :class-doc-from: class

.. autoclass:: moat.dev.heat.errors.ErrorsState
   :class-doc-from: class

.. automodule:: moat.dev.heat.pellet
   :members:
   :exclude-members: PelletCfg, PelletState

.. autoclass:: moat.dev.heat.pellet.PelletCfg
   :class-doc-from: class

.. autoclass:: moat.dev.heat.pellet.PelletState
   :class-doc-from: class

.. automodule:: moat.dev.heat.record
   :members: record, replay, read_timeline, convert_legacy, HEADER, DEFAULT_PATHS, LEGACY_PATHS
