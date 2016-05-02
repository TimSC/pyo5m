#python setup.py build_ext --inplace
from distutils.core import setup, Extension

module1 = Extension('Encoding',
                    sources = ['encoding.c'])

setup (name = 'pyo5m',
       version = '1.0',
       description = 'o5m encoding and decoding',
	   py_modules=['osmxml', 'o5m', 'OsmData'],
       ext_modules = [module1])

