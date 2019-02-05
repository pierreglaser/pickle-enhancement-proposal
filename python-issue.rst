Add pickler hook to allow the user to customize the serialization of user
defined functions and types.

Pickler objects provide a dispatch_table attribute, where the user can specify
custom saving functions depending on the object-to-be-saved type. However, for
performance purposes, this table is predated (in the C implementation only) by
a hardcoded switch that will take care of the saving for many built-in types,
without a lookup in the dispatch_table.

Especially, it is not possible to define custom saving methods for functions
and classes, although the current default (save_global, that saves an object
using its module attribute path) is likely to fail at pickling or unpickling
time in many cases.

The aforementioned failures exist on purpose in the standard library (as a way
to allow for the serialization of functions accessible from non-dynamic (*)
modules only). However, there exist cases where serializing functions from
dynamic modules matter. These cases are currently handled thanks the
cloudpickle module (https://github.com/cloudpipe/cloudpickle), that is used by
many distributed data-science frameworks such as pyspark, ray and dask. For the
reasons explained above, cloudpickle's Pickler subclass derives from the python
Pickler class instead of its C class, which severely harms its performance. 

While prototyping with Antoine Pitrou, we came to the conclusion that a hook
could be added to the C Pickler class, in which an optional user-defined
callback would be invoked (if defined) when saving functions and classes
instead of the traditional save_global. Here is a patch so that we can have
something concrete of which to discuss.

(*) dynamic module are modules that cannot be imported by name as traditional
    python file backed module. Examples include the __main__ module that can be
    populated dynamically by running a script or by a, user writing code in a
    python shell / jupyter notebook.
