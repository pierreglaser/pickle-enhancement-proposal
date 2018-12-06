# As I am currently submitting a pickle enhancment proposal

# here are a couple function that will be of use during differents parts of the
# notebook
import types


def _make_empty_cell():
    if False:
        # trick the compiler into creating an empty cell in our lambda
        cell = None
        raise AssertionError('this route should not be executed')

    return (lambda: cell).__closure__[0]


def get_closure_values(f):
    closure_values = [cell.cell_contents for cell in f.__closure__]
    return closure_values


def make_cell(value):
    def g():
        return value
    return g.__closure__[0]


def make_pow(base):
    def power(exponent):
        return base**exponent
    return power


five_exp = make_pow(5)


if __name__ == "__main__":
    # re-create a function with the same closure, altough local_variable is not
    # available in the global namespace

    # in a new process, creating a new function using another
    # function's __code__ object requires the other arguments of
    # `types.FunctionType` to be compatible withthe function's __code__

    try:
        # the last argument of types.FunctionType is closure.
        # Here, we give an empty tuple for the function's closure, whereas
        # function_with_a_closure.__code__.co_freevars (referencing variables
        # in an enclosed scope)
        my_new_function = types.FunctionType(five_exp.__code__,
                                             {}, None, None, ())
    except ValueError as e:
        print('wrong closure argument: {}'.format(e))

    # instead, one has to create first a new, cell referencing a the variable
    # that is used by function_with_a_closure.
    # cells = [_make_empty_cell() for _ in function_with_a_closure.__closure__]
    cell_contents = get_closure_values(five_exp)

    # my_new_function = types.FunctionType(function_with_a_closure.__code__,
    # {}, None, None, tuple(cells))

    # and finally, set the values of the cells:
    # for cell, content in zip(cells, cell_contents):
    #     cell.cell_contents = content

    cool_cells = [make_cell(v) for v in cell_contents]
    cool_cells_func = types.FunctionType(five_exp.__code__, {},
                                         None, None, tuple(cool_cells))

    # so the question here is: why does cloudpickle have a very complex
    # behavior regarding closure setting?
    # Well, things get complicated when the closure includes a recursive
    # reference to the function itself
    def make_pow_recursive(base):
        def power_recursive(exponent):
            return base*power_recursive(exponent-1)
        return power_recursive

    # this code would actually return an error in early versions on python (see
    # PEP 227), when not all names bound in enclosing scopes were visible
    five_exp_recursive = make_pow_recursive(5)
    closure_values = get_closure_values(five_exp_recursive)
    assert five_exp in closure_values

    # a naive attempt to pickle a dynamic function such as:

    import pickle
    # calling the python object for better debugging sugar
    pickler = pickle._Pickler()

    # TODO: explain the problem with pickling type.FunctionType?
    pickler.save(type.FunctionType)
    state = (
            five_exp_recursive.__code__,
            {},
            five_exp_recursive.__name__,
            None,
            get_closure_values(five_exp_recursive)
            )
    pickler.save(state)
    pickler.write(pickle.REDUCE)

    # would not work:
    # when trying to save the closure values, the Pickler object would get
    # caught in an infinite, loop, re-calling the same block of code over and
    # over again.

    # This problem is pretty common, and the solution is to memoize any
    # self-referencing object. Basically, create a non-recursive, (so
    # partial) version of the object, and save it. Once it is saved, calling
    # Pickler.memoize(object) will make the Pickler write memo.get(id(obj))
    # instead of save(obj) in the pickle string. No more infinite cycle.
    # At Unpickling time, once the partial object is created, it will be
    # referenced as obj, and put in the unpickler memo. Each time
    # memo.get(id(obj)) will be read in the pickle string, the partial object
    # will be put into the stack. Of course, the partial object passed by
    # reference and not by value, the reconstructed verion of it remains
    # self-referencing.

    # as a result, doing someting such as

    def fill_closure(func, closure_values):
        for cell, value in zip(func.__closure__, closure_values):
            cell.cell_contents = value

    import pickle
    pickler = pickle._Pickler()

    closure_values = get_closure_values(five_exp_recursive)
    state = (
            five_exp_recursive.__code__,
            {},
            five_exp_recursive.__name__,
            None,
            None
            )

    pickler.save(fill_closure)

    # start writing the args of fill_closure as a length-2 tuple
    pickler.write(pickle.MARK)

    pickler.save(type.FunctionType)
    pickler.save(state)

    # call types.FunctionType(state) and add it on the stack (1st element of
    # the tuple we are writing)
    pickler.write(pickle.REDUCE)

    # write the second arg of fill_closure
    pickler.write(closure_values)

    # pack the two elements into a tuple
    pickler.write(pickle.TUPLE)

    # call fill_closure(*args)
    pickler.write(pickle.REDUCE)
    #
    #

    # seems like it would work right? right? In python 3, yes, but sadly in
    # python2 it won't. Indeed, until the PEP 3104 rebinding of enclosing scope
    # names was not allowed. Closure objects represent variables in an
    # enclosing scope, so writing to them would have broken this policy, thus
    # cell_contents was not writeable

    # In cloudpickle, overcoming this lead to some very complex workarounds,
    # including empty cell creations with further indirect modification in
    # intermediate function. I won't get into this level of detail. But this is
    # an extreme example of how painful retrocompatibility can be.
