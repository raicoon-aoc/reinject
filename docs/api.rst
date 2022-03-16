API Reference
=============

Core API
--------

.. autofunction:: reinject.register_resource
.. autofunction:: reinject.resource_scope
.. autofunction:: reinject.get_current_scope


Support Classes
---------------

.. autoclass:: reinject.Resource
   :members:


.. autoclass:: reinject.SetupTeardownResource
   :members:


.. autoclass:: reinject.Scope
    :members: __getitem__, ensure_resource, add_resource
