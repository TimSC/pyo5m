#include <Python.h>

#define INTERNAL_BUFF_SIZE 16

static PyObject *
EncodeVarint(PyObject *self, PyObject *args)
{
    unsigned PY_LONG_LONG val = 0;
	char buff[INTERNAL_BUFF_SIZE] = "";
	unsigned char more = 1;
	unsigned int cursor = 0;

    if (!PyArg_ParseTuple(args, "K", &val))
        return NULL;
	
	while (more) {
		unsigned char sevenBits = val & 0x7f;
		val = val >> 7;
		more = val != 0;
		if(cursor < INTERNAL_BUFF_SIZE) {
			buff[cursor] = (more << 7) + sevenBits;
			cursor ++;	
		}
		else {
			PyErr_SetString(PyExc_RuntimeError, "Internal buffer overflow while encoding varint");
			return NULL;
		}
	}

    return PyString_FromStringAndSize(buff, cursor);
}

static PyObject *
EncodeZigzag(PyObject *self, PyObject *args)
{
    PY_LONG_LONG val = 0;
	char buff[INTERNAL_BUFF_SIZE] = "";
	unsigned char more = 1;
	unsigned int cursor = 0;
	unsigned PY_LONG_LONG zz = 0;

    if (!PyArg_ParseTuple(args, "L", &val))
        return NULL;

	zz = (val << 1) ^ (val >> (sizeof(PY_LONG_LONG)*8-1));

	while (more) {
		unsigned char sevenBits = zz & 0x7f;
		zz = zz >> 7;
		more = zz != 0;
		if(cursor < INTERNAL_BUFF_SIZE) {
			buff[cursor] = (more << 7) + sevenBits;
			cursor ++;	
		}
		else {
			PyErr_SetString(PyExc_RuntimeError, "Internal buffer overflow while encoding zigzag");
			return NULL;
		}
	}

    return PyString_FromStringAndSize(buff, cursor);
}

static PyMethodDef SpamMethods[] = {
    {"EncodeVarint",  EncodeVarint, METH_VARARGS, "Varint encode an unsigned number."},
	{"EncodeZigzag",  EncodeZigzag, METH_VARARGS, "Zigzag encode a signed number."},
    {NULL, NULL, 0, NULL}
};

PyMODINIT_FUNC
initEncoding(void)
{
    (void) Py_InitModule("Encoding", SpamMethods);
}

