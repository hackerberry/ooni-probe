#-*- coding: utf-8 -*-

#import os, sys
#import copy_reg

## Hack to set the proper sys.path. Overcomes the export PYTHONPATH pain.
#sys.path[:] = map(os.path.abspath, sys.path)
#sys.path.insert(0, os.path.abspath(os.getcwd()))

## This is a hack to overcome a bug in python
#from ooni.utils.hacks import patched_reduce_ex
#copy_reg._reduce_ex = patched_reduce_ex

__all__ = ['custodiet']
