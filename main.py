#!/usr/bin/env python3
"""
Entry point for POTA Prop
"""
import multiprocessing
from pota_prop import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
