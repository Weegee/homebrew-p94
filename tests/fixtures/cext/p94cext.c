#include <Python.h>
#include <stdio.h>

static PyObject *p94cext_add(PyObject *self, PyObject *args) {
    long a, b;
    if (!PyArg_ParseTuple(args, "ll", &a, &b)) {
        return NULL;
    }
    return PyLong_FromLong(a + b);
}

static PyMethodDef methods[] = {
    {"add", p94cext_add, METH_VARARGS, "Add two integers."},
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef module = {PyModuleDef_HEAD_INIT, "p94cext", NULL, -1, methods};

PyMODINIT_FUNC PyInit_p94cext(void) { return PyModule_Create(&module); }
