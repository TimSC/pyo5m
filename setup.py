#python setup.py build_ext --inplace
from distutils.core import setup, Extension

module1 = Extension('Encoding',
                    sources = ['encoding.c'])

setup (name = 'pyo5m',
       version = '1.0',
       description = 'This is a demo package',
       ext_modules = [module1])

