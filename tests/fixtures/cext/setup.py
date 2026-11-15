from setuptools import Extension, setup

setup(ext_modules=[Extension("p94cext", ["p94cext.c"])])
