#include <Python.h>
#define INTERNAL_BUFF_SIZE 16

// ************* Encode ***************

static PyObject *EncodeVarint(PyObject *self, PyObject *args)
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

#if PY_MAJOR_VERSION >= 3
	return PyBytes_FromStringAndSize(buff, cursor);
#else
	return PyString_FromStringAndSize(buff, cursor);
#endif
}

static PyObject *EncodeZigzag(PyObject *self, PyObject *args)
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
#if PY_MAJOR_VERSION >= 3
	return PyBytes_FromStringAndSize(buff, cursor);
#else
	return PyString_FromStringAndSize(buff, cursor);
#endif
}

// ************* Decode ***************

static PyObject *DecodeVarint(PyObject *self, PyObject *args)
{
	PyObject *outObj = NULL;
	if (!PyArg_ParseTuple(args, "O", &outObj))
		return NULL;
	
	PyObject *readMethod = PyObject_GetAttrString(outObj, "read");
	if(readMethod == NULL) {
		Py_DECREF(outObj);
		PyErr_SetString(PyExc_TypeError, "Input object does not have read method");
		return NULL;
	}

	if(!PyCallable_Check(readMethod)) {
		Py_DECREF(outObj);
		PyErr_SetString(PyExc_TypeError, "Input object read method not callable");
		return NULL;
	}

	PyObject *readLenArgListObj = Py_BuildValue("(i)", 1);

	unsigned char contin = 1;
	unsigned PY_LONG_LONG offset = 0;
	unsigned PY_LONG_LONG total = 0;
	while (contin) {
		PyObject *readResponse = PyObject_Call(readMethod, readLenArgListObj, NULL);

#if PY_MAJOR_VERSION >= 3
		if(!PyBytes_Check(readResponse)) {
			Py_DECREF(outObj);
			Py_DECREF(readResponse);
			PyErr_SetString(PyExc_RuntimeError, "Read result has unexpected type");
			return NULL;
		}

		Py_ssize_t rawBuffSize = PyBytes_GET_SIZE(readResponse);
		const char* rawBuff = PyBytes_AS_STRING(readResponse);

		if(rawBuff == NULL || rawBuffSize < 1) {
			Py_DECREF(outObj);
			Py_DECREF(readResponse);
			PyErr_SetString(PyExc_RuntimeError, "Read result has unexpected length");
			return NULL;
		}
#else
		if(!PyString_Check(readResponse)) {
			Py_DECREF(outObj);
			Py_DECREF(readResponse);
			PyErr_SetString(PyExc_RuntimeError, "Read result has unexpected type");
			return NULL;
		}

		Py_ssize_t rawBuffSize = PyString_GET_SIZE(readResponse);
		const char* rawBuff = PyString_AS_STRING(readResponse);

		if(rawBuff == NULL || rawBuffSize < 1) {
			Py_DECREF(outObj);
			Py_DECREF(readResponse);
			PyErr_SetString(PyExc_RuntimeError, "Read result has unexpected length");
			return NULL;
		}
#endif

		unsigned PY_LONG_LONG val = *(unsigned char *)(rawBuff);
		contin = (val & 0x80) != 0;
		total += (val & 0x7f) << offset;
		offset += 7;

		Py_DECREF(readResponse);
	}

	PyObject *ret = PyLong_FromUnsignedLongLong(total);
	Py_DECREF(readLenArgListObj);
	Py_DECREF(outObj);

	return ret;
}

static PyObject *DecodeZigzag(PyObject *self, PyObject *args)
{

	PyObject *outObj = NULL;
	if (!PyArg_ParseTuple(args, "O", &outObj))
		return NULL;
	
	PyObject *readMethod = PyObject_GetAttrString(outObj, "read");
	if(readMethod == NULL) {
		Py_DECREF(outObj);
		PyErr_SetString(PyExc_TypeError, "Input object does not have read method");
		return NULL;
	}

	if(!PyCallable_Check(readMethod)) {
		Py_DECREF(outObj);
		PyErr_SetString(PyExc_TypeError, "Input object read method not callable");
		return NULL;
	}

	PyObject *readLenArgListObj = Py_BuildValue("(i)", 1);

	unsigned char contin = 1;
	unsigned PY_LONG_LONG offset = 0;
	unsigned PY_LONG_LONG total = 0;
	while (contin) {
		PyObject *readResponse = PyObject_Call(readMethod, readLenArgListObj, NULL);

#if PY_MAJOR_VERSION >= 3
		if(!PyBytes_Check(readResponse)) {
			Py_DECREF(outObj);
			Py_DECREF(readResponse);
			PyErr_SetString(PyExc_RuntimeError, "Read result has unexpected type");
			return NULL;
		}

		Py_ssize_t rawBuffSize = PyBytes_GET_SIZE(readResponse);
		const char* rawBuff = PyBytes_AS_STRING(readResponse);

		if(rawBuff == NULL || rawBuffSize < 1) {
			Py_DECREF(outObj);
			Py_DECREF(readResponse);
			PyErr_SetString(PyExc_RuntimeError, "Read result has unexpected length");
			return NULL;
		}
#else
		if(!PyString_Check(readResponse)) {
			Py_DECREF(outObj);
			Py_DECREF(readResponse);
			PyErr_SetString(PyExc_RuntimeError, "Read result has unexpected type");
			return NULL;
		}

		Py_ssize_t rawBuffSize = PyString_GET_SIZE(readResponse);
		const char* rawBuff = PyString_AS_STRING(readResponse);

		if(rawBuff == NULL || rawBuffSize < 1) {
			Py_DECREF(outObj);
			Py_DECREF(readResponse);
			PyErr_SetString(PyExc_RuntimeError, "Read result has unexpected length");
			return NULL;
		}
#endif

		unsigned PY_LONG_LONG val = *(unsigned char *)(rawBuff);
		contin = (val & 0x80) != 0;
		total += (val & 0x7f) << offset;
		offset += 7;

		Py_DECREF(readResponse);
	}

	PY_LONG_LONG zz = (total >> 1) ^ (-(total & 1));

	PyObject *ret = PyLong_FromLongLong(zz);
	Py_DECREF(readLenArgListObj);
	Py_DECREF(outObj);

	return ret;

}

// ************* Python hooks ***************

static PyMethodDef moduleFunctions[] = {
	{"EncodeVarint",  EncodeVarint, METH_VARARGS, "Varint encode an unsigned number."},
	{"EncodeZigzag",  EncodeZigzag, METH_VARARGS, "Zigzag encode a signed number."},
	{"DecodeVarint",  DecodeVarint, METH_VARARGS, "Decode an unsigned number from a varint stream."},
	{"DecodeZigzag",  DecodeZigzag, METH_VARARGS, "Decode an signed number from a zigzag stream."},
	{NULL, NULL, 0, NULL}
};

#if PY_MAJOR_VERSION >= 3
PyMODINIT_FUNC PyInit_Encoding(void)
{
	static struct PyModuleDef moduledef = {
		PyModuleDef_HEAD_INIT,
		"Encoding",	 /* m_name */
		"Encoding o5m data types",  /* m_doc */
		-1,				  /* m_size */
		moduleFunctions,	/* m_methods */
		NULL,				/* m_reload */
		NULL,				/* m_traverse */
		NULL,				/* m_clear */
		NULL,				/* m_free */
	};
	return PyModule_Create(&moduledef);
}
#else
PyMODINIT_FUNC initEncoding(void)
{
	(void) Py_InitModule("Encoding", moduleFunctions);
}
#endif

