#!/usr/bin/env python
# encoding: utf8
"""Adapted from virtualenv's setup.py.
"""

import sys, os
try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup
    kw = {'scripts': ['scripts/tarsnapper']}
else:
    kw = {'entry_points':
          """[console_scripts]\ntarsnapper = tarsnapper.script:run\n""",
          'zip_safe': False}
import re

here = os.path.dirname(os.path.abspath(__file__))

# Figure out the version
version_re = re.compile(
    r'__version__ = (\(.*?\))')
fp = open(os.path.join(here, 'tarsnapper/__init__.py'))
version = None
for line in fp:
    match = version_re.search(line)
    if match:
        exec("version = %s" % match.group(1))
        version = ".".join(map(str, version))
        break
else:
    raise Exception("Cannot find version in __init__.py")
fp.close()

setup(name='tarsnapper',
      version=version,
      description="Manages tarsnap backups",
      classifiers=[
        'License :: OSI Approved :: BSD License',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 3'
      ],
      author='Michael Elsdoerfer',
      author_email='michael@elsdoerfer.com',
      url='http://github.com/miracle2k/tarsnapper',
      license='BSD',
      packages=['tarsnapper'],
      install_requires = ['argparse>=1.1', 'pyyaml>=3.09', 'python-dateutil>=2.4.0', 'pexpect>=3.1'],
      **kw
)
