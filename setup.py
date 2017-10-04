""" Controls how Polyglot should be built by Python """

from distutils.core import setup
from Cython.Build import cythonize

PACKAGES = ['polyglot', 'polyglot.element_manager',
            'polyglot.element_manager.http', 'polyglot.element_manager.isy']

# run setup
setup(
    name="Polyglot",
    version="0.0.8",
    author="Universal Devices Inc",
    platforms="any",
    ext_modules=cythonize('polyglot/*.pyx'),
    packages=PACKAGES
)
