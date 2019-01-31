=======================================
Interactively defined function pickling
=======================================



Abstract
========

We propose an extension of the pickle implentation to allow for
the serialization of nested and interactively-defined functions.


.. contents::
   :depth: 1



Rationale
=========

In python, the ``pickle`` [#pickle]_ protocol, and its associated implentation, allows for
the serialization of many python objects and data structures, among which the
ubiqutous functions [#functions]_ and classes [#classes]_. The latter two
are currently pickled using their attribute path string:

.. code:: python

   >>> from os import makedirs
   >>> import pickletools
   >>> import pickle
   >>> pickletools.dis(pickle.dumps(makedirs, protocol=4))
       0: \x80 PROTO      4
       2: \x95 FRAME      19
      11: \x8c SHORT_BINUNICODE 'os'
      15: \x94 MEMOIZE    (as 0)
      16: \x8c SHORT_BINUNICODE 'makedirs'
      26: \x94 MEMOIZE    (as 1)
      27: \x93 STACK_GLOBAL
      28: \x94 MEMOIZE    (as 2)
      29: .    STOP
   highest protocol among opcodes = 4

the ``STACK_GLOBAL`` opcode, at index 27, *pushes a module.attr object on the
stack*.

As the instructions in the pickle string show, loading the pickle string
containing the function ``func`` (from the module ``mod``), triggers the
execution of the following code:

.. code:: python

   >>> from module import func


.. topic:: Note: restricting the discussion to functions

   Dynamic functions and classes serialization share the same stakes for the
   end user, as well as some implementation details in the way they will be
   pickled in the future.  However, if classess rely on functions, the opposite
   is not true. Therefore, it is reasonable to start with an *atomic*
   enhancement proposal about dynamic function pickling, and, further on,
   extend with little effort the new serialization functionalities to classes.
   From now on, the discussion in this PR will only focus on functions, and not
   classes.

The limitations of this implementation is that not all functions can be found
this way. Notable exceptions include:

* ``lambda`` functions
* functions defined in a nested scope
* functions defined in an interactive session (i.e in the ``__main__`` module)

``lambda`` and nested functions cannot be accessed as attributes to a module
(as ``pickle`` expects them to be). As for interactively defined functions,
they will be only accessible to the interepreter in which they have been
created.  Indeed, interpreters do not share their ``__main__`` module.

The latter case is particularly interesting. The data science ecosystem has
seen the eclosion of two independant phenomenon:

* Interactive sessions have been leveraged by projects such as Jupyter
  [#jupyter]_ to accelarate iterative developement and data exploration.
* As the amount of accessible data and the capacity of computer grows, a lot of
  effort has been invested to improve multi-process [#joblib]_ and multi-machine
  [#dask]_ [#rayproject]_ computing in python. Serialization constitutes a key
  step in multi-processing at it is required to communicate data between the
  different nodes.

Combining these two trends, we get an increasing need to properly serialize
interactively defined functions. Several communities [#pyspark]_ [#sklearn]_
joined forces to build and maintain a package extending ``pickle``
functionalities, under the name of ``cloudpickle`` [#cloudpickle]_. However,
its pure python implementation makes it slow to pickle large data structures,
especially ``lists`` and ``dicts``.

Proposal
========

This PR proposes an enhancement of the pickle implementation in ``cpython``,
both in ``Modules/_pickle.c`` and ``Lib/pickle.py``, in order to support the
serialization of dynamically defined and nested functions, as well as lambdas.


Implementation Details
======================

Overview
--------

The conceptual change in the serialization process is non-negligible: the
philosophy behind the current pickle implementation is to prevent foreign code
execution by only guaranteeing sucessful unpickling of already-persisteent
functions, i.e functions defined in the top level of an accessible python
module.

In this PR, the pickle string of dynamic function will instead contain an
function object reconstructor, as well as the function's current state. We can
summarize the code executed at unpickling time by:

.. code:: python


   >>> # make_skel_func (wrapper of types.Functiontype) is the reconstructor
   >>> f = make_skel_func(*args)
   >>> # fill_function updates the function's state
   >>> fill_function(f, state)

(In practice, in order to avoid circular references, some attributes f present
in the signature of ``types.functionType`` have to be unset, and instead be
given to ``fill_function``)

Changes in python internals
---------------------------

``args`` and ``state`` contain objects who are not currently picklable in
``python3.7``, namely

1. the ``function``, ``cell``, and ``code`` type
2. ``cell`` objects and ``code`` objects.

We decide to enrich the Pickler's dispatch table by enabling serialization of
all of the objects above.

* the first batch is adressed by adding the three objects to the ``builtin``
  namespace
* the latter is adressed by adding ``save_cell`` and ``save_code`` to the
  ``Pickler``'s methods

In relation with cell saving, cellobjects now have a constructor.

In addition, we modify the current ``save_function`` function to detect if a
function is dynamic, nested, or lambda. Finally, we implement a function to
serialize those types a function (``save_function_tuple``).

The global namespace of the two pickle modules are populated with extra
functions, that are called at unpickling time to re-create the dynamic
functions: ``make_skel_func`` and ``fill_function``. Other functions are
created in ``pickle`` (``walk_global_ops``). In ``_pickle``, other functions
are declared but not exposed to the python user.

Finally, several helper functions are added to collect the attributes of the.
functions necessary to recreate it (``closure``, ``globals``...)

Discussion
==========

Alternatives for python internal changes
----------------------------------------

------------------------------------------------------
Changes in the ``builtin`` namespace
------------------------------------------------------

Current implementaion and drawbacks
+++++++++++++++++++++++++++++++++++

For now, the implementation relies upon objects such as ``cell``, ``function``
and ``code`` being added to the ``builtin`` namespace. Otherwise, when trying
to pickle such types from the ``builtin`` module, an ``AttributeError`` is
raised.


.. code:: python

   >>> from types import FunctionType
   >>> FunctionType
   <class 'function'>
   >>> import pickle
   >>> pickle.dumps(FunctionType)
   Traceback (most recent call last):
     File "<stdin>", line 1, in <module>
   _pickle.PicklingError: Can't pickle <class 'function'>: attribute lookup function on builtins failed

The drawback of this solution is that there user upgrading their local python
environement may have some of their variables collude with these new additions.
(``code``, ``cell``, ``function``)


Alternative
+++++++++++

Instead, it is also possible to stick to the current ``cloudpickle``
implementation, where by adding hooks to ``save_type`` includes hookconditional
statements to spot such types and implement custom pickling techinques that to
not rely on module attribute lookup.

--------------------------
Addition of ``PyCell_New``
--------------------------

``cell`` objects now implement a public constructor. This was done to avoid
more hacky ways to create cells (by creating a function with a non empty
closure, and returning the first item of it's ``__closure__`` attribute). On
the other side, this does not like something the user should or would like
to do.

Alternative
+++++++++++
Going back to the hacky way of creating new cells.


----------------------------------
Exposing new functions to the user
----------------------------------


------------------------
``__closure__`` handling
------------------------

Current implementaion and drawbacks
+++++++++++++++++++++++++++++++++++

As mentioned above, ``make_skel_func`` and ``fill_function`` are very close to
``function.__init__`` and ``function.__setstate__``. However, the function's
closure can contain a reference to the function itself. As a result, a first
versino of the function is created in ``make_skel_func`` with an content-less
closure. Once this is done, the function is memoized, and the closure is filled
in ``fill_function``. Overall, the handling of a function's closure is done
somewhat clumsily, mostly because the current functions constructor checks the
length its ``closure`` argument to see it sizes matches the expected one. This
example shows a case of failure:

.. code:: python

   >>> import types
   >>> def f():
   ...     """ return a function with a non-empty closure"""
   ...     a = 1
   ...     def g():
   ...         return a + 1
   ...     return g
   ...
   >>> func_with_closure = f()
   >>> # trying to re-construct g with an empty closure raises an error:
   ... types.FunctionType(func_with_closure.__code__, {}, 'malformed_func',
                          None, ())  # last argument is the closure
   Traceback (most recent call last):
     File "<stdin>", line 2, in <module>
   ValueError: g requires closure of length 1, not 0

This limitation leads to some hacky workarounds, where first, a tuple of empty
``cell`` objects is created, before having their ``cell_contents`` attribute
set during ``fill_function``



Alternative
+++++++++++

The alternative would be to accept the construction of functions with malformed
closures, and to make the closure attribute writeable.


------------------------------------------------------
Implementation of the ``allow_dynamic_objects`` switch
------------------------------------------------------

This functionality allows external functions (not attributes of registered
modules) to be executed. Not everybody may want this, this functionality was
made optional, using a switch in ``load, loads, Pickler.load``.

In practice, the allow_dynamic_objects is used inside load_reduce: if the
load_reduce's callable is a function constructor (for now, _make_skel_func), a
``UnpicklingError`` is raised.


Alternative
+++++++++++

For this functionality, a new opcode sounds like a reasonable alternative.


Global variables handling
-------------------------

Another important feature of dynamic functions pickling is that the pickle
string of a serialized function should contain all global variables that the
function uses. A few challenges exist:

* The global variables a function is using are sometimes hard to catch (for
  example, modules referenced as an attribute to a package)
* At unpickling time, we must decide in which namespace the globals of the
  functions will be unpacked in.

Here is a practial issue: When serializing two functions previously defined in
a ``__main__`` module, one may assume that those two functions will coexist in
a shared main module, where they will share the same global variables. As
serialization and unserialization can happen several times in a same session,
we may encounter a case where when unpacking the globals a a function
conflicts with the current globals of the already existing shared namespace. In
this situation, should the globals of the function be overriden, or should the
globals of the current module be overriden instead?

In the current code, the priority is given to new global variables, that will
override existing ones if collision happen at unpickling time.t

.. rubric:: Footnotes

.. [#pickle] `pickle documentation <https://docs.python.org/3.7/library/pickle.html>`_
.. [#functions] `Python 3 functions documentation <https://docs.python.org/3/library/stdtypes.html#functions>`_
.. [#classes] `Python 3 classes documentation <https://docs.python.org/3/tutorial/classes.html>`_
.. [#jupyter] `Project Jupyter official website <https://jupyter.org/>`_
.. [#joblib]  `joblib official website <https://joblib.readthedocs.io/en/latest/>`_
.. [#dask] `Dask github repository <https://github.com/dask/dask>`_
.. [#rayproject] `Ray project github repository <https://github.com/ray-project/ray>`_
.. [#pyspark] `Pyspark documentation website <http://spark.apache.org/docs/2.2.0/api/python/pyspark.html>`_
.. [#sklearn]  `scikit-learn official website <https://scikit-learn.org/stable/>`_
.. [#cloudpickle] `cloudpickle github repository <https://github.com/cloudpipe/cloudpickle>`_
.. [#cloudpickle-gh-214] `cloudpickle issue #214 <https://github.com/cloudpipe/cloudpickle/issues/214>`_
.. [#cloudpickle-gh-216] `cloudpickle issue #216 <https://github.com/cloudpipe/cloudpickle/pull/216>`_
