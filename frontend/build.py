"""Thin wrapper: the single build script lives at the repository root (build.py) and writes to ./dist."""
import os, sys, runpy
here = os.path.dirname(os.path.abspath(__file__))
sys.argv = [os.path.join(here, '..', 'build.py')] + sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
