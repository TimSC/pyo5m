#include <Python.h>

#define INTERNAL_BUFF_SIZE 128

static PyObject *
EncodeVarint(PyObject *self, PyObject *args)
{
    unsigned PY_LONG_LONG val = 0;
	char buff[INTERNAL_BUFF_SIZE] = "";

    if (!PyArg_ParseTuple(args, "K", &val))
        return NULL;
	
	unsigned char more = 1;
	unsigned int cursor = 0;
	while (more) {
		unsigned char sevenBits = val & 0x7f;
		val = val >> 7;
		more = val > 0;
		if(cursor < INTERNAL_BUFF_SIZE) {
			buff[cursor] = (more << 7) + sevenBits;
			cursor ++;	
		}
		else {
			PyErr_SetString(PyExc_TypeError, "Internal buffer overflow while encoding varint");
			return NULL;
		}
	}

    return PyString_FromStringAndSize(buff, cursor);
}

static PyMethodDef SpamMethods[] = {
    {"EncodeVarint",  EncodeVarint, METH_VARARGS,
     "Encode a varint."},
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

PyMODINIT_FUNC
initEncoding(void)
{
    (void) Py_InitModule("Encoding", SpamMethods);
}

